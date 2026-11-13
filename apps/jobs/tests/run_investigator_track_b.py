"""Isolated Track B SDK runner; no oracle imports, service config or DB clients.

--preflight is model-free. --execute initializes the SDK, verifies its live MCP
surface, then permits exactly one bounded synthetic reasoning query.
"""
import argparse
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from datetime import datetime, timezone

# Retain only local process essentials and optional Claude authentication. Do not
# inherit production keys, proxies, PYTHONPATH, or prior response/thinking caps.
ESSENTIAL = {'HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'SHELL', 'LANG', 'TERM',
             'CLAUDE_CODE_OAUTH_TOKEN'}
clean_env = {k: v for k, v in os.environ.items() if k in ESSENTIAL or k.startswith('LC_')}
os.environ.clear()
os.environ.update(clean_env)
os.environ['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
os.umask(0o077)

from claude_agent_sdk import (AgentDefinition, ClaudeAgentOptions, ClaudeSDKClient,
    HookMatcher, PermissionResultAllow, PermissionResultDeny, ResultMessage,
    SystemMessage, create_sdk_mcp_server, tool)
from mcp import types as mt
from track_b_fixture import FixtureSession, PUBLIC, SOURCE
from track_b_workflow import REPO, adapted_prompts, load_originals

ROOT = REPO / 'apps/jobs/reports/investigator-m1-baseline/track-b'
ROOT.mkdir(exist_ok=True, mode=0o700)
LIMITS = {'sdk_budget_stop_usd': 2.0, 'wall_seconds': 600, 'tools': 40,
          'delegations': 2, 'detail_reads': 6, 'sample_limit': 3, 'lead_turns': 60}
PREFIX = 'mcp__reelix_fixture__'
READS = {'sample_queries', 'get_query_detail', 'get_source_excerpt'}
ALL = READS | {'write_report'}
DENIED = ['Read', 'Grep', 'Glob', 'Bash', 'Edit', 'Write', 'WebSearch', 'WebFetch',
          'Skill', 'ToolSearch', 'NotebookEdit', 'Computer', 'execute_sql']
FORBIDDEN_MODULES = {'core.config', 'reelix_eval.db', 'reelix_eval.store',
                     'sqlalchemy', 'psycopg', 'qdrant_client', 'openai'}


def save(name, data):
    (ROOT/name).write_text(json.dumps(data, indent=2, default=serialize)+'\n')


def serialize(value):
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else str(value)


class IsolationError(RuntimeError): pass


class State:
    def __init__(self, session):
        self.session = session
        self.ids = {d['query_id'] for d in json.loads((PUBLIC/'observations.json').read_text())['details']}
        self.live = False
        self.reset()

    def reset(self):
        self.tools = self.mcp = self.delegations = self.details = 0
        self.seen = set()
        self.denials = []

    def log(self, kind, data):
        filename = 'trace-private.jsonl' if self.live else 'isolation-probes-private.jsonl'
        with (ROOT/filename).open('a') as f:
            f.write(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),
                                'kind':kind,'data':data}, default=serialize)+'\n')

    def permission_reason(self, name, args, role='lead'):
        if name in ('Task','Agent'):
            if role != 'lead' or args.get('subagent_type') != 'query-inspector':
                return 'Only lead may delegate to query-inspector'
            return None
        if not name.startswith(PREFIX): return 'Tool not in fixture surface'
        short = name[len(PREFIX):]
        if short not in (ALL if role == 'lead' else READS): return 'Tool unavailable to this role'
        if short == 'get_source_excerpt' and args.get('path') != SOURCE: return 'Source not allowlisted'
        if short == 'get_query_detail' and args.get('query_id') not in self.ids: return 'Unknown fixture ID'
        if short == 'sample_queries':
            n = args.get('limit')
            if type(n) is not int or not 1 <= n <= 3: return 'Sample limit is three'
        return None

    async def pre(self, data, tool_use_id, context):
        name, args = data.get('tool_name',''), data.get('tool_input',{})
        role = data.get('agent_type') or ('unknown' if data.get('agent_id') else 'lead')
        reason = self.permission_reason(name,args,role)
        if tool_use_id not in self.seen:
            self.seen.add(tool_use_id); self.tools += 1
            if self.tools > LIMITS['tools']: reason = 'Global tool limit'
            if name in ('Task','Agent') and not reason:
                if self.delegations >= LIMITS['delegations']: reason = 'Delegation limit'
                else: self.delegations += 1
        self.log('pre_tool',{'name':name,'input':args,'role':role,'agent_id':data.get('agent_id'),
                             'tool_use_id':tool_use_id,'denied':reason})
        if reason:
            self.denials.append(reason)
            return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                                          'permissionDecisionReason':reason}}
        return {}

    async def permission(self, name, args, context):
        # The hook is authoritative for role/count checks even when allowed_tools
        # auto-approves a call before this secondary callback is consulted.
        reason = self.permission_reason(name,args)
        return PermissionResultDeny(message=reason) if reason else PermissionResultAllow()

    async def event(self,data,tool_use_id,context):
        self.log('hook',data)
        return {}

    async def dispatch(self, name, args):
        self.mcp += 1
        self.log('mcp_input',{'name':name,'input':args})
        try:
            if self.mcp > LIMITS['tools']: raise PermissionError('MCP call limit')
            if name not in ALL: raise PermissionError('Unknown fixture tool')
            if name == 'get_query_detail':
                self.details += 1
                if self.details > LIMITS['detail_reads']: raise PermissionError('Detail read limit')
            if name == 'write_report': result = self.write_report(args)
            else: result = self.session.call(name,args)
            self.log('mcp_output',{'name':name,'result':result})
            return {'content':[{'type':'text','text':json.dumps(result)}]}
        except Exception as e:
            self.log('mcp_error',{'name':name,'error_class':type(e).__name__,'message':str(e)})
            return {'content':[{'type':'text','text':str(e)}],'is_error':True}

    def write_report(self,args):
        if set(args) != {'case_assessments','findings','blind_spots'}:
            raise ValueError('Only the three report JSON fields are accepted; no paths')
        assessments = json.loads(args['case_assessments'])
        findings = json.loads(args['findings']); spots = json.loads(args['blind_spots'])
        if not isinstance(assessments,list) or {a.get('query_id') for a in assessments} != self.ids or len(assessments)!=3:
            raise ValueError('Report must assess each of the three supplied IDs once')
        if not isinstance(findings,list) or not isinstance(spots,list): raise ValueError('Expected JSON arrays')
        # Reuse existing rendering without importing agent/config/client modules.
        spec = importlib.util.spec_from_file_location('_track_b_report', REPO/'packages/python/reelix_eval/report.py')
        mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
        fields = {f.name for f in dataclasses.fields(mod.Finding)}
        typed = []
        for f in findings:
            defaults = dict(title='Untitled',symptom='',evidence='',hypothesis='',confidence='low',proposed_fix='')
            defaults.update({k:v for k,v in f.items() if k in fields})
            typed.append(mod.Finding(**defaults))
        rep = mod.Report(run_id='track-b-isolated',window='three synthetic cases; no historical baseline',
                         sample_sizes={'cases':3},findings=typed,extra_blind_spots=spots,
                         git_sha=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=REPO,capture_output=True,text=True,check=True).stdout.strip())
        path = mod.write(rep,ROOT/'reports')
        data = rep.to_dict(); data['case_assessments'] = assessments; data['synthetic'] = True
        (path.parent/'findings.json').write_text(json.dumps(data,indent=2)+'\n')
        with path.open('a') as f:
            f.write('\n## Synthetic case assessments\n\n'+json.dumps(assessments,indent=2)+'\n')
        return {'report':str(path),'findings':len(typed),'cases':3,'synthetic':True}


