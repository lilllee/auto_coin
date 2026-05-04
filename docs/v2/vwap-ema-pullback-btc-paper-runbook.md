# vwap_ema_pullback BTC-only paper/shadow runbook

Date: 2026-05-04
Status: **paper 운영 준비 단계** — 본 문서는 절차 / 설정 / verdict 게이트만 정의. 실제 paper 활성화는 운영자 명시적 액션 필요.

Source PRD: [`.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md`](../..//.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md) · Test spec: [`.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md`](../..//.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md)

Prior validation:
- P2.5 sweep: `reports/vwap_ema_pullback_p25_validation.{json,md}` · commit `5d77fae`
- Per-ticker recommendation: BTC `recommend_btc_only_paper`, ETH `hold`.

전략 자체는 `EXPERIMENTAL_STRATEGIES` 마킹 그대로. live 활성화 절대 금지. 본 PR 은 운영 절차 + 검증 테스트만 추가하며 strategy / enricher / runner / KPI / ledger 코드는 0줄도 변경하지 않는다.

---

## 1. 설정값 (operating config)

다음은 `vol_w30` (PRD §3.1 권장 시작 default) 기준. `.env` 또는 V2 UI Settings 페이지에 그대로 입력한다.

### 1.1 환경 변수 매트릭스

| key | value | 근거 |
|---|---|---|
| `MODE` | `paper` | **가장 중요한 안전장치** — live 절대 금지. |
| `LIVE_TRADING` | `false` | 보조 가드. paper 모드 자동이지만 명시. |
| `KILL_SWITCH` | `false` | 시작 시 진입 허용. 종료 시 운영자가 `true` 변경. |
| `STRATEGY_NAME` | `vwap_ema_pullback` | EXPERIMENTAL 게이트 통과 — UI 에서 `include_experimental=True` 토글 후 선택. |
| `TICKERS` | `KRW-BTC` | **단 1개만**. 다른 ticker 절대 추가 금지. |
| `MAX_CONCURRENT_POSITIONS` | `1` | 단일 BTC slot. |
| `MAX_POSITION_RATIO` | `0.50` | paper 자본의 50% 사용 (단일 slot 이라 분산 필요 없음). |
| `COOLDOWN_MINUTES` | `120` | strategy `cooldown_bars=2` × 1h interval = 2h = 120분 등가. |
| `DAILY_LOSS_LIMIT` | `-0.03` (= -3%) | default 그대로. (소수 표기 — `-0.03`, `-3.0` 아님.) |
| `CHECK_INTERVAL_SECONDS` | `3600` | 1h interval 매칭. (V1 floor 30s — 안전.) |
| `PAPER_INITIAL_KRW` | `1000000` | 100만원 가상 자본. |
| `ACTIVE_STRATEGY_GROUP` | `vwap_ema_pullback_btc_paper` | KPI dashboard 필터링 핵심 태그. |
| `STRATEGY_PARAMS_JSON` | (1.2 의 `vol_w30` JSON) | candidate 별로 다름. |

### 1.2 STRATEGY_PARAMS_JSON 후보 — 3 종

#### `vol_w30` (paper 시작 default · 권장)

```json
{
  "exit_mode": "atr_buffer_exit",
  "exit_atr_multiplier": 0.3,
  "min_ema_slope_ratio": 0.002,
  "max_vwap_cross_count": 2,
  "ema_touch_tolerance": 0.003,
  "volume_filter_mode": "ge_1_2",
  "volume_mean_window": 30,
  "htf_trend_filter_mode": "off",
  "rsi_filter_mode": "off",
  "daily_regime_filter_mode": "off"
}
```

P2.5 결과: BTC 6m PF 1.34 / ret +5.77% · BTC 1y PF 1.05 / ret +1.47% · ETH 1y +4.16pp anchor diff (cross-asset signal).

#### `vol_1_4` (alternative — 더 strict 한 대안)

```json
{
  "exit_mode": "atr_buffer_exit",
  "exit_atr_multiplier": 0.3,
  "min_ema_slope_ratio": 0.002,
  "max_vwap_cross_count": 2,
  "ema_touch_tolerance": 0.003,
  "volume_filter_mode": "ge_1_4",
  "volume_mean_window": 20,
  "htf_trend_filter_mode": "off",
  "rsi_filter_mode": "off",
  "daily_regime_filter_mode": "off"
}
```

P2.5 결과: BTC 6m PF **1.40** ⭐ / ret +5.92% · BTC 1y PF 1.09 / ret +2.81% (BTC-pure 측면 가장 강함). 단 ETH 1y 개선 미약 (+0.01pp).

#### `anchor` (= P2 C_vol_1_2 — regression fallback)

```json
{
  "exit_mode": "atr_buffer_exit",
  "exit_atr_multiplier": 0.3,
  "min_ema_slope_ratio": 0.002,
  "max_vwap_cross_count": 2,
  "ema_touch_tolerance": 0.003,
  "volume_filter_mode": "ge_1_2",
  "volume_mean_window": 20,
  "htf_trend_filter_mode": "off",
  "rsi_filter_mode": "off",
  "daily_regime_filter_mode": "off"
}
```

P2.5 결과: BTC 6m PF 1.18 / ret +3.25% · BTC 1y PF 1.02 / ret +0.34% (P2 결과 재현). vol_w30 / vol_1_4 둘 다 fail 시 회귀.

### 1.3 .env 예시 (그대로 복사용)

```bash
# vwap_ema_pullback BTC-only paper run
MODE=paper
LIVE_TRADING=false
KILL_SWITCH=false
STRATEGY_NAME=vwap_ema_pullback
TICKERS=KRW-BTC
MAX_CONCURRENT_POSITIONS=1
MAX_POSITION_RATIO=0.50
COOLDOWN_MINUTES=120
CHECK_INTERVAL_SECONDS=3600
DAILY_LOSS_LIMIT=-0.03
PAPER_INITIAL_KRW=1000000
ACTIVE_STRATEGY_GROUP=vwap_ema_pullback_btc_paper
STRATEGY_PARAMS_JSON='{"exit_mode":"atr_buffer_exit","exit_atr_multiplier":0.3,"min_ema_slope_ratio":0.002,"max_vwap_cross_count":2,"ema_touch_tolerance":0.003,"volume_filter_mode":"ge_1_2","volume_mean_window":30,"htf_trend_filter_mode":"off","rsi_filter_mode":"off","daily_regime_filter_mode":"off"}'
```

---

## 2. 시작 전 체크리스트 (pre-flight)

각 항목 직접 확인하고 모두 ✓ 가 되어야 paper 시작.

### 2.1 코드 / 테스트 상태

- [ ] `git status --short` 결과가 expected (paper 시작 전에는 clean 또는 의도된 변경만).
- [ ] `git log --oneline -1` 가 `5d77fae` (P2.5) 이상 — P2.5 까지 적용된 코드.
- [ ] `pytest -q` 1181 PASS (또는 본 PR 의 `test_btc_paper_config.py` 추가 후 1181+).
- [ ] `ruff check src tests scripts` clean.

### 2.2 환경 변수

- [ ] `.env` 또는 web UI Settings 에 §1.1 의 모든 setting 적용.
- [ ] `MODE=paper` 확인 (NOT `live`).
- [ ] `LIVE_TRADING=false` 확인.
- [ ] `TICKERS=KRW-BTC` 확인 — 단 1개. comma 추가 / 다른 ticker 0건.
- [ ] `STRATEGY_NAME=vwap_ema_pullback` 확인.
- [ ] `STRATEGY_PARAMS_JSON` 가 §1.2 의 `vol_w30` JSON (또는 의도된 candidate).
- [ ] `ACTIVE_STRATEGY_GROUP=vwap_ema_pullback_btc_paper` 확인 — KPI 분리 핵심.
- [ ] `KILL_SWITCH=false` 확인 (시작 시).

### 2.3 V2 UI 검증

- [ ] `python -m auto_coin.web --port 8080` 실행.
- [ ] 로그인 후 `/dashboard` 접속.
- [ ] bot status: `paper` 확인 (NOT `live`).
- [ ] strategy: `vwap_ema_pullback` 표시.
- [ ] tickers: `KRW-BTC` 1개만 표시.
- [ ] kill_switch: `OFF` 표시.
- [ ] active_strategy_group: `vwap_ema_pullback_btc_paper` (UI 에 표시 안 되면 `/kpi/data` JSON 응답에서 확인).

### 2.4 알림 / 모니터링

- [ ] Telegram bot token / chat_id 설정 — 모든 BUY/SELL 알림 받는지 "Test Telegram" 으로 확인.
- [ ] 첫 1h 동안 logs 확인 위치 결정 (`logs/auto_coin_*.log` 또는 `journalctl` 등).
- [ ] 4주 후 review 일정 캘린더 등록.

### 2.5 비상 절차 사전 확인

- [ ] `/settings/risk` 에서 kill_switch 토글 위치 숙지.
- [ ] 운영자 본인이 매일 1회 이상 `/dashboard` 확인 가능한 일정.
- [ ] §4 의 stop/kill 게이트 임계값 메모.

위 5 분야 모두 ✓ 면 paper run 시작 가능.

---

## 3. 2주 / 4주 review 절차

### 3.1 매일 체크 (1분)

`/dashboard` 페이지 — 다음만 확인:
- bot 가 살아있는지 (heartbeat 시각).
- Telegram 알림 이상 없음 (BUY/SELL 만 수신, ERROR 알림 0건).
- kill_switch 변경 없음.
- 보유 포지션 / 평가액 직관적으로 정상 범위.

이상 발견 시 즉시 §4 stop 게이트 검토.

### 3.2 매주 review (15분)

매주 같은 요일 / 시간 권장 (예: 일요일 21:00 KST).

수행:

1. **`/kpi?period=14d` 접속**.
2. **`/kpi/data` JSON 가져오기** — 운영자 도구 / curl 사용:
   ```bash
   curl -b cookies.txt 'http://localhost:8080/kpi/data?period=14d'
   ```
   응답 JSON 의 `trade_kpi` / `daily_kpi` / `slippage_kpi` 확인.
3. **paper 거래만 필터링** — JSON 의 trades 항목 중 `mode=="paper"` + `active_strategy_group=="vwap_ema_pullback_btc_paper"` 만 골라서 집계 (운영자 수동, 또는 follow-up PR 의 group 필터 UI 사용).
4. **다음 6 metric 기록**:
   - cumulative trade count
   - PF (profit factor)
   - win rate
   - total return (%)
   - max drawdown (%)
   - 평균 슬리피지 (bp) — TradeLog 의 `decision_exit_price` vs `exit_price` 비교

5. **§4 의 stop/kill 게이트 위반 여부 확인** — 위반 시 즉시 kill_switch ON.
6. **결과 노트 기록** — 간단히 `talk/` 또는 사적 노트:
   ```
   Week N: trades=X, PF=Y, win=Z%, ret=A%, DD=B%, slip=C bp · ok / warn / stop
   ```

### 3.3 2주차 mid-review (PRD §4)

| 결과 | 액션 |
|---|---|
| ≥ 5 trades + PF ≥ 0.85 + DD ≤ 7% | **계속** — 4주차까지 진행 |
| < 5 trades | 신호 발생 부족 — Codex 협의. candidate 조기 switch (vol_w30 → vol_1_4 더 빈번) 검토 |
| PF < 0.7 또는 DD > 10% | **kill_switch ON** · 조기 종료. STOP_RETIRE 후보 |

mid-review 결과는 별도 talk/ 노트로 기록:
```
talk/claude-validation-NNNN-vwap-btc-paper-week2.md
```

### 3.4 4주차 final review (PRD §4)

| 결과 | Verdict | 다음 단계 |
|---|---|---|
| ≥ 12 trades + PF ≥ 1.0 + 누적 ret ≥ 0% + DD ≤ 10% + slippage ≤ 50 bps avg | **PASS_LIVE** | 별도 PR 로 live 활성 검토 (소액 capital + 1~2주 paper-shadow live 비교) |
| ≥ 12 trades + PF 0.85~1.0 + DD ≤ 12% | **HOLD_PAPER_EXTEND** | paper 4주 추가 (총 8주) — 통계 보강 후 재결정 |
| < 12 trades 또는 PF < 0.85 또는 DD > 12% | **STOP_RETIRE** | strategy retire PR — `EXPERIMENTAL_STRATEGIES` 유지 또는 registry 제거 |

#### Anchor improvement check (informational)

paper 결과의 BTC ret 이 P2.5 in-sample (vol_w30 BTC 6m +5.77% / 1y +1.47%) 와 align?

- in-sample 대비 −20pp 이상 underperform → backtest overfit 의심 → STOP_RETIRE 상향 조정.
- in-sample 과 ±10pp 내 align → realistic. 위 verdict 게이트 그대로.

### 3.5 4주차 결과 노트

`talk/claude-validation-NNNN-vwap-btc-paper-week4-final.md` 작성 시 포함:

- 누적 trade count · PF · win rate · ret · DD · 슬리피지.
- §3.4 verdict.
- candidate 변경 이력 (vol_w30 → vol_1_4 등 발생 시).
- 다음 단계 권고.

#### Trade count 통계적 마진 (PRD §12 informational)

vol_w30 의 1y 103 trades = 약 0.28 trades/day = **주당 약 2 trades**.
- 2주 paper → 약 4 trades 예상 → §3.3 mid-review threshold 5 와 거의 일치.
- 4주 paper → 약 8 trades 예상 → §3.4 final threshold 12 미달 가능 → **HOLD_PAPER_EXTEND 분기 자주 발생**.

따라서 mid-review 의 "<5 trades" 시 즉시 retire 결정 안 하고 **4주차 / 8주차 까지 대기** 권장. `PF < 0.7` 이나 `DD > 10%` 같은 quality 게이트는 trade count 와 별개로 strict 적용.

---

## 4. Stop / kill switch 기준

### 4.1 자동 게이트 (코드가 알아서 작동)

기존 `RiskManager` 가 다음 자동 처리 — 운영자 별도 액션 0건:

- **일일 손실 한도**: 포트폴리오 합산 -3% 도달 시 신규 진입 자동 차단.
- **kill_switch=True**: 신규 진입 즉시 차단, 청산은 허용 (open 포지션 자연 종료).

### 4.2 수동 게이트 (운영자 monitoring)

매주 review (§3.2) 시 다음 발견하면 **즉시 kill_switch ON 으로 변경**:

| 조건 | 임계 | 액션 |
|---|---|---|
| **연속 손실** | 5 회 연속 SELL pnl<0 | kill_switch ON · 1주 휴식 후 재평가 |
| **누적 drawdown** | 시작 대비 -10% (paper equity) | kill_switch ON · 분석 후 retire 결정 |
| **PF 악화** | 2주 누적 PF < 0.7 | kill_switch ON · candidate switch (vol_w30 → vol_1_4) 또는 retire |
| **Trade count 부족** | 2주 < 5 trades | 신호 발생 자체 문제 — 분석 + candidate switch 또는 retire |
| **Slippage 이상** | 평균 > 50 bps (backtest 가정 5 bps × 10) | 시장 마이크로구조 의심 — 일시 중지 |
| **시간 한도** | 4 주 경과 | 강제 review · §3.4 final verdict 결정 |

### 4.3 kill_switch ON 절차

1. `/settings/risk` 페이지 접속.
2. "Kill switch" 토글 ON.
3. CSRF 토큰 통과 후 "Apply + Reload Bot" 클릭.
4. `/dashboard` 에서 kill_switch: `ON` 표시 확인.
5. Telegram 으로 "kill switch activated" 알림 도착 확인 (existing).
6. 다음 tick 부터 신규 BUY 차단. open 포지션은 SELL 신호 또는 다음 §5 rollback 시점까지 유지.

### 4.4 비상 정지 (긴급)

극단적 상황 (시스템 이상 / 큰 시장 변동) 시:

```bash
# V2 systemd
sudo systemctl stop auto-coin-web

# 또는 V1 nohup
pkill -f "auto_coin.main"
```

봇 프로세스 정지 = 추가 거래 0건. 이미 open 포지션은 다음 시작 시 strategy 가 evaluating.

---

## 5. KPI 확인 방법

### 5.1 paper 거래 분리 확인

paper 거래는 거래소 (업비트) 에 기록 안 됨 → **ledger KPI** (Codex 0010) 자동 isolation:

- `/kpi/ledger/data` — paper 거래 흔적 0건 보장.
- 의미: paper run 동안 ledger KPI 보고서는 "paper 외" 거래만 반영.

local TradeLog 에는 paper 거래 기록 — `mode=paper` + `strategy_name=vwap_ema_pullback` + `active_strategy_group=vwap_ema_pullback_btc_paper` 태그.

### 5.2 KPI 대시보드 사용 (현재)

본 PR 시점 V2 dashboard 는 group 필터 UI 없음 → JSON 응답에서 운영자 수동 필터링.

```bash
# 1) raw JSON 받기
curl -b cookies.txt -s 'http://localhost:8080/kpi/data?period=14d' > /tmp/kpi.json

# 2) jq 로 paper + 본 group 만 필터 (jq 가 설치돼 있다면)
jq '.trade_kpi.by_strategy[] | select(.strategy_name=="vwap_ema_pullback")' /tmp/kpi.json

# 3) full trade-by-trade 보고 싶으면 DB 직접 query
sqlite3 data/.auto_coin.db <<'SQL'
SELECT exit_at, pnl_ratio, pnl_krw, fee_krw, exit_reason_code
FROM tradelog
WHERE strategy_name='vwap_ema_pullback'
  AND mode='paper'
ORDER BY exit_at DESC
LIMIT 20;
SQL
```

### 5.3 KPI 대시보드 사용 (follow-up)

다음 follow-up PR 후보:

- `/kpi?group=vwap_ema_pullback_btc_paper` — `active_strategy_group` 드롭다운 UI.
- `compute_summary` 에 `strategy_group_filter` 인자.

본 runbook 에서는 §5.2 의 수동 필터링 사용.

### 5.4 슬리피지 KPI

`/kpi/data` 응답의 `slippage_kpi` 섹션. paper 모드 거래는 slippage 측정 안 됨 (mode=live 만 측정 — `_is_slippage_measurable` 가드). 따라서 paper run 동안 `slippage_kpi.measurable_count == 0` 정상.

paper-shadow live 단계 (별도 PR) 에서 slippage measurable 시작.

### 5.5 일별 / 주별 비교

`reports/` 디렉토리에 운영자가 직접 노트 작성:

- `reports/btc-paper-week1.md` (1주차 요약)
- `reports/btc-paper-week2.md` (2주차 + mid-review)
- `reports/btc-paper-week3.md`
- `reports/btc-paper-week4.md` (4주차 + final review)

자동 생성 후보 (follow-up): `scripts/eval_paper_verdict.py` — period + group 받아 §3.4 verdict 게이트 자동 산출.

---

## 6. Rollback 방법

paper 운영 중단 / 다른 strategy 로 복구.

### 6.1 정상 종료 (권장)

1. `/settings/risk` → kill_switch ON. 신규 진입 차단.
2. open 포지션 SELL 신호 대기 (또는 EMA 이탈 시 자동 청산).
3. open 포지션 0 확인 후 `/settings/strategy` → 다른 default 로 변경 (예: `volatility_breakout`).
4. `STRATEGY_PARAMS_JSON` 도 default 로 복구.
5. `TICKERS` 도 default (예: `KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP`) 로 복구.
6. `ACTIVE_STRATEGY_GROUP` 을 default (`legacy_single_ticker` 또는 비움) 로 변경.
7. `MAX_CONCURRENT_POSITIONS` / `MAX_POSITION_RATIO` 도 default 복구.
8. `COOLDOWN_MINUTES` 도 default (`30`) 복구.
9. "Apply + Reload Bot" 클릭.
10. `/dashboard` 에서 새 strategy 적용 확인.
11. `kill_switch` OFF (새 strategy 진입 허용).

### 6.2 즉시 롤백 (긴급)

1. `/settings/risk` → kill_switch ON.
2. 봇 정지 (`sudo systemctl stop auto-coin-web` 또는 `pkill`).
3. `.env` 백업본으로 교체 또는 git history 의 직전 commit 으로 되돌림 (단 secret 은 별도).
4. 봇 재시작.

### 6.3 결과 보존

paper 운영 종료 후:

1. `data/.auto_coin.db` 백업 (paper TradeLog 보존):
   ```bash
   cp data/.auto_coin.db data/.auto_coin.db.btc-paper-2026-MM-DD.bak
   ```
2. `talk/` 에 final 노트 작성 (§3.5).
3. `reports/btc-paper-week*.md` 모음.
4. P2.5 → paper 결과 흐름 그대로 별도 P3 / live PR 의 reference 로 활용.

### 6.4 live 활성화 절대 금지 — 본 runbook 범위

본 runbook 의 어떤 단계에서도 다음 변경 절대 금지:

- ❌ `MODE=live` 변경
- ❌ `LIVE_TRADING=true` 변경
- ❌ `EXPERIMENTAL_STRATEGIES` 에서 `vwap_ema_pullback` 제거
- ❌ `time_exit_disabled` 매핑 변경
- ❌ Volume Profile 관련 설정 활성

live 활성화는 **별도 PR + 운영자 명시 승인** 후에만 가능. 본 runbook 은 paper 까지만 다룬다.

---

## 7. Acceptance for paper start

다음 모두 ✓ 시 paper run 정식 시작:

- [ ] §2 시작 전 체크리스트 5 분야 모두 ✓.
- [ ] §1.2 의 candidate 중 하나 (`vol_w30` 권장) 의 STRATEGY_PARAMS_JSON 적용.
- [ ] §3 review 일정 (매일 / 매주 / 2주 mid / 4주 final) 캘린더 등록.
- [ ] §4 stop/kill 게이트 임계값 운영자 메모.
- [ ] §5 KPI 확인 방법 (curl + jq + sqlite) 선택 + 운영자 사전 연습.
- [ ] §6 rollback 절차 운영자 사전 연습.

위 모두 만족 시 §3.1 의 "매일 체크" 부터 시작.

---

## 8. References

- PRD: [`.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md`](../..//.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md)
- Test spec: [`.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md`](../..//.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md)
- P2.5 결과: `reports/vwap_ema_pullback_p25_validation.md`
- P2.5 reply: `talk/claude-to-codex-0015-vwap-p25-validation.md`
- Codex 0010 ledger KPI: `talk/codex-to-claude-0010-upbit-ledger-kpi.md` + `claude-to-codex-0010-upbit-ledger-kpi.md`
- V2 PLAN: [`./PLAN.md`](./PLAN.md)
