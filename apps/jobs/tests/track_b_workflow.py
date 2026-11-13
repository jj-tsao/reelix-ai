"""Fixture-only prompt adaptation. No reviewer data or production imports."""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEAD_PATH = REPO / "packages/python/reelix_eval/agent/prompts.py"
INSPECTOR_PATH = REPO / "packages/python/reelix_eval/agent/subagents.py"

FIXTURE_WORKFLOW = '''# Workflow

This is an isolated diagnostic reasoning test over supplied synthetic observations
and a frozen source snapshot, not a stock end-to-end production investigation.
There is no historical baseline, model judge, deployment, replay, or unrestricted
filesystem access. Do not request those capabilities or infer a temporal change.

1. Enumerate the supplied cases with sample_queries (limit at most 3). Read each
   with get_query_detail(served_only=false), including when no aggregate movement
   is available. Sampling is a small census, not a symptom label.
2. Compare request, spec, candidate metadata, fits, tiers and served state. Missing
   fields mean unknown, not healthy. Look for disconfirming examples across cases;
   do not assume that another case supports the same explanation.
3. Use get_source_excerpt for the single advertised frozen source path. This
   replaces Read/Grep. Explain what code would do under stated inputs, separating
   that mechanism from proof that its preconditions occurred in a logged case.
   Raw model responses and execution-branch traces are unavailable here.
4. Attribute supported observations to a pipeline stage where possible. Separate
   directly observed symptoms, source-supported mechanisms, and plausible but
   unconfirmed causes. Calibrate confidence for each; abstain when evidence is
   insufficient. No production occurrence is established by synthetic inputs.
5. Optional: delegate evidence inspection to query-inspector using these same
   tools and all case IDs. Do not repeat data collection unnecessarily. There is
   no metrics-analyst because no historical comparison is possible.
6. Call write_report once your assessment covers every case. Include query IDs,
   numbers, inspected source references, disconfirming examples and limitations.
   A case may have no supported finding, or remain unassessable. Proposals are
   optional and unverified; no edits or fix-verification claims are permitted.

'''
FIXTURE_BOUNDARY = '''# Fixture boundary

Use only the advertised fixture lookups, optional query-inspector delegation and
output-only write_report. The report must distinguish observations, mechanisms,
unconfirmed causes and limits for every case. There are no SQL, run_judge,
Read/Grep, shell, replay or edit tools. Do not invent substitute evidence.
'''
INSPECTOR_METHOD = '''You inspect the supplied synthetic recommendation cases and frozen source only.
This is a diagnostic reasoning test, not a production investigation.

Method:
1. Use sample_queries(limit<=3) or the supplied IDs. Read each requested case via
   get_query_detail(served_only=false). Filter membership is not a symptom.
2. Use get_source_excerpt for the advertised frozen code path instead of Read or
   Grep. No historical comparison, model judge, replay or production access exists.
3. Compare observations with what the source would do under specified inputs.
   Distinguish observed symptoms, code-supported mechanisms and unconfirmed causes.
   Raw model responses/branch traces are unavailable. Say what is missing and
   abstain from unsupported attribution; no production incidence is established.
4. Return one concise assessment for each case, with query IDs, fit/tier/served
   evidence, source references, disconfirming examples, confidence and limitations.
   Conclude rather than leaving an interim observation. Do not edit or verify fixes.

'''


def load_originals():
    # Read literal prompt definitions without importing the production agent or
    # configuration modules (which could load clients or credentials).
    tree = ast.parse(LEAD_PATH.read_text())
    lead = next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYSTEM_PROMPT" for t in n.targets))
    tree = ast.parse(INSPECTOR_PATH.read_text())
    call = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "QUERY_INSPECTOR" for t in n.targets))
    inspector = next(ast.literal_eval(k.value) for k in call.keywords if k.arg == "prompt")
    return lead, inspector


def adapted_prompts():
    lead, inspector = load_originals()
    intro = "You investigate supplied Reelix recommendation evidence using fixture tools.\n"
    # Domain description, Standards and Known blind spots stay byte-for-byte.
    domain = lead.split("# What you are looking at", 1)[1].split("# Workflow", 1)[0]
    standards = lead.split("# Standards", 1)[1].split("# Editing", 1)[0]
    adapted_lead = intro + "\n# What you are looking at" + domain + FIXTURE_WORKFLOW + "# Standards" + standards + FIXTURE_BOUNDARY
    adapted_inspector = INSPECTOR_METHOD + "Rules:" + inspector.split("Rules:", 1)[1]
    return adapted_lead, adapted_inspector
