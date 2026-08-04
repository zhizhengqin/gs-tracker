# /review — codex/multi-inst-a-share-homepage (2026-08-04)

Base: main (602e0fb) | Diff: 30 files, +1653/-87 | Tests: 447 passed

## Critical pass
- SQL safety: OK — all queries parameterized; migrations use ALTER ADD COLUMN + IF NOT EXISTS guards, no PK rebuild.
- LLM trust boundary: OK — AI triage output only filters indices; DeepSeek config via llm_models table, no hardcoded keys.
- Conditional side effects: OK — pipeline writes go through save_signals_incremental UPSERT (fingerprint conflict).
- New external sources (qfii/northbound/jpm_research): httpx + retries/backoff, no eval/exec, honest about HKEX data limits.

## Findings
- [P2][fixed] web.py: dead `_purge_non_gs_news_signals()` left commented-out in lifespan; function + test deleted (single-institution era cleanup, dangerous if ever re-enabled under multi-institution).
- [P3][accepted] Cross-institution dedup is heuristic (keyword-affinity count); misattribution possible on 50/50 articles. Acceptable: loser article is still covered by its own institution's future signals.
- [P3][accepted] `institution` API params not validated against institutions table; unknown value returns empty list, no injection risk (parameterized).

## Verdict: SHIP-READY after fix. Zero GS regression covered by 447-test suite.
