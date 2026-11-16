"""Private replay worker entry point. Fixed chat/result protocol, no client keys."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
import hashlib
import inspect
import json
import marshal
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from reelix_eval.replay.isolated import source_manifest, manifest_digest
from reelix_eval.replay.curator import _replay_local
from reelix_eval.replay.evalset import EvalCase, FrozenCandidate
from reelix_eval.verification import RevisionEvidence


def namespace(value):
    if isinstance(value,dict): return SimpleNamespace(**{k:namespace(v) for k,v in value.items()})
    if isinstance(value,list): return [namespace(v) for v in value]
    return value


class ModelBridge:
    def __init__(self): self.pending={}; self.counter=0
    async def chat(self, **kwargs):
        self.counter+=1; ident=self.counter
        future=asyncio.get_running_loop().create_future();self.pending[ident]=future
        print(json.dumps({'kind':'chat','id':ident,'kwargs':kwargs}),flush=True)
        return namespace(await future)
    async def receive(self):
        while line := await asyncio.to_thread(sys.stdin.readline):
            data=json.loads(line)
            future=self.pending.pop(data['id'])
            if data.get('error'):future.set_exception(RuntimeError('model_bridge_failed'))
            else:future.set_result(data['response'])


def identity(request):
    root=Path(request['snapshot']).resolve()
    from reelix_agent.curator import curator_agent, curator_prompts, curator_tiers
    files=source_manifest(root)
    imported=[];valid=True
    for name,module in list(sys.modules.items()):
        if not name.startswith('reelix_') or name.startswith('reelix_eval'):continue
        filename=getattr(module,'__file__',None)
        if filename is None:continue  # namespace package
        path=Path(filename).resolve()
        if not path.is_relative_to(root):valid=False;continue
        imported.append((str(path.relative_to(root)),hashlib.sha256(path.read_bytes()).hexdigest()))
    bindings=[]
    for name,fn in [('run_curator_agent',curator_agent.run_curator_agent),
                    ('build_curator_user_prompt',curator_agent.build_curator_user_prompt),
                    ('apply_curator_tiers',curator_tiers.apply_curator_tiers)]:
        if not Path(inspect.getfile(fn)).resolve().is_relative_to(root):valid=False
        bindings.append((name,hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest()))
    actual=hashlib.sha256(curator_agent.CURATOR_PROMPT_S.encode()).hexdigest()
    if curator_agent.CURATOR_PROMPT_S != curator_prompts.CURATOR_PROMPT_S:valid=False
    return RevisionEvidence(request['expected'],manifest_digest(files),tuple(sorted(files.items())),
        tuple(sorted(imported)),actual,valid,os.getpid(),request['execution_id'],request['prompt'],tuple(bindings))


async def main(request):
    request['execution_id']=str(uuid.uuid4())
    before=identity(request)
    if not before.matched or dict(before.files)!=request['files']:
        print(json.dumps({'kind':'result','error':'revision_mismatch'}),flush=True);return
    cases=[]
    for value in request['cases']:
        value['candidates']=[FrozenCandidate(**c) for c in value['candidates']]
        cases.append(EvalCase(**value))
    bridge=ModelBridge();reader=asyncio.create_task(bridge.receive())
    try:
        run=await _replay_local(cases,bridge,request['label'],request['concurrency'])
        after=identity(request)
        if (before.files != after.files or before.loaded_bindings != after.loaded_bindings
                or before.prompt_sha256 != after.prompt_sha256 or not after.matched):
            run.issues.append('source_or_bindings_changed_during_execution')
        print(json.dumps({'kind':'result','run':asdict(run),'revision':asdict(after)}),flush=True)
    finally:
        reader.cancel()
        await asyncio.gather(reader,return_exceptions=True)


if __name__=='__main__':
    try:asyncio.run(main(json.loads(sys.stdin.readline())))
    except Exception as exc:print(json.dumps({'kind':'result','error':type(exc).__name__}),flush=True)
