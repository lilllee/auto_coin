# Current Collaboration State

Last updated: 2026-04-23 KST

## Current strategic conclusion

현재 만들어진 기존 전략은 실사용하지 않는다.

- `regime_reclaim_30m`: HOLD, 연구용 보관.
- `regime_pullback_continuation_30m`: HOLD, 실패 기준선으로 보관.
- live / paper / UI / KPI / walk-forward: 아직 금지.

## Latest validated signal

Claude가 구현한 `regime_relative_strength_event_study` 결과와 Codex 재검토 결과:

- Best condition set: `regime_rs_trend_volume_breakout`
- Conservative daily regime no-lookahead patch 적용 완료
- Commit: `0b6e039` pushed to `origin/main`
- Verdict: PASS
- After patch:
  - alt_event_count: 298
  - ETH events: 151
  - XRP events: 147
  - h16 avg excess: approximately +0.755%
  - h24 avg excess: approximately +0.944%
  - h16 median excess: approximately +0.252%
  - h24 median excess: approximately +0.241%
  - 9 gates: all pass

## Next approved implementation lane

Implement `regime_relative_breakout_30m` as Stage 2 only.

Allowed:

- strategy implementation
- candle enrichment / registry metadata needed for the strategy
- tests
- Stage 2 script/report for BTC/ETH/XRP x 1y/2y with fee/slippage

Forbidden:

- walk-forward
- paper/live trading
- settings UI
- KPI UI
- web UI
- reversion SMA exit
