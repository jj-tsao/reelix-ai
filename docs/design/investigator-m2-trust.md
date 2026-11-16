# Investigator M2: Independent Operational Trust Framework

M2 adds a host evaluator to the existing Investigator, without patch execution,
a service, database, policy engine or another reasoning agent. Investigator
confidence and prose are advisory. Host observation identity, explicit predicates,
versioned Python policy and bound human review determine progression.

Implementation: `packages/python/reelix_eval/trust.py`; integration:
`reelix_eval/agent/tools.py`, `prompts.py`, `run.py`, and `report.py`.
The pre-existing M1/M1.5 design document is retained as historical context.

## Contracts and authority

`InvestigationAssessment` supplements Finding, rather than replacing it. It binds
to a validated Finding's digest and separates exact observed fields, proposed
source mechanism, runtime causal hypothesis/preconditions, alternatives,
disconfirming references, gaps, contradictions and unsupported assumptions.
The ID is agent-chosen; the host registers its content binding within the run.
Registration establishes identity, never truth. Changed finding content needs a
new ID; changed assessment/proposal content requires evaluation again.

`RemediationProposal` describes a permitted curator code/prompt change, base and
candidate revision identities, patch text/reference, effect, scope, risks,
preconditions, reversibility and a structured verification plan. It is data.
No patch parser or executor is provided. Candidate revision/patch consistency
remains a review obligation; a declared candidate digest is not loaded-source
attestation. The existing fresh-process replay supplies that attestation later.

`TrustEvaluation` contains typed condition results with stable IDs, one of
`satisfied`, `unsatisfied`, `unknown`, `not_applicable`, evidence refs, rationale,
next action and evaluation provenance. It binds assessment/proposal digests,
policy version/revision, evidence snapshot, trusted context/reviews and next step.
Inputs are frozen strict Pydantic models with unknown fields rejected. Host
outputs are frozen dataclasses and are never deserialized from agent arguments.

`PolicyDecision` has these meanings:

| Outcome | Meaning |
|---|---|
| `request_evidence` | Required support is absent, contradicted or unknown; follow the condition-specific next steps. Authorized read-only work can continue. |
| `deny` | Production execution, a prohibited target/action, or unauthorized evidence access. More confidence cannot cure this. |
| `require_approval` | A grounded proposal is ready for human review, or sandbox prerequisites hold but bound approval is missing. No execution permission. |
| `sandbox_candidate` | The exact proposal meets this policy's requirements for future bounded sandbox review. No execution permission or reusable authorization token. |

`read_only_permitted` records host evidence-access policy separately from action
readiness. Read-only assessment returns guidance via `request_evidence`; no hard
action conditions are required to continue authorized observation. Every decision
has `execution_authorized=False`. Production execution is prohibited even if a
custom host target allowlist includes it.

## Conditions and risk sensitivity

The explicit evaluator checks:

- Evidence existence/provenance; representation of facts versus hypotheses;
  exact observed runtime values; alternative/disconfirming coverage; explicit
  gaps; source mechanism; runtime causal preconditions and causal adequacy.
- Finding identity/content binding; exact action/target allowlist; current base
  revision; direct action preconditions; semantic target/patch relevance;
  bounded risk/reversibility; separate human approval.
- Frozen baseline/candidate cases and revisions; two unchanged controls; at least
  twenty paired cases; a designated measurable improvement axis; all five M1.5
  regression axes; failure, abort and inconclusive handling.

Read-only assessment may retain unknowns. Proposal review requires observed
symptoms, source-grounded mechanism and action relevance (bound human judgments),
identity/scope/revision checks and the verification strategy. Sandbox eligibility
additionally requires causal preconditions/adequacy, alternative and gap review,
action preconditions, bounded risk and policy-specified approval. Unknown and
not-applicable results never satisfy a required action condition. No universal
confidence threshold is used. Approval does not override missing evidence.

JSON pointers and exact JSON values deterministically corroborate recorded fields.
They do **not** validate descriptions, predicate relevance, mechanism sufficiency
or causality. Source presence and quoted text do **not** establish those claims.
These semantic conditions remain unknown until a human review of the exact bound
inputs is installed by host code. No LLM opinion can satisfy them. The plan schema
checks representation; risk review covers whether its scope and failure/abort
rules are adequate. Review is contextual judgment, not causal proof.

## Host evidence and feedback loop

The existing read tools attach `_trust_evidence` identity/provenance metadata to
successful results and record immutable observations in ToolContext. Missing
reads do not create evidence. Query runtime evidence excludes Qdrant-backfilled
metadata and explanations. Judge outputs are `judge_opinion`, and cannot satisfy
runtime predicates. `read_trust_source` reads only policy-permitted curator files
and records source with the current manifest revision. Source existence is not
runtime evidence. Evidence payloads remain inspectable through the host resolver;
read results avoid duplicating the full payload in identity metadata.

