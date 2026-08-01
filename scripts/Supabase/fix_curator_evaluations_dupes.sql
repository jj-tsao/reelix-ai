-- =============================================================================
-- Fix: duplicate curator_evaluations rows
-- =============================================================================
-- PROBLEM
--
-- `curator_evaluations` accumulated duplicate rows for the same
-- (query_id, media_id). Two causes, both required:
--
--   1. The unique index declared in agent_tables_schema.sql
--      (idx_curator_evaluations_qid_mid) was never actually created in this
--      database — only the non-unique query_id / media_id / tier indexes exist.
--   2. `/explore/rerun` deliberately reuses the same query_id, and
--      `TelemetryLogger.log_curator_evaluations` POSTed without an
--      `?on_conflict=` parameter, so every chip rerun appended a fresh full set
--      of rows instead of updating the existing ones.
--
-- `rec_results` was never affected because `log_candidates` already posts to
-- `rec_results?on_conflict=endpoint,query_id,media_id`. The `Prefer:
-- resolution=merge-duplicates` header was already being sent on every request —
-- only the conflict target was missing.
--
-- IMPACT
--
-- 21 of 513 queries carried 2-9 runs each (372 rows, 5.7 percent of the table). Any
-- AVG/COUNT over curator_evaluations double-counted those queries, which feeds
-- the curator metrics in daily_metrics.
--
-- FIX
--
-- Delete superseded runs, add the missing unique index, and (in application
-- code) start sending the conflict target. A run writes all of its rows in a
-- single INSERT, so every row of one run shares an identical created_at —
-- "keep the rows matching MAX(created_at) for that query_id" therefore keeps
-- exactly one coherent slate rather than splicing runs together.
--
-- DESTRUCTIVE: step 1 deletes historical rows for superseded runs. Verified
-- beforehand: 372 rows to delete, 6156 to remain, 0 duplicates within any
-- single run (so step 3 can build).
--
-- Idempotent: re-running is a no-op once applied.
-- =============================================================================

begin;

-- 1. Drop every run except the most recent one, per query_id.
delete from curator_evaluations ce
where ce.created_at < (
    select max(created_at) from curator_evaluations x
    where x.query_id = ce.query_id
);

-- 2. Safety net. Should delete nothing (verified 0), but if a single run ever
--    wrote a candidate twice, the unique index below would fail to build.
delete from curator_evaluations a
using curator_evaluations b
where a.query_id = b.query_id
  and a.media_id = b.media_id
  and a.id > b.id;

-- 3. The index that was supposed to exist all along. With this in place,
--    PostgREST's `?on_conflict=query_id,media_id` can resolve, turning a rerun
--    into an UPDATE instead of a duplicate INSERT.
create unique index if not exists idx_curator_evaluations_qid_mid
  on curator_evaluations (query_id, media_id);

commit;

-- =============================================================================
-- Application-side change that must ship with this (packages/python/reelix_logging)
-- =============================================================================
--
--   log_curator_evaluations:
--     - POST to `curator_evaluations?on_conflict=query_id,media_id`
--     - include an explicit `created_at` on every row
--
-- The explicit created_at matters: ON CONFLICT DO UPDATE only writes the columns
-- present in the payload, so without it a rerun would keep the original row's
-- timestamp. Readers that isolate "the latest run" by MAX(created_at) would then
-- mix runs — and a candidate dropped by the rerun would keep a stale
-- is_served = true. Stamping every row of a run with one fresh timestamp keeps
-- the latest-run cohort exact and lets superseded candidates age out naturally.
--
-- Verify after deploying:
--   select count(*) from (
--     select query_id, media_id from curator_evaluations
--     group by 1,2 having count(*) > 1) t;   -- expect 0, permanently
-- =============================================================================