def build_options(state, workspace):
    schemas = {
        'sample_queries':{'limit':int,'filter':str},
        'get_query_detail':{'query_id':str,'served_only':bool},
        'get_source_excerpt':{'path':str},
        'write_report':{'case_assessments':str,'findings':str,'blind_spots':str},
    }
    descriptions = {
        'sample_queries':'List up to three supplied synthetic IDs; census membership is not a symptom.',
        'get_query_detail':'Read one supplied synthetic case, including missing fields; no external backfill.',
        'get_source_excerpt':f'Return the frozen source snapshot for the only allowed path: {SOURCE}. No other files.',
        'write_report':'''Write the local fixture report. All arguments are JSON array strings.
case_assessments: one object per supplied ID with query_id, observations, stage_attribution,
source_mechanisms, unconfirmed_causes, confidence, limitations, disconfirming_examples,
production_occurrence. State what is observed versus conditional/unconfirmed. Missing evidence
may justify abstention; no production inference is available. findings uses existing fields:
title,symptom,evidence,hypothesis,confidence,proposed_fix,location,query_ids,verified.
blind_spots is a list of evidence/coverage limits. Do not claim verified fixes.''',
    }
    definitions=[]
    for name,schema in schemas.items():
        async def handler(args,name=name): return await state.dispatch(name,args)
        definitions.append(tool(name,descriptions[name],schema)(handler))
    server=create_sdk_mcp_server('reelix_fixture',tools=definitions)
    lead,inspector=adapted_prompts()
    role=AgentDefinition(description='Inspect supplied synthetic cases and frozen source with calibrated evidence limits.',
                         prompt=inspector,tools=[PREFIX+n for n in sorted(READS)],
                         disallowedTools=[*DENIED,'Task','Agent'])
    options=ClaudeAgentOptions(model='claude-opus-5',system_prompt=lead,cwd=str(workspace),
        tools=['Task'],allowed_tools=['Task',*[PREFIX+n for n in sorted(ALL)]],
        disallowed_tools=DENIED,agents={'query-inspector':role},
        mcp_servers={'reelix_fixture':server},strict_mcp_config=True,
        setting_sources=[],skills=[],plugins=[],add_dirs=[],
        max_turns=LIMITS['lead_turns'],max_budget_usd=LIMITS['sdk_budget_stop_usd'],
        can_use_tool=state.permission,include_hook_events=True,
        hooks={'PreToolUse':[HookMatcher(hooks=[state.pre])],
               'PostToolUse':[HookMatcher(hooks=[state.event])],
               'PostToolUseFailure':[HookMatcher(hooks=[state.event])],
               'SubagentStart':[HookMatcher(hooks=[state.event])],
               'SubagentStop':[HookMatcher(hooks=[state.event])]},
        stderr=lambda line:state.log('cli_stderr',line))
    return options,server


