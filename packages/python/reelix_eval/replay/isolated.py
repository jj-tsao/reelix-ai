"""Fresh-interpreter replay, with a fixed local model-call bridge.

Only source/case data cross the worker pipe. The injected client and credentials
stay in the parent; no arbitrary RPC, external server or credential file exists.
"""
from __future__ import annotations
import ast
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from reelix_eval.verification import RevisionEvidence
from reelix_eval.replay.curator import CaseReplay, ReplayRun, cases_digest

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def source_manifest(root: Path) -> dict[str, str]:
    files = {}
    for package in sorted(root.glob('reelix_*')):
        if not package.is_dir() or package.name == 'reelix_eval':
            continue
        for path in sorted(package.rglob('*.py')):
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('revision_source_outside_root')
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('revision_source_empty')
    return files


def manifest_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def expected_prompt(root):
    tree = ast.parse((root/'reelix_agent/curator/curator_prompts.py').read_text())
    assignments = [n for n in tree.body if isinstance(n, ast.Assign) and
                   any(isinstance(t, ast.Name) and t.id == 'CURATOR_PROMPT_S' for t in n.targets)]
    value = ast.literal_eval(assignments[-1].value)
    if not isinstance(value, str): raise ValueError('prompt_identity_unavailable')
    return hashlib.sha256(value.encode()).hexdigest()


def failed_run(cases, label, issue, revision=None):
    return ReplayRun(label, [CaseReplay(c.query_id,c.query_text,ok=False,error=issue,
                     baseline_served_ids=c.baseline_served_ids) for c in cases],
                     revision=revision, evalset_sha256=cases_digest(cases), issues=[issue])


def response_payload(response):
    usage = getattr(response, 'usage', None)
    return {'choices':[{'message':{'content':c.message.content,
                       'refusal':getattr(c.message,'refusal',None)},
                       'finish_reason':getattr(c,'finish_reason',None)} for c in response.choices],
            'usage':{'prompt_tokens':getattr(usage,'prompt_tokens',0) or 0,
                     'completion_tokens':getattr(usage,'completion_tokens',0) or 0}}


async def replay_fresh(cases, client, label, concurrency, source_root, expected_revision, timeout):
    if not cases or len({c.query_id for c in cases}) != len(cases):
        return failed_run(cases,label,'empty_or_duplicate_cases')
    if type(concurrency) is not int or concurrency < 1:
        return failed_run(cases,label,'invalid_concurrency')
    source_root = Path(source_root or SOURCE_ROOT).resolve()
    with tempfile.TemporaryDirectory(prefix='reelix-replay-') as tmp:
        snapshot = Path(tmp)/'source'; snapshot.mkdir()
        try:
            files = source_manifest(source_root)
            for name in files:
                out = snapshot/name; out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source_root/name,out)
            digest = manifest_digest(files)
            if source_manifest(snapshot) != files or source_manifest(source_root) != files:
                return failed_run(cases,label,'source_changed_during_snapshot')
            prompt = expected_prompt(snapshot)
        except Exception:
            return failed_run(cases,label,'source_snapshot_failed')
        expected = digest if expected_revision is None else expected_revision
        if expected != digest:
            return failed_run(cases,label,'expected_revision_mismatch')
        env = {k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','LANG','LC_ALL')}
        env['PYTHONPATH'] = os.pathsep.join((str(snapshot),str(SOURCE_ROOT)))
        proc = await asyncio.create_subprocess_exec(sys.executable,'-B','-m','reelix_eval.replay.worker',
            cwd=tmp,env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,limit=8*1024*1024)
        tasks = set(); lock = asyncio.Lock()
        async def send(value):
            async with lock:
                proc.stdin.write((json.dumps(value,allow_nan=False)+'\n').encode())
                await proc.stdin.drain()
        async def model_call(message):
            try:
                response = await client.chat(**message['kwargs'])
                result = {'kind':'chat_result','id':message['id'],'response':response_payload(response)}
            except Exception as exc:
                result = {'kind':'chat_result','id':message['id'],'error':type(exc).__name__}
            try:
                await send(result)
            except (BrokenPipeError,ConnectionResetError):
                pass  # Worker exit/timeout is handled by the main protocol loop.
        async def discard_stderr():
            while await proc.stderr.read(65536): pass  # Never echo private inputs/errors.
        stderr = asyncio.create_task(discard_stderr())
        wire = None
        async def execute():
            await send({'snapshot':str(snapshot),'expected':expected,'files':files,'prompt':prompt,
                        'cases':[asdict(c) for c in cases],'label':label,'concurrency':concurrency})
            while line := await proc.stdout.readline():
                msg = json.loads(line)
                if msg.get('kind') == 'chat':
                    t = asyncio.create_task(model_call(msg)); tasks.add(t); t.add_done_callback(tasks.discard)
                elif msg.get('kind') == 'result': return msg
                else: raise ValueError('invalid_worker_protocol')
            raise ValueError('worker_closed_without_result')
        try:
            wire = await asyncio.wait_for(execute(),timeout)
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(),10)
            if proc.returncode or wire.get('error'):
                return failed_run(cases,label,'loaded_revision_mismatch' if wire.get('error')=='revision_mismatch' else 'worker_execution_failed')
            r = wire['revision']
            for key in ('files','imported_files','loaded_bindings'): r[key] = tuple(tuple(v) for v in r[key])
            revision = RevisionEvidence(**r)
            result_cases = []
            for c in wire['run']['cases']:
                c['fits'] = {int(k):v for k,v in c['fits'].items()}
                result_cases.append(CaseReplay(**c))
            run = ReplayRun(label,result_cases,revision,cases_digest(cases),wire['run']['execution_completed'],wire['run']['issues'])
            if not revision.matched or revision.expected != expected or dict(revision.files) != files:
                for c in run.cases: c.ok = c.outputs_valid = False; c.error='loaded_revision_mismatch'
                run.issues.append('loaded_revision_mismatch')
            return run
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError): raise
            return failed_run(cases,label,'worker_timeout' if isinstance(exc,asyncio.TimeoutError) else 'worker_protocol_failed')
        finally:
            for task in tasks: task.cancel()
            if tasks: await asyncio.gather(*tasks,return_exceptions=True)
            if proc.returncode is None:
                proc.kill(); await proc.wait()
            await stderr
