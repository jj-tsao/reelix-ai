import unittest
from track_b_workflow import adapted_prompts, load_originals


class FixtureWorkflowTests(unittest.TestCase):
    def test_lead_diagnostic_standards_and_domain_are_preserved(self):
        original, _ = load_originals()
        adapted, _ = adapted_prompts()
        self.assertEqual(original.split('# Standards', 1)[1].split('# Editing', 1)[0],
                         adapted.split('# Standards', 1)[1].split('# Fixture boundary', 1)[0])
        self.assertEqual(original.split('# What you are looking at', 1)[1].split('# Workflow', 1)[0],
                         adapted.split('# What you are looking at', 1)[1].split('# Workflow', 1)[0])

    def test_inspector_rules_and_disconfirming_standard_are_preserved(self):
        _, original = load_originals()
        _, adapted = adapted_prompts()
        self.assertEqual(original.split('Rules:', 1)[1], adapted.split('Rules:', 1)[1])
        self.assertIn('disconfirming', adapted)

    def test_workflow_states_scope_and_does_not_leak_case_answers(self):
        lead, inspector = adapted_prompts()
        for text in (lead, inspector):
            self.assertIn('synthetic', text)
            self.assertIn('get_source_excerpt', text)
            self.assertIn('unconfirmed causes', text)
            for value in ('fixture-e791', 'fixture-c284', 'fixture-b615',
                          '910000002', 'omitted_evaluation_ids', 'oracle.json'):
                self.assertNotIn(value, text)
        self.assertNotIn('4. **Corroborate.**', lead)
        self.assertNotIn('7. **Verify**', lead)


if __name__ == '__main__':
    unittest.main()