async def check_surface(options,server,state,workspace):
    checks={}
    listed=await server['instance'].request_handlers[mt.ListToolsRequest](mt.ListToolsRequest(method='tools/list'))
    checks['actual_mcp_manifest_closed']={t.name for t in listed.root.tools}==ALL
    call=server['instance'].request_handlers[mt.CallToolRequest]
    async def invoke(name,args):
        result=await call(mt.CallToolRequest(method='tools/call',params=mt.CallToolRequestParams(name=name,arguments=args)))
        return result.root
    checks['registered_source_lookup_works']=not (await invoke('get_source_excerpt',{'path':SOURCE})).isError
    probes=[('Read',{'file_path':'/outside/oracle.json'}),('Grep',{'path':'/outside'}),
            ('Bash',{'command':'env'}),('execute_sql',{'query':'SELECT 1'}),
            ('run_judge',{'persist':True}),('replay_curator',{}),
            (PREFIX+'get_source_excerpt',{'path':'../oracle.json'}),
            (PREFIX+'get_query_detail',{'query_id':'../oracle.json'})]
    for role in ('lead','query-inspector'):
        results=[]
        for i,(name,args) in enumerate(probes):
            hook=await options.hooks['PreToolUse'][0].hooks[0]({'tool_name':name,'tool_input':args,'agent_type':role},f'probe-{role}-{i}',None)
            results.append(hook.get('hookSpecificOutput',{}).get('permissionDecision')=='deny')
        checks[role+'_assembled_hook_denies_escapes']=all(results)
    checks['registered_rpc_denies_unknown_and_traversal']=all([
        (await invoke('execute_sql',{'query':'SELECT 1'})).isError,
        (await invoke('run_judge',{'persist':True})).isError,
        (await invoke('get_source_excerpt',{'path':'/outside/oracle.json'})).isError,
        (await invoke('get_query_detail',{'query_id':'../oracle.json','served_only':False})).isError,
        (await invoke('write_report',{'path':'../oracle.json'})).isError,
    ])
    checks['role_has_no_native_tools']=set(options.agents['query-inspector'].tools)=={PREFIX+n for n in READS}
    checks['inspector_cannot_write_or_delegate']=all(state.permission_reason(name,args,'query-inspector') is not None for name,args in (
        (PREFIX+'write_report',{}),('Agent',{'subagent_type':'query-inspector'})))
    checks['only_one_diagnostic_role']=set(options.agents)=={'query-inspector'}
    checks['native_tools_only_delegation']=options.tools==['Task']
    checks['settings_plugins_skills_closed']=options.setting_sources==[] and options.strict_mcp_config and options.plugins==[] and options.skills==[] and options.add_dirs==[]
    checks['stock_response_thinking_and_subagent_defaults']=options.max_thinking_tokens is None and options.thinking is None and options.agents['query-inspector'].maxTurns is None and 'CLAUDE_CODE_MAX_OUTPUT_TOKENS' not in os.environ
    checks['workspace_has_only_public_inputs']=sorted(p.name for p in workspace.iterdir())==['observations.json','source-context.json']
    checks['no_production_modules']=not (FORBIDDEN_MODULES & set(sys.modules))
    checks['environment_has_no_service_credentials']=not any(any(token in k.upper() for token in ('DATABASE','QDRANT','OPENAI','SUPABASE','JUDGE','AWS')) for k in os.environ)
    checks['budget_configured']=options.max_budget_usd==2 and options.max_turns==60
    # Exercise the handler's independent cap, not just the SDK-side hook.
    state.details=LIMITS['detail_reads']
    checks['actual_detail_cap_denies']=bool((await invoke('get_query_detail',{
        'query_id':sorted(state.ids)[0],'served_only':False})).isError)
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
    transport=SubprocessCLITransport(prompt='',options=options)
    transport._cli_path=transport._find_cli()
    command=transport._build_command()
    checks['sdk_serializes_native_budget_and_tool_restriction']=(
        command[command.index('--max-budget-usd')+1]=='2.0' and
        command[command.index('--tools')+1]=='Task' and '--strict-mcp-config' in command)
    save('isolation-offline.json',{'checks':checks,'passed':all(checks.values()),'generation_calls':0})
    if not all(checks.values()): raise IsolationError('Offline SDK/tool isolation check failed')
    state.reset()
    return checks


