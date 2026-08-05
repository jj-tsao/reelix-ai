-- =============================================================================
-- Orchestrator replay: log the agent's INPUT, not just its output
-- =============================================================================
-- Every column on agent_decisions today records what the orchestrator produced
-- (spec_json, mode, opening_summary) or how it performed (tokens, latency).
-- Nothing records what it was given, so a decision cannot be reproduced.
--
-- That matters because the orchestrator's input is not just `query_text`. When
-- session memory is present, AgentState.from_agent_input injects an extra system
-- message built from it — the prior turn's spec, the slot_map of titles that
-- were shown, and recent feedback. A refine turn like "more like #3 but funnier"
-- is unresolvable without it: #3 only exists in slot_map.
--
-- Session memory lives in Redis and is evicted, so it cannot be backfilled. Of
-- 541 logged RECS decisions only 12 come from single-query sessions (where
-- memory was empty) and are therefore replayable today. This column fixes that
-- going forward; existing rows stay unreplayable for refine turns.
--
-- Stored raw rather than pre-rendered so a replay can re-run the live
-- `build_session_memory_message`, making changes to memory formatting testable —
-- the same principle that lets curator replay pick up prompt edits.
--
-- Idempotent: safe to re-run.
-- =============================================================================

alter table agent_decisions
  add column if not exists session_memory jsonb;

comment on column agent_decisions.session_memory is
  'Orchestrator input for this turn (prior spec, slot_map, recent feedback). Required to replay a refine-turn decision; NULL on first turns and on rows written before 2026-08-05.';

-- Replayable-population check: first turns are those with no session memory.
create index if not exists idx_agent_decisions_first_turn
  on agent_decisions (created_at desc)
  where session_memory is null;

-- =============================================================================
-- Verify after deploying
-- =============================================================================
--
--   -- Should climb from 0 as new traffic lands:
--   select count(*) filter (where session_memory is not null) as with_memory,
--          count(*)                                          as total
--   from agent_decisions
--   where created_at >= '2026-08-05';
--
--   -- What a replay would reconstruct for one refine turn:
--   select query_id,
--          session_memory -> 'summary' ->> 'turn_kind'   as turn_kind,
--          jsonb_array_length(coalesce(session_memory -> 'seen_media_ids', '[]')) as seen,
--          session_memory ? 'slot_map'                   as has_slot_map
--   from agent_decisions
--   where session_memory is not null
--   order by created_at desc limit 10;
-- =============================================================================
