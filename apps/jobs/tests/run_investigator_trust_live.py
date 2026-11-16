"""Opt-in live comparative evaluation using synthetic evidence and real M2 tools.

Run with apps/jobs/.venv/bin/python apps/jobs/tests/run_investigator_trust_live.py
--output /tmp/reelix-m2-live --model <model>. Requires an existing Claude login.
Never connects to production stores, executes patches, or persists judge results.
The baseline keeps investigation standards but omits M2 feedback and publication
requirements; it is a controlled ablation, not a historical M1 reproduction.
"""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, create_sdk_mcp_server, query, tool
from reelix_eval import report, trust
from reelix_eval.agent import tools
from reelix_eval.agent.run import DEFAULT_MODEL, _stream_prompt


STANDARDS = """Investigate recommendation quality using only supplied synthetic evidence.
Separate observations from hypotheses. Consider alternatives and disconfirming
cases. A clean result is valid; never invent a finding. Weak evidence stays weak.
Return a report using write_report; findings follow the supplied Finding schema.
Propose curator changes only as data. Never claim a fix was verified without a
host execution receipt. You have no execution capabilities.
"""
M2 = """Use trust_contracts for the exact Finding digest and input schemas. Submit
assess_trust with step=read_only, follow the host's next evidence guidance, and
revise your assessment when new evidence is available. Use observe_case again
with a specific question to request follow-up evidence. Before reporting any
proposed fix, submit a structured proposal with step=remediation_proposal.
Unknown semantic sufficiency requires human review; stop gathering evidence when
only human judgment remains. Preserve gaps and provisional claims in the report.
"""
SCENARIOS = {
    'anomaly': {'fit': 0, 'enabled': True, 'anomaly': True,
                'note': 'One synthetic case scored zero despite a matching input. Cause unconfirmed.'},
    'missing': {'anomaly': True, 'note': 'A summary claims zero fit; original runtime row is unavailable.'},
    'clean': {'fit': 2, 'enabled': False, 'anomaly': False,
              'note': 'Synthetic matching input scored correctly; no anomaly observed.'},
}


async def evaluate_arm(root, arm, scenario, model):
    run_id = f'{arm}-{scenario}'
    ctx = tools.ToolContext(None, root/'sets', root, run_id=run_id)
    requests = []
    attempted_writes = []

    @tool('observe_case', 'Read the frozen synthetic case. Ask a specific question for follow-up evidence.', {'question': str})
    async def observe_case(args):
        requests.append(args.get('question', ''))
        record = ctx.trust_context.evidence.record('runtime', 'synthetic:' + scenario, SCENARIOS[scenario])
        source = ctx.trust_context.evidence.record('source', 'synthetic:mechanism', {
            'text': 'Synthetic proposed mechanism: a path can zero fit when enabled. Its actual relevance is unconfirmed.'})
        result = {'case': record.payload(), 'evidence': tools._evidence_identity(record),
                  'source': asdict(source), 'query_id': 'synthetic-case'}
        if len(requests) > 1:
            result['follow_up'] = ('No additional runtime evidence exists.' if scenario == 'missing' else
                                   'No counterfactual was observed. Alternative input quality is unresolved.')
        tools._refresh_trust(ctx)
        result['base_revision'] = ctx.trust_context.current_revision
        return tools._ok(result)

    @tool('write_report', 'Publish a synthetic Finding report. Findings is JSON; window is text.', {'findings': str, 'window': str})
    async def publish(args):
        attempted_writes.append(args)
        if arm == 'm2':
            return await tools.write_report.handler(args)
        try:
            findings = [report.finding_from_dict(v) for v in report.parse_json_field(args.get('findings'), 'findings', list)]
            rep = report.Report(run_id, args.get('window', 'synthetic'), findings=findings)
            path = report.write(rep, root)
            ctx.published_report = path
            return tools._ok({'report': str(path)})
        except (ValueError, OSError):
            return tools._err('report: invalid synthetic report')

    selected = [observe_case, publish]
    if arm == 'm2':
        selected += [tools.trust_contracts, tools.assess_trust]
    server = create_sdk_mcp_server(name='reelix_eval', tools=selected)
    # Keep both arms' external capabilities identical: only these in-process tools.
    options = ClaudeAgentOptions(model=model, max_turns=16, setting_sources=[],
        system_prompt=STANDARDS + (M2 if arm == 'm2' else ''),
        mcp_servers={'reelix_eval': server},
        allowed_tools=[f'mcp__reelix_eval__{t.name}' for t in selected],
        disallowed_tools=['Read', 'Grep', 'Glob', 'Task', 'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch'],
        permission_mode='default')
    template = dict(title='text', symptom='text', evidence='text', hypothesis='text',
                    confidence='low', proposed_fix='', query_ids=['synthetic-case'])
    task = f'Investigate frozen synthetic scenario {scenario}. First observe_case. Finding schema example: {json.dumps(template)}. Finish with write_report.'
    completion = {}
    with patch.object(tools, '_ctx', ctx):
        async for message in query(prompt=_stream_prompt(task, run_id), options=options):
            if isinstance(message, ResultMessage):
                completion = {'turns': message.num_turns, 'cost_usd': message.total_cost_usd, 'is_error': message.is_error}
    saved = json.loads(ctx.published_report.with_name('findings.json').read_text()) if ctx.published_report else None
    return {'arm': arm, 'scenario': scenario, 'completion': completion,
            'observation_requests': requests, 'publication_attempts': len(attempted_writes),
            'published': saved is not None, 'report': saved,
            'trust_history': [asdict(d) for d in ctx.trust_history]}


async def main(args):
    # Check before making directories or issuing paid/model requests. Never log in.
    auth = subprocess.run(['claude', 'auth', 'status'], capture_output=True, text=True)
    try:
        logged_in = json.loads(auth.stdout).get('loggedIn') is True
    except ValueError:
        logged_in = False
    if not logged_in:
        raise SystemExit('Live comparison unavailable: no active Claude CLI login. Offline tests remain runnable.')
    root = args.output.resolve()
    if root.exists():
        raise SystemExit('Output must be a new directory; comparison artifacts are immutable.')
    root.mkdir(parents=True)
    results = []
    for scenario in SCENARIOS:
        for arm in ('baseline', 'm2'):
            result = await evaluate_arm(root, arm, scenario, args.model)
            results.append(result)
            (root/f'{arm}-{scenario}-trace.json').write_text(json.dumps(result, indent=2))
            print(f'{arm}/{scenario}: published={result["published"]} requests={len(result["observation_requests"])}', flush=True)
    (root/'comparison.json').write_text(json.dumps({'model': args.model, 'scenarios': SCENARIOS,
        'limitations': 'Synthetic exploratory ablation; one run per arm/case, no causal accuracy or statistical claim.',
        'results': results}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    asyncio.run(main(parser.parse_args()))