The Investigator uses `trust_contracts` to obtain JSON schemas and the canonical
Finding digest, then submits `assess_trust`. The tool accepts only the Finding,
assessment, optional proposal and requested next step. It accepts no evidence
records, statuses, reviews, policy versions, approvals or receipts. Its output
contains independent conditions, specific next evidence steps and resolved
identity/provenance. Follow-up observations and revised assessments are retained
in session evaluation history. The prompt directs evidence gathering and revision,
explicit provisional reporting when access is exhausted, and stopping when only
human judgment remains.

Reports with proposed fixes require a proposal-stage submission. They may still
publish unresolved proposals, accompanied by the host's current decision and
condition results. This permits useful provisional reporting without presenting
it as action clearance. Publication recomputes against the current source,
evidence and policy, so it cannot reuse stale eligibility. Findings and receipts
retain schema v2 semantics; `trust_decisions` is an additive host-generated field
in JSON and Markdown. Clean reports remain valid. The standalone report writer
remains usable by host callers; the agent-facing tool enforces assessment entry.

`HumanReview` has no agent-facing ingestion tool. A trusted embedding host may
install review records with reviewer identity, rationale and resolved evidence
refs. Each review binds exact assessment/proposal, policy, finding registry,
revision, evidence snapshot and access policy. New evidence, changed source,
changed proposal or policy invalidates the review. This is a process trust
boundary, not a cryptographic identity or authentication service. Default CLI
runs cannot self-supply reviews and therefore cannot reach sandbox eligibility.

## Verification and execution boundaries

`verify_outcome` resolves an existing host M1.5 receipt by ID, binds frozen cases,
evalset, baseline and candidate loaded revisions to the proposal plan, and checks
the plan's minimum cases, independent controls, designated improvement axis and
regression guards. Outcomes distinguish not attempted, failed, inconclusive,
criteria not satisfied and improved. Reports attach this plan-bound result under
`proposal_verification` separately from action readiness and M1.5 receipt status.
This does not attest diagnosis correctness.
Abort criteria are plan/review obligations; no execution or abort controller is
implemented. A failed/rejected candidate stays a proposal.

M2 disables Edit, Write and Bash at both SDK configuration and the host callback,
including legacy `--apply`. The flag retains its existing explicit evaluation
persistence permission only; it cannot enable edits. Replay can inspect already
prepared revisions under the existing M1.5 contracts. No production changes,
deployment, rollback, patch execution or new autonomous privileges are included.

## Validation and remaining work

Phases were validated sequentially:

1. M2-A: nine contract/policy tests, followed by the complete existing suite
   (52 tests including M2-A). Deterministic branches, four statuses, forged refs,
   unknown hard conditions, stale inputs and host-only review authority passed.
2. M2-B: five integration tests covering feedback/revision, immutable publication,
   proposal-stage gating, evidence capture, authority injection and SDK/host
   execution denial passed before comparative work began.
3. M2-C offline: four controlled comparison/verification tests cover clean
   controls, unsupported high-confidence proposals, contradictory facts, human
   review/approval, stale proposals, all receipt outcomes, plan identity and
   designated-axis/regression obligations. These exercise actual tool/report
   boundaries with scripted inputs, not a live Investigator's reasoning.

The final maintained offline suite passes all 61 tests. Run it with:

```sh
apps/jobs/.venv/bin/python -m unittest discover -s apps/jobs/tests -v
```

A live synthetic comparison runner is ready:

```sh
apps/jobs/.venv/bin/python apps/jobs/tests/run_investigator_trust_live.py \
  --output /tmp/reelix-m2-live --model <available-agent-model>
```

It compares baseline investigation standards against the M2 feedback workflow on
anomaly, missing-evidence and clean scenarios. Both arms have only synthetic
in-process tools, no production store, file/shell tools or patch execution.
The baseline is an ablation, not a historical M1 reproduction. It preserves
reports, observation requests, publication attempts, conditions and costs for
review; each arm/case is exploratory, not a statistically powered evaluation.

The live runner was attempted but stopped at preflight: `claude auth status`
reported `loggedIn=false`. No model requests were issued. **Live M2-C behavioral
validation remains incomplete.** Passing offline tests establishes enforcement
and feedback plumbing; it does not establish better live investigation behavior,
causal calibration, diagnostic accuracy or remediation effectiveness. After an
existing authorized Claude login is available, run the comparison and review
whether guidance changed evidence gathering, provisional reasoning and stopping
behavior. Do not infer those improvements from typed metadata alone.
