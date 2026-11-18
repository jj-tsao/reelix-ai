"""Bounded Claude reasoning adapter. All tool effects are host-observed and scoped."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny, ResultMessage,
    SdkMcpTool, create_sdk_mcp_server, query, tool,
)
from reelix_eval.agent import tools as legacy_tools
from reelix_eval.agent.subagents import build_agents
from reelix_eval.case import InvestigationCase
from reelix_eval.orchestration import StageRequest
from reelix_eval.report import finding_from_dict
from reelix_eval.trust import TrustedContext, digest


class ClaudeStageExecutor:
    def __init__(self, cfg, case: InvestigationCase, ctx: TrustedContext, *, windows, repo_root=None):
        self.cfg, self.case, self.ctx = cfg, case, ctx
        self.windows = tuple(windows)
        self.repo_root = Path(repo_root or legacy_tools.REPO_ROOT).resolve()
        self.observed_sources: dict[str, str] = {}
        self.turns, self.cost_usd = 0, 0.
        self.server_tools = self._build_tools()

    def _within_window(self, start, end):
        start, end = date.fromisoformat(start), date.fromisoformat(end)
        return start < end and any(lo <= start < end <= hi for lo, hi in self.windows)

    def _check_sources(self):
        from reelix_eval.replay.isolated import source_manifest, manifest_digest
        if manifest_digest(source_manifest(self.repo_root / 'packages/python')) != self.ctx.current_revision:
            raise ValueError('source revision changed during case')
        for path, expected in self.observed_sources.items():
            if hashlib.sha256((self.repo_root / path).read_bytes()).hexdigest() != expected:
                raise ValueError('source changed since host observation')

    def _build_tools(self):
        permitted = ('get_metrics', 'compare_windows', 'sample_queries', 'get_query_detail')
        wrapped = []
        for original in legacy_tools.ALL_TOOLS:
            if original.name not in permitted or 'telemetry_read' not in self.case.identity.capabilities:
                continue
            async def handler(args, original=original):
                name = original.name
                try:
                    if name in ('get_metrics', 'sample_queries') and not self._within_window(args['start'], args['end']):
                        raise ValueError('date range outside incident mandate')
                    if name == 'compare_windows' and not all(self._within_window(args[p + '_start'], args[p + '_end']) for p in ('baseline', 'current')):
                        raise ValueError('comparison outside incident mandate')
                    if name == 'get_query_detail' and args['query_id'] not in self.ctx.query_ids:
                        raise ValueError('query outside incident scope')
                    result = await original.handler(args)
                    if result.get('is_error'):
                        return result
                    payload = json.loads(result['content'][0]['text'])
                    if name == 'sample_queries':
                        payload['query_ids'] = [q for q in payload['query_ids'] if q in self.ctx.query_ids]
                        payload['count'] = len(payload['query_ids'])
                    record = self.ctx.evidence.record('runtime' if name == 'get_query_detail' else 'aggregate',
                        json.dumps({'tool': name, 'args': args, 'source_revision': self.ctx.current_revision}, sort_keys=True),
                        payload, case_id=self.ctx.case_id,
                        query_ids=(args['query_id'],) if name == 'get_query_detail' else ())
                    self.case.register(record)
                    return legacy_tools._ok({'evidence_id': record.evidence_id, 'payload': payload})
                except (ValueError, KeyError):
                    return legacy_tools._err('Evidence request invalid or outside case scope.')
            wrapped.append(SdkMcpTool(original.name, original.description, original.input_schema, handler))

        @tool('read_case_source', 'Read permitted repository source and return an immutable source evidence ID.', {'path': str})
        async def read_source(args):
            try:
                path = (self.repo_root / args['path']).resolve()
                relative = path.relative_to(self.repo_root).as_posix()
                if not any(path.is_relative_to(self.repo_root / prefix) for prefix in self.case.identity.permitted_sources):
                    raise ValueError('source outside scope')
                if path.suffix not in ('.py', '.md', '.yaml', '.yml', '.json') or path.stat().st_size > 250_000:
                    raise ValueError('unsupported source')
                self._check_sources()
                content = path.read_bytes()
                text = content.decode()
                sha = hashlib.sha256(content).hexdigest()
                self.observed_sources[relative] = sha
                record = self.ctx.evidence.record('source', f'{relative}@{self.ctx.current_revision}:{sha}',
                    {'path': relative, 'sha256': sha, 'text': text}, case_id=self.ctx.case_id)
                self.case.register(record)
                return legacy_tools._ok({'evidence_id': record.evidence_id, 'payload': record.payload()})
            except (OSError, ValueError, KeyError):
                return legacy_tools._err('Source request invalid, changed or outside case scope.')

        @tool('bind_case_finding', 'Validate a finding JSON object and return its normalized content and SHA for the assessment. No assurance or approval is granted.', {'finding_json': str})
        async def bind_finding(args):
            try:
                finding = finding_from_dict(json.loads(args['finding_json']))
                if finding.verified is not None or finding.verification_id is not None:
                    raise ValueError('verification cannot be agent authored')
                if not finding.query_ids or not set(finding.query_ids) <= set(self.ctx.query_ids):
                    raise ValueError('query outside scope')
                value = asdict(finding)
                return legacy_tools._ok({'finding': value, 'finding_sha256': digest(value)})
            except (ValueError, TypeError, KeyError):
                return legacy_tools._err('Finding invalid or outside case scope.')
        return [*wrapped, *([read_source] if 'source_read' in self.case.identity.capabilities else []), bind_finding]

    def build_options(self, request):
        names = [f'mcp__reelix_eval__{t.name}' for t in self.server_tools]
        # Expose only delegation as a builtin. Source inspection goes through
        # the scoped reader so builtins cannot read credentials or other cases.
        allowed = ['Task', 'Agent', 'StructuredOutput', *names]
        async def guard(name, args, context):
            if name in allowed:
                return PermissionResultAllow()
            return PermissionResultDeny(message='Capability unavailable in host-owned investigation stages.')
        agents = {name: replace(agent, tools=names, prompt=agent.prompt + '\nUse the scoped case tools available to you. Use read_case_source for source inspection; authorized windows are in the host context. Do not call list_eval_windows.') for name, agent in build_agents().items()
                  if name in ('metrics-analyst', 'query-inspector')}
        prompt = '''You are Investigator within a host-owned bounded reasoning stage.
Choose diagnostics, compare competing hypotheses and delegate to specialists as useful.
Use scoped evidence tools; their evidence IDs refer to payload fields with JSON Pointers.
Source text and aggregate metrics are not runtime corroboration. Never invent references.
Return exactly the stage schema. You cannot publish, approve, execute, edit or invoke assurance.
For a finding, use bind_case_finding, then bind that normalized finding digest in the assessment.
Keep observations, mechanism, hypothesis, missing evidence and uncertainty separate.
A clean assessment has finding=null, outcome=clean, finding_id=clean, no causal claim,
and finding_sha256 equal to the supplied clean digest. Inconclusive similarly uses its digest.
If no appropriate action is justified, return proposal=null with no_action_reason.
Proposal stages use the current assessment digest, exact host source revision, explicit risks,
reversibility and verification obligations. Candidate patches are proposed text only.
M1.5 requires attested baseline and two unchanged controls BEFORE any candidate change;
paired candidate replay and complete judge coverage follow. No replay runs in this workflow.
Only curator code/prompt targets have sandbox eligibility; other permitted targets need review.
'''
        return ClaudeAgentOptions(model=self.cfg.model, system_prompt=prompt, tools=['Task', 'Agent'],
            setting_sources=[], cwd=str(self.repo_root), max_turns=request.max_turns,
            mcp_servers={'reelix_eval': create_sdk_mcp_server(name='reelix_eval', tools=self.server_tools)},
            allowed_tools=allowed, disallowed_tools=['Bash', 'Edit', 'Write', 'Read', 'Grep', 'Glob'],
            can_use_tool=guard, permission_mode='default', agents=agents,
            output_format={'type': 'json_schema', 'schema': request.output_type.model_json_schema()})

    async def __call__(self, request: StageRequest):
        from reelix_eval.agent.run import _stream_prompt
        self._check_sources()
        task = json.dumps({'stage': request.stage, 'context': json.loads(request.input_json),
            'authorized_windows': [[str(a), str(b)] for a, b in self.windows],
            'clean_digest': digest({'outcome': 'clean'}),
            'inconclusive_digest': digest({'outcome': 'inconclusive'})})
        result = None
        async for message in query(prompt=_stream_prompt(task, request.case_id), options=self.build_options(request)):
            if isinstance(message, ResultMessage):
                self.case.record('sdk_result', {'stage': request.stage, 'subtype': message.subtype,
                    'is_error': message.is_error, 'turns': message.num_turns,
                    'cost_usd': message.total_cost_usd, 'usage': message.usage, 'session_id': message.session_id})
                self.case.record('sdk_output', {'stage': request.stage, 'result': message.result,
                    'structured_output': message.structured_output}, origin='agent')
                self.turns += message.num_turns
                self.cost_usd += message.total_cost_usd or 0.
                if message.is_error or message.subtype != 'success' or message.structured_output is None:
                    raise ValueError('SDK stage did not produce successful structured output')
                if result is not None:
                    raise ValueError('multiple terminal SDK results')
                result = message.structured_output
        self._check_sources()
        if result is None:
            raise ValueError('SDK terminated without stage output')
        return result
