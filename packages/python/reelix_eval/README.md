# reelix_eval

Offline evaluation harness for the Reelix recommendation agent. Nothing here is
imported by the serving path — the API and MCP server never depend on it.

| Module | Purpose |
|---|---|
| `db` | Engine factory (`DATABASE_URL`). Mirrors the jobs app's rather than importing an app. |
| `store` | Read-only queries over the logging tables: windows, metrics, window comparison, symptom-filtered sampling, full per-query assembly. |
| `judge` | LLM-as-judge on Claude via the Anthropic SDK. Two calls per query so curator and explanation quality stay separable. Synchronous (`judge_queries`) or Batch API (`judge_queries_batch`, half price). |
| `replay` | Freeze real queries into an eval set, then re-run the curator stage against the working tree. |
| `report` | `report.md` + `findings.json` writer. |

## Usage

```python
from reelix_eval.db import get_engine
from reelix_eval import store

engine = get_engine()
store.list_windows(engine, days=30)                  # which days have usable data
store.sample_queries(engine, start, end, 20, "low_fit")
store.get_query_detail(engine, query_id)             # + Qdrant metadata backfill
```

## Judge cost

Measured per query (~5.5K input / ~1.1K output tokens):

| Path | $/query | Notes |
|---|---:|---|
| Sonnet 5 + Batch API | **$0.0195** | Default for `jobs.eval_judge`. ~2 min end-to-end. |
| Sonnet 5, synchronous | $0.0380 | Used by the agent's `run_judge` tool, which can't wait. |
| Opus 5, synchronous | $0.0654 | Reference judge for periodic recalibration. |

Sonnet 5 was chosen by A/B against Opus 5 (r=0.81 on relevance, 95% of items
within one point, identical `spec_violation` calls). Haiku 4.5 was rejected —
novelty correlation drops to 0.52 and it grades systematically easier. The full
table is in `judge/runner.py` next to `DEFAULT_JUDGE_MODEL`.

**Prompt caching does not apply here.** Both system prompts are below the
cacheable minimum (rec=920, expl=400 tokens; Sonnet 5 needs 1024, Opus 5 512), so
`cache_control` is a verified no-op. The rest of each request is the per-query
candidate list, which can't be shared.

## Notes

- **Metadata backfill.** The logging tables never stored genres/keywords/overview,
  so `get_query_detail` refetches them from Qdrant by `media_id`. Without it the
  judge sees only a title.
- **`discovery/for-you` has no `query_text`** (it's a personalized feed, not a
  text query). Sampling filters exclude those rows so they never resolve to
  nothing — except `errored`, which deliberately includes requests that died
  before intake logging.
- **Replay is not deterministic.** The curator runs at `temperature=0.1`. An
  unchanged replay scores ~0.80 served overlap against a fixed baseline, with
  tier counts wandering ~±0.25. See `replay/curator.py` for the measured floor.
- **Judge auth** uses `REELIX_JUDGE_ANTHROPIC_KEY`, passed explicitly. Do not
  export `ANTHROPIC_API_KEY` — it shadows the Claude Code login.