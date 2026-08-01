-- =============================================================================
-- Eval Agent Schema
-- =============================================================================
-- Backing tables for the offline eval harness (packages/python/reelix_eval).
--
-- Two changes:
--   1. judge_evaluations gains the signals the redesigned judge produces
--      (spec_violation, explanation_grounded) plus the deterministic
--      spec_violation_code check and the effort level the judge ran at.
--   2. judge_query_evaluations is new: per-QUERY judgements (spec_fidelity,
--      list_coherence) that have no per-candidate meaning.
--
-- Token accounting moves to judge_query_evaluations. The old code stamped the
-- same per-query totals onto every candidate row, so any SUM(input_tokens) over
-- judge_evaluations over-counted by the number of candidates. Per-item rows now
-- write NULL and the per-query row is the single source of truth.
--
-- Idempotent: safe to re-run. Apply in the Supabase SQL editor, or via
-- `python -m jobs.eval_judge --apply-schema` once that flag exists.
--
-- Usage after applying:
--   python -m jobs.eval_judge --date 2026-07-31
-- =============================================================================

-- -----------------------------------------------------------------------------
-- judge_evaluations: new per-candidate signals
-- -----------------------------------------------------------------------------
-- spec_violation       — judge's answer: does this title break a HARD spec
--                        constraint (excluded genre, year_range, provider)?
-- spec_violation_code  — the same question computed deterministically from
--                        spec_json + the Qdrant payload. Disagreement between
--                        the two is a free, continuous calibration signal on the
--                        judge itself, independent of any change to the system
--                        under test.
-- explanation_grounded — hallucination check: does the "why" text assert
--                        anything untrue about the title?
-- judge_effort         — Claude effort level ('low'|'medium'|'high'|...). Scores
--                        are not comparable across effort levels, so runs must
--                        record which one produced them.
alter table judge_evaluations
  add column if not exists spec_violation       boolean,
  add column if not exists spec_violation_code  boolean,
  add column if not exists explanation_grounded boolean,
  add column if not exists judge_effort         text;

comment on column judge_evaluations.spec_violation_code is
  'Deterministic recomputation of spec_violation; disagreement with the judge''s answer measures judge drift.';
comment on column judge_evaluations.input_tokens is
  'Deprecated — always NULL. Token counts live on judge_query_evaluations to avoid per-candidate duplication.';
comment on column judge_evaluations.output_tokens is
  'Deprecated — always NULL. See judge_query_evaluations.';

create index if not exists idx_judge_eval_spec_violation
  on judge_evaluations (spec_violation)
  where spec_violation is true;

-- -----------------------------------------------------------------------------
-- judge_query_evaluations: per-query judgements
-- -----------------------------------------------------------------------------
-- One row per (eval_run_id, query_id).
--
-- spec_fidelity   — did the orchestrator's spec_json faithfully capture the
--                   user's request? This is the orchestrator's FIRST quality
--                   signal; nothing else measures it.
-- list_coherence  — does the served set read as one coherent, non-redundant
--                   answer? Catches near-duplicate slates, a real recommender
--                   failure mode that per-item scoring is blind to.
-- status          — 'ok' | 'refused' | 'error'. A refusal or transport failure
--                   is recorded rather than dropped, so a shrinking sample is
--                   visible instead of silently biasing the averages.
create table if not exists judge_query_evaluations (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),

  -- Identifiers
  eval_run_id     text not null,
  query_id        text not null,

  -- Context (denormalized for self-contained analysis)
  query_text      text,

  -- Per-query judge scores (1-5)
  spec_fidelity   int,
  list_coherence  int,
  reasoning       text,

  -- Outcome
  status          text not null default 'ok',

  -- Metadata. Tokens live HERE only.
  judge_model     text,
  judge_effort    text,
  input_tokens    int,
  output_tokens   int,

  unique (eval_run_id, query_id)
);

create index if not exists idx_judge_query_eval_run
  on judge_query_evaluations (eval_run_id);
create index if not exists idx_judge_query_eval_query
  on judge_query_evaluations (query_id);
create index if not exists idx_judge_query_eval_status
  on judge_query_evaluations (status, created_at desc);

-- RLS: backend-only table (accessed via service_role, not exposed to frontend)
alter table judge_query_evaluations enable row level security;

-- =============================================================================
-- Query patterns
-- =============================================================================
--
-- Judge vs curator agreement, per tier:
--   SELECT je.curator_tier,
--          COUNT(*) AS n,
--          AVG(je.relevance) AS avg_relevance,
--          AVG(je.curator_total_fit) AS avg_curator_fit
--   FROM judge_evaluations je
--   WHERE je.eval_run_id = 'xxx'
--   GROUP BY 1 ORDER BY 2 DESC;
--
-- Judge calibration — how often the LLM and the code check disagree:
--   SELECT COUNT(*) FILTER (WHERE spec_violation <> spec_violation_code)::float
--            / NULLIF(COUNT(*), 0) AS disagreement_rate
--   FROM judge_evaluations
--   WHERE eval_run_id = 'xxx'
--     AND spec_violation IS NOT NULL AND spec_violation_code IS NOT NULL;
--
-- Orchestrator quality over time (nothing else measures this):
--   SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
--          AVG(spec_fidelity) AS spec_fidelity,
--          AVG(list_coherence) AS list_coherence
--   FROM judge_query_evaluations
--   WHERE status = 'ok'
--   GROUP BY 1 ORDER BY 1 DESC;
--
-- Judge cost for a run (correct — no per-candidate duplication):
--   SELECT SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok
--   FROM judge_query_evaluations WHERE eval_run_id = 'xxx';
-- =============================================================================