async def main(execute):
    if execute and (ROOT/'attempt-started.json').exists(): raise IsolationError('Single fixture run already attempted')
    with TemporaryDirectory(prefix='reelix-track-b-',dir='/private/tmp') as tmp:
        workspace=Path(tmp)
        for name in ('observations.json','source-context.json'): shutil.copyfile(PUBLIC/name,workspace/name)
        session=FixtureSession(workspace);state=State(session)
        options,server=build_options(state,workspace)
        checks=await check_surface(options,server,state,workspace)
        originals=load_originals();adapted=adapted_prompts()
        save('prompts.json',{'original_lead':originals[0],'original_inspector':originals[1],
                             'fixture_lead':adapted[0],'fixture_inspector':adapted[1]})
        save('configuration.json',{'limits':LIMITS,'model':options.model,'roles':list(options.agents),
             'fixture_hashes':{n:hashlib.sha256((workspace/n).read_bytes()).hexdigest() for n in ('observations.json','source-context.json')},
             'prompt_hashes':[hashlib.sha256(p.encode()).hexdigest() for p in adapted],
             'production_modules_loaded':sorted(FORBIDDEN_MODULES & set(sys.modules)),
             'environment_keys':sorted(os.environ),'workspace':str(workspace)})
        if not execute:
            print(json.dumps({'offline_isolation':'passed','checks':len(checks),'model_calls':0}));return
        outcome={};started=None
        try:
            # Initialize without sending a prompt: MCP status is checked before
            # any model generation, on the same SDK client used for the run.
            async with ClaudeSDKClient(options=options) as client:
                status=await asyncio.wait_for(client.get_mcp_status(),timeout=30)
                save('sdk-mcp-pre-generation.json',status)
                entries=status.get('mcpServers',[])
                if any(e.get('name')!='reelix_fixture' or e.get('status')!='connected' for e in entries):
                    raise IsolationError('Unexpected external/live MCP surface')
                # This SDK/CLI returned an empty mcp_status before a prompt.
                # Inspect and exercise the initialized SDK's real message bridge
                # instead of treating absent status metadata as a connected tool.
                q=client._query
                if set(q.sdk_mcp_servers)!={'reelix_fixture'} or len(q.hook_callbacks)!=5:
                    raise IsolationError('SDK registry or hooks differ from assembly')
                bridge=await q._handle_sdk_mcp_request('reelix_fixture',{
                    'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}})
                names={t['name'] for t in bridge.get('result',{}).get('tools',[])}
                if names!=ALL: raise IsolationError('Initialized SDK bridge manifest differs')
                bridge_checks={}
                for n,args in [('execute_sql',{'query':'SELECT 1'}),
                               ('get_source_excerpt',{'path':'../oracle.json'})]:
                    res=await q._handle_sdk_mcp_request('reelix_fixture',{
                        'jsonrpc':'2.0','id':2,'method':'tools/call',
                        'params':{'name':n,'arguments':args}})
                    bridge_checks[n]=bool(res.get('error') or res.get('result',{}).get('isError'))
                if not all(bridge_checks.values()):raise IsolationError('Initialized SDK bridge escape allowed')
                save('sdk-bridge-pre-generation.json',{'manifest':bridge,'denial_checks':bridge_checks,
                    'registered_servers':list(q.sdk_mcp_servers),'registered_hooks':len(q.hook_callbacks),
                    'generation_calls':0})
                save('sdk-initialization-private.json',await client.get_server_info())
                if FORBIDDEN_MODULES & set(sys.modules):raise IsolationError('Production client module loaded')
                state.reset();state.live=True
                save('attempt-started.json',{'utc':datetime.now(timezone.utc).isoformat(),'limits':LIMITS,'sdk_isolation_passed_before_generation':True})
                print(json.dumps({'event':'sdk_isolation_passed','model_generation_starting':True}),flush=True)
                started=time.monotonic()
                async def run():
                    task=('Assess each supplied synthetic query ID: '+', '.join(sorted(state.ids))+
                          '. Inspect all candidates and the frozen source; report the available evidence and its limits for each case. '
                          'No historical baseline, external judge or production services are available. '
                          'At most 40 tools, two delegations and six detail reads; preserve time to write_report. '
                          'This is an isolated diagnostic reasoning test, not a stock investigation.')
                    await client.query(task)
                    async for msg in client.receive_response():
                        state.log('sdk_message',msg)
                        if isinstance(msg,SystemMessage) and msg.subtype=='init':
                            advertised=set(msg.data.get('tools',[]))
                            permitted={PREFIX+n for n in ALL}|{'Task','Agent'}
                            if not advertised<=permitted:raise IsolationError('Unexpected native tool advertised')
                        if isinstance(msg,ResultMessage):
                            save('sdk-result-private.json',dataclasses.asdict(msg))
                            return {'status':'returned','subtype':msg.subtype,'turns':msg.num_turns,
                                    'cost_usd':msg.total_cost_usd,'is_error':msg.is_error}
                    raise RuntimeError('No SDK result')
                outcome=await asyncio.wait_for(run(),timeout=LIMITS['wall_seconds'])
        except Exception as e:
            outcome={'status':'failed','error_class':type(e).__name__,'message':str(e)}
        finally:
            outcome.update(elapsed_seconds=round(time.monotonic()-started,3) if started else None,
                           tool_calls=state.tools,mcp_calls=state.mcp,delegations=state.delegations,
                           detail_reads=state.details,denials=state.denials,
                           report_present=(ROOT/'reports/track-b-isolated/report.md').exists(),
                           production_modules_loaded=sorted(FORBIDDEN_MODULES & set(sys.modules)))
            save('outcome.json',outcome)
            print(json.dumps(outcome),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--preflight',action='store_true');g.add_argument('--execute',action='store_true')
    a=p.parse_args();asyncio.run(main(a.execute))
