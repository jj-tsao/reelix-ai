import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from reelix_eval.case import CaseIdentity, InvestigationCase
from reelix_eval.trust import _pointer, evaluate
from test_investigator_trust import fixture


class CaseTests(unittest.TestCase):
    def test_append_only_checkpoints_and_transition_rules(self):
        with TemporaryDirectory() as root:
            identity = CaseIdentity('c', 'investigate', 'frozen', ('q',), 'base', 'policy')
            case = InvestigationCase(identity, Path(root))
            payload = {'text': 'original'}
            case.record('assessment', payload, origin='agent')
            payload['text'] = 'mutated'
            case.transition('investigation', 'start')
            with self.assertRaises(ValueError):
                case.transition('proposal', 'skip')
            first = case.storage / '0001.json'
            self.assertEqual(json.loads(case.history[1].payload_json)['text'], 'original')
            self.assertEqual(InvestigationCase.inspect(first)['stage'], 'created')
            with self.assertRaises(FileExistsError):
                InvestigationCase(identity, Path(root))
            ctx, _, _ = fixture()
            evidence = ctx.evidence.record('runtime', 'other', {}, case_id='other', query_ids=('q',))
            with self.assertRaises(ValueError):
                case.register(evidence)
            with self.assertRaises(ValueError):
                case.register(replace(evidence, case_id='c', query_ids=('foreign',)))

    def test_pointer_indices_and_escapes(self):
        for index in ('-1', '01', '+1', ' 1', '1.0', '-', '١', '3', '~2'):
            with self.subTest(index=index), self.assertRaises((ValueError, IndexError)):
                _pointer([1, 2], '/' + index)
        self.assertEqual(_pointer({'a/b': {'~': [3]}}, '/a~1b/~0/0'), 3)

    def test_incident_scope_not_just_evidence_id(self):
        ctx, assessment, _ = fixture()
        ctx.case_id = 'incident'
        ctx.query_ids = ('q',)
        result = evaluate(assessment, None, 'read_only', ctx)
        self.assertEqual(next(c.status for c in result.evaluation.conditions if c.condition_id == 'facts.corroborated'), 'unknown')
