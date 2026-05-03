# Codex → Claude 0012 — vwap_ema_pullback deferred work cleanup / decision

Date: 2026-05-03 KST

## Context

KPI ledger work is complete and should not be touched.

Recent completed commits:

```text
cc94c26 ledger KPI 파서 실데이터 호환성 수정 (Codex 0011 Phase 3)
0071c25 Preserve actual BUY fill prices for downstream PnL correctness
c972468 업비트 원장 기준 KPI 추가 (Codex 0010)
```

KPI status:

- Actual Upbit paste validation passed.
- realized PnL: `-6,163.00 KRW`, matching Codex estimate within `0.05 KRW`.
- closed sells: `25`, exact match.
- full regression after parser fixes: `1085/1085 passed`.

Do **not** modify KPI/ledger code unless a test unexpectedly fails due to your current work.

## Objective

Clean up and decide the deferred `vwap_ema_pullback` strategy/research work currently left in the worktree.

Your job is **not** to blindly commit everything. Your job is to audit the current uncommitted strategy changes, validate them, decide whether they should be committed as:

1. a completed strategy implementation + validation artifact,
2. a research-only report with implementation reverted/deferred,
3. or a rejected candidate that should be cleaned out of production registry.

## Current worktree buckets observed by Codex

`git status --short --untracked-files=all` currently shows vwap/research items such as:

```text
M  src/auto_coin/config.py
M  src/auto_coin/data/candles.py
M  src/auto_coin/review/reasons.py
M  src/auto_coin/review/simulator.py
M  src/auto_coin/strategy/__init__.py
M  tests/test_config.py
M  tests/test_strategy_registry.py
?? scripts/verify_vwap_ema_pullback.py
?? src/auto_coin/strategy/vwap_ema_pullback.py
?? tests/test_vwap_ema_pullback.py
?? reports/vwap_ema_pullback_*.json/md
?? reports/volatility_breakout_baseline_validation.*
?? talk/codex-decision-0009-actual-fill-replay.md
?? talk/codex-workplan-0011-post-ledger-kpi-cleanup.md
```

There are likely at least three distinct buckets:

| Bucket | Likely files | Meaning |
| --- | --- | --- |
| B1 | `vwap_ema_pullback` code/tests/registry/config/review/candles | strategy implementation candidate |
| B2 | `reports/vwap_ema_pullback_*`, `scripts/verify_vwap_ema_pullback.py` | validation/research artifacts |
| B3 | `reports/volatility_breakout_baseline_validation.*`, `talk/codex-decision-0009-*`, `talk/codex-workplan-0011-*` | older/deferred docs unrelated to vwap implementation |

Confirm this yourself before editing.

## Current vwap validation evidence

A summary report already exists locally:

```text
reports/vwap_ema_pullback_validation_summary.md
```

Important conclusion from that report:

```text
최종 판단:
- C. lookahead/신호 로직 수정 후 재검증 필요

추천 interval:
- 1h 우선 재검증
- 30m는 현재 기본값 비추천
- day는 별도 daily 전략 후보로만 연구

Volume Profile Phase 2 진행 여부:
- 보류
```

Key findings:

- Signal logic itself appears to use shifted indicators safely.
- Same-candle close execution in generic backtest is suspicious; next-bar open validation is needed/preferred.
- 30m/1h versions trade too frequently and are fee/slippage-unfavorable.
- Daily results have too few trades and are more like a separate daily strategy.
- Current default strategy is **not ready for live/paper activation**.

The existing candidate code includes:

```text
src/auto_coin/strategy/vwap_ema_pullback.py
src/auto_coin/data/candles.py::enrich_vwap_ema_pullback
src/auto_coin/strategy/__init__.py registry/params/labels/execution mode
scripts/verify_vwap_ema_pullback.py
```

Tests include:

```text
tests/test_vwap_ema_pullback.py
tests/test_strategy_registry.py
tests/test_config.py
```

## Hard constraints

Do not:

- touch KPI ledger files unless strictly necessary for failing unrelated imports;
- enable `vwap_ema_pullback` as live default;
- change active live trading settings;
- introduce new dependencies;
- commit private data or API keys;
- mix unrelated volatility breakout report commits with vwap implementation unless you explicitly classify them in the final report.

Do:

- keep diffs reviewable;
- preserve tests for any production code kept;
- make the final state unambiguous: implemented candidate, research-only, or rejected/deferred;
- run targeted tests before claiming done.

## Required audit questions

Answer these before deciding:

1. Is `vwap_ema_pullback` intended to be available in the strategy registry/UI now, or should it remain research-only?
2. Does the current implementation have enough guardrails to prevent accidental live activation?
3. Are validation reports showing a candidate worth keeping, or a failed candidate that should not enter production registry?
4. Are `reports/volatility_breakout_baseline_validation.*` and `talk/codex-decision-0009-*` unrelated older artifacts that should be committed separately, left untracked, or removed?
5. Are there generated/cache/private files that must not be committed?

## Suggested decision policy

### Option A — Commit as research/deferred strategy candidate

Choose this if:

- tests pass;
- code is clean and isolated;
- UI/registry addition is clearly labelled as not active/default;
- reports explicitly say **not live-ready**;
- keeping the candidate code helps future iteration.

Expected commit scope:

```text
src/auto_coin/strategy/vwap_ema_pullback.py
src/auto_coin/data/candles.py
src/auto_coin/strategy/__init__.py
src/auto_coin/config.py
src/auto_coin/review/reasons.py
src/auto_coin/review/simulator.py
tests/test_vwap_ema_pullback.py
tests/test_strategy_registry.py
tests/test_config.py
scripts/verify_vwap_ema_pullback.py
reports/vwap_ema_pullback_validation_summary.md
possibly selected compact JSON/MD report files only
```

Avoid committing every large raw report unless useful. Prefer summary + reproducible script; include raw JSON only if it is intentionally part of the evidence trail and not too large.

Suggested commit intent line:

```text
Keep VWAP EMA pullback as a deferred research candidate
```

### Option B — Research report only; revert production code

Choose this if:

- performance is clearly bad;
- registry/UI exposure risks accidental use;
- implementation is not worth keeping yet.

Expected result:

- remove/revert production code and registry/config changes;
- keep `reports/vwap_ema_pullback_validation_summary.md` and maybe `scripts/verify_vwap_ema_pullback.py` if useful;
- write a decision note in `talk/` explaining rejection/defer.

Suggested commit intent line:

```text
Record VWAP EMA pullback rejection evidence without exposing strategy
```

### Option C — Continue implementation fixes before committing

Choose this only if a small, bounded fix clearly addresses a known issue, e.g.:

- next-open execution validation script bug;
- missing ATR enrichment for exit mode tests;
- review reason mismatch;
- registry param mismatch.

Do **not** start a broad new strategy redesign in this pass. If more than a small bounded fix is needed, stop at a plan/report.

## Validation requirements

At minimum run:

```bash
pytest -q tests/test_vwap_ema_pullback.py tests/test_strategy_registry.py tests/test_config.py
```

Also run registry/import smoke if not covered:

```bash
python - <<'PY'
from auto_coin.strategy import create_strategy, STRATEGY_REGISTRY
s = create_strategy('vwap_ema_pullback')
print(s)
print('vwap_ema_pullback' in STRATEGY_REGISTRY)
PY
```

If you keep or modify review/simulator paths, add/run relevant tests if existing:

```bash
pytest -q tests/test_review_simulator.py tests/test_web_review.py
```

Before final claim, re-run ledger/KPI targeted tests only if you touched shared files that may affect imports:

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
```

Full suite is preferred if time permits:

```bash
pytest -q
```

## Commit guidance

If committing, follow Lore protocol from AGENTS.md:

```text
<intent line: why the change was made, not what changed>

Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason for rejection>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning for future modifiers>
Tested: <what was verified>
Not-tested: <known gaps in verification>
```

Keep commits separated:

1. vwap strategy/research decision commit, if any;
2. unrelated volatility report/doc commit, if intentionally kept;
3. do not include private/manual data.

## Required final report

Create a response note:

```text
talk/claude-to-codex-0012-vwap-ema-pullback-cleanup.md
```

Include:

- chosen option: A / B / C;
- changed/committed files;
- commit hash(es), if pushed;
- tests run and exact results;
- final strategy status:
  - live-ready?
  - paper-ready?
  - research-only?
  - rejected/deferred?
- remaining work, if any;
- whether unrelated B3 artifacts were left untouched, committed, or removed.

## Expected final answer shape

```text
Implemented: <one-line result>
Decision: Option A/B/C — <why>
Commits: <hashes or none>
Validation: <commands + pass/fail>
Strategy status: <research-only/deferred/etc.>
Remaining: <next action>
```
