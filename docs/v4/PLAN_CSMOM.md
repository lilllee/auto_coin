# V4 · PLAN_CSMOM — Cross-Sectional Momentum Rotation

작성일: 2026-04-18
상태: 설계 단계 (미구현)
전제: `2026-04-18 수익성 검증` 및 `2026-04-18 새 전략군 방향 확정` 결론 위에서 작성.
    기존 전략군(VB · ATR · composite · EMA · turtle · regime)은 모두 후보 탈락으로 확정.

---

## 0. 한 줄 요약

> universe(KRW 시총 상위 N) 내에서 과거 X일 수익률 상위 K 종목을 주기적으로 rebalance 보유. 절대 threshold가 아닌 상대 rank로 신호를 생성, BTC 레짐 필터로 risk-off 구간 전면 flat, 종목 간 변동성 역가중 사이징.

---

## 1. 왜 CSMOM인가 (선정 근거 요약)

1. **Threshold-free**: rank 기반이라 시장별 sweet spot 불일치 문제 없음 (F1·F5 해소)
2. **Universe-level 단일 파라미터**: 한 설정이 전체 universe에 동일 적용 (P9 부합)
3. **자연스러운 멀티마켓 분산**: 항상 K 종목 보유 → 특정 자산 의존 감소 (F3 해소)
4. **Trade count 확보 용이**: rebalance마다 회전 발생 → WF window당 trade 수 자동 확보 (F6 해소)
5. **학술 근거**: cross-sectional momentum은 주식에서 30년+ 검증된 팩터 (Jegadeesh-Titman 1993 이후), 크립토 이식 연구 존재
6. **기존 인프라 70% 재사용**: Executor / OrderStore / WS / RiskManager 뼈대는 유지, backtest/WF만 portfolio-aware로 확장

---

## 2. 전략 사양

### 2-1. Universe

**기본 universe** (7 종목):
```
KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE, KRW-ADA, KRW-BNB
```

**선정 원칙**:
- 업비트 KRW 마켓 시총 상위 + 유동성 충분
- 최소 2년 이상 일봉 histogram 확보 가능
- 상장 폐지 / 거래중단 이슈 상대적으로 적음

**확장 규칙**:
- Stage 2~4 통과 후에만 universe 확장 검토
- universe 추가 시 전체 WF 재실행 필수

### 2-2. Signal: Rank metric

```
momentum_score_t(i) = close_t(i) / close_{t-L}(i) - 1
  where L = lookback_days (기본 60)
```

매 signal tick마다:
1. universe 전 종목 `momentum_score` 계산
2. descending 정렬
3. 상위 `hold_N` (기본 3) 종목 → target holdings

### 2-3. Regime filter (의무)

BTC 주봉 기준:
```
risk_on  := BTC_weekly_close > BTC_weekly_EMA20 AND EMA20_slope > 0
risk_off := 위 조건 어긋남
```

- `risk_off` 전환 시: **전 포지션 즉시 flat**, 신규 진입 차단
- `risk_on` 복귀 후 첫 rebal tick에서만 재진입

### 2-4. Rebalance cadence

- 기본 `rebal_days = 7` (주간)
- 매주 월요일 09:05 KST (일일 리셋 직후) 에 rank 재계산
- rebal tick에 만:
  - universe 상위 `hold_N` 재계산
  - 현 보유 중 hold-N에서 축출된 종목 → SELL
  - 새로 편입된 종목 → BUY (남는 자본을 universe 내 vol-inverse weight로 배분)
  - 유지 편입 종목은 HOLD

**중간 tick (rebal 외 일자)**:
- 신규 진입 없음
- 레짐 flip 감지 시 즉시 flat만 허용

### 2-5. Position sizing (변동성 역가중)

매 rebal 시:

```
ATR_i = atr(20, i)                        # 20일 ATR
vol_weight_i = 1 / (ATR_i / close_i)     # normalized vol-inverse
normalized_w_i = vol_weight_i / Σ vol_weight_j   # sum to 1 over held N
target_krw_i = portfolio_equity × risk_budget × normalized_w_i
```

- `risk_budget` (기본 0.8) — 포트폴리오의 몇 %를 위험 자산에 투입할지
- 변동성 큰 종목은 낮은 가중, 작은 종목은 높은 가중 → 종목 간 risk 기여도 균일화

### 2-6. Exit

다음 3가지만 허용:

1. **Rebalance exit**: rebal tick에 hold-N에서 축출됨 → SELL
2. **Regime exit**: risk-on → risk-off flip → 전원 flat
3. **Emergency exit** (기존 WS): 개별 종목 -15% 이상 급락 시 (catastrophic stop, normal volatility와 구분되도록 느슨하게)

**금지**:
- ❌ 고정 -2% 손절
- ❌ 08:55 time exit
- ❌ 개별 strategy.SELL signal

### 2-7. 파라미터 기본값

| 파라미터 | 기본값 | 비고 |
|---|---|---|
| `lookback_days` | 60 | momentum score window |
| `hold_N` | 3 | 동시 보유 상한 |
| `rebal_days` | 7 | 리밸런싱 주기 |
| `risk_budget` | 0.8 | 포트폴리오 자본 투입 비율 |
| `atr_window` | 20 | 사이징용 ATR 기간 |
| `regime_ema_weeks` | 20 | BTC 주봉 EMA 기간 |
| `catastrophic_stop` | -0.15 | 단일 종목 급락 비상 손절 |

---

## 3. 기존 인프라와의 관계

### 3-1. 재사용 (변경 없음)

- `exchange/upbit_client.py` · `ws_client.py` · `ws_private.py`
- `executor/order.py` · `executor/store.py`
- `notifier/telegram.py`
- `web/bot_manager.py` scheduler/lifespan (reload 로직 그대로)
- `web/auth.py` · `csrf.py` · `crypto.py`
- `log_stream` · SSE · 리포트 뷰어

### 3-2. 확장 (새 파일 또는 기능 추가)

#### 3-2-1. `src/auto_coin/backtest/portfolio_runner.py` (신규)

```python
def portfolio_backtest(
    candles: dict[str, pd.DataFrame],   # ticker → daily OHLCV
    *,
    lookback_days: int = 60,
    hold_N: int = 3,
    rebal_days: int = 7,
    risk_budget: float = 0.8,
    regime_df: pd.DataFrame | None = None,  # BTC weekly (optional)
    fee: float = 0.0005,
    slippage: float = 0.0005,
    initial_krw: float = 1_000_000,
) -> PortfolioBacktestResult:
    ...
```

반환:
- `equity_curve: pd.Series` (daily portfolio equity)
- `trades: list[PortfolioTrade]` (entry/exit per ticker per rebal)
- `benchmark_curve: pd.Series` (equal-weight B&H across universe)
- metrics: CAGR, Sharpe, Calmar, MDD, excess, trade count

#### 3-2-2. `src/auto_coin/backtest/portfolio_walk_forward.py` (신규)

- train 180d / test 60d (중요: 30d는 rebal 1회밖에 안 됨 → 60d 로 확장)
- parameter grid: `lookback_days ∈ [30,60,90,120]` × `hold_N ∈ [2,3,4]` × `rebal_days ∈ [3,7,14]`
- optimize by: `sharpe_ratio` (default) 또는 `cumulative_return`
- window 결과 집계: portfolio 기준 excess, positive window ratio, trade count aggregate

#### 3-2-3. `web/models.py::DailySnapshot` 확장

```python
portfolio_equity_krw: float       # 오늘 마감 시점 포트폴리오 평가액
portfolio_excess_vs_bnh: float    # 동일 universe B&H 대비 누적 차이
active_strategy_group: str        # e.g., "csmom_v1"
```

#### 3-2-4. `strategy/` 추가

- `portfolio/csmom.py` — 순수 rank+regime 함수 (I/O 없음, universe df dict 입력)
- 기존 per-ticker `Strategy` abstraction 에 맞지 않으므로 **별도 `PortfolioStrategy` 프로토콜 신설** 고려

#### 3-2-5. `web/bot_manager.py` · `bot.py` 확장

- 현재: per-ticker tick 루프 + per-ticker Store/Executor
- 추가: "portfolio tick" — 주간 rebalance tick에만 rank 계산 + 전체 종목 조정
- 기존 tick 루프는 WS emergency exit 전용으로 축소

### 3-3. 폐기 (deprecated 표기만, 삭제는 나중)

- 기존 6개 전략 (STRATEGY_REGISTRY)
- `exit_hour_kst` / `exit_minute_kst` → CSMOM에서는 사용 안 함
- `stop_loss_ratio=-0.02` → CSMOM 경로에서는 bypass, emergency 만
- `max_position_ratio` 고정 KRW 균등 → vol-inverse로 대체

---

## 4. 검증 파이프라인 (Stage 1 ~ 7)

> `수익성_검증_액션_체크리스트.md` B3 항목의 세부 절차.

### Stage 1. Design review

**통과**: 본 문서 검토 승인 · §2 파라미터 범위 확정
**탈락**: 설계 원칙 P1·P3·P4·P6·P9·P11 중 하나라도 위반

### Stage 2. In-sample backtest (2y)

**기간**: 최근 730일
**Universe**: 기본 7종목
**파라미터**: 기본값 (lookback=60, hold_N=3, rebal=7)

| 지표 | Hard fail | Soft warning | Pass target |
|---|---|---|---|
| Cumulative excess vs universe B&H | ≤ 0 | 0 ~ +5% | ≥ +10% |
| Sharpe | < 0.4 | 0.4 ~ 0.7 | ≥ 0.8 |
| MDD | < -50% | -50% ~ -35% | ≥ -30% |
| Trade count | < 30 | 30 ~ 50 | ≥ 60 |
| Expectancy per trade | < 0.15% | 0.15 ~ 0.3% | ≥ 0.3% |

**Hard fail 해당 시**: CSMOM 파라미터 재설계 또는 전략 자체 폐기 고려
**Pass target 미달이지만 soft warning 범위**: Stage 3로 진행하되 결과 의존

### Stage 3. Parameter sensitivity sweep

**스윕 grid**:
- `lookback_days ∈ [30, 45, 60, 90, 120, 180]`
- `hold_N ∈ [2, 3, 4, 5]`
- `rebal_days ∈ [3, 5, 7, 14]`

**통과**: 인접 grid 셀의 excess가 default 값 대비 ±50% 이내 유지, positive cells ≥ 60%
**Soft warning**: positive cells 40~60%
**Hard fail**: 한 점 sweet spot (주변 셀 전부 crash) 또는 positive cells < 40%

### Stage 4. Portfolio walk-forward

**설정**: train 180d · test 60d · step 30d · 12~18 windows (2y 기준)
**Optimizer**: Sharpe 기준

| 지표 | Hard fail | Soft warning | Pass target |
|---|---|---|---|
| Avg test excess vs universe B&H | ≤ 0% | 0 ~ +1% | ≥ +2% |
| Positive excess window ratio | < 40% | 40 ~ 55% | ≥ 55% |
| Train/Test 배수 | > 5x | 3x ~ 5x | ≤ 3x |
| Test trade count aggregate | < 30 | 30 ~ 50 | ≥ 50 |
| Best-param 안정성 (windows 간 mode 일치율) | < 30% | 30 ~ 60% | ≥ 60% |

**Hard fail 시**: 전략 재설계 (파라미터 범위 조정) 또는 폐기
**Soft warning**: Stage 5로 진행, 단 결과에 보수적 할인

### Stage 5. Multi-market / 확장 universe 검증

**목적**: universe에 알트 2~3 추가 또는 축소한 설정에서 일반성 확인
**통과**: 최소 2개 universe variant 에서 Stage 4 Hard fail 기준 넘음
**탈락**: default universe 에서만 작동 → 데이터 snooping 의심

### Stage 6. Paper live (최소 4주, 권장 8주)

**KPI**:
- 포트폴리오 누적 excess > 0 (vs universe B&H)
- 주간 drawdown ≤ -10%
- 체결 대비 backtest 성과 괴리 < 20%
- 예상 trade count (16~32건) 내 실제 체결 수

**Hard fail**: 체결/백테스트 괴리 > 30% · 4주 누적 excess < -5% · 운영 오류 (중복 주문, state 꼬임) 발생
**Soft warning**: 기대값 0~+0.2% 범위

### Stage 7. 소액 live (최소 8주)

**설정**: 총자본 50만원 · 종목당 risk_budget × equity / N
**KPI**:
- 누적 포트폴리오 excess vs universe B&H > 0
- MDD > -15%
- Trade count ≥ 15
- 체결 슬리피지 < 0.1% (업비트 시장가 기준)

**Hard fail**: 누적 음수 또는 운영 사고 발생 → 즉시 중단 + 재설계

---

## 5. 구현 단계 순서

> `수익성_검증_액션_체크리스트.md` B2 이후 세부 작업.

| Phase | 작업 | 소요 추정 |
|---|---|---|
| P0 | 본 PLAN 승인 | — |
| P1 | `backtest/portfolio_runner.py` 구현 + 테스트 | 2~3 세션 |
| P2 | `backtest/portfolio_walk_forward.py` + Stage 4 기준 자동 판정기 | 1~2 세션 |
| P3 | `strategy/portfolio/csmom.py` 순수 함수 구현 | 1 세션 |
| P4 | Stage 2~4 실행 (파라미터 basic + sweep + WF) | 1 세션 |
| **GATE** | Stage 4 hard-fail 기준 검토 | — |
| P5 | (통과 시) `web/models.py` DailySnapshot 컬럼 추가, KPI 페이지 확장 | 1~2 세션 |
| P6 | `bot.py` · `bot_manager.py` 에 portfolio tick 로직 추가 | 2~3 세션 |
| P7 | `web/settings_service.py` 에 CSMOM 설정 UI | 1~2 세션 |
| P8 | Stage 6 paper live 착수 | 4~8주 |
| **GATE** | Stage 6 결과 검토 | — |
| P9 | Stage 7 소액 live | 8주+ |

**P4 이전에는 어떤 UI/bot 코드도 건드리지 않는다** — 백테스트/WF만으로 살릴지 폐기할지 결정.

---

## 6. 리스크와 미해결 이슈

### 6-1. 전략 측

- **Crypto momentum crash risk**: 2022 같은 급락에서 momentum 전략이 특히 타격. regime filter로 완화하지만 지연 존재
- **Universe 구성 bias**: 상위 7개가 2024~2026 시점 기준 — 시점 의존. survivorship bias 가능성
- **Rebal day 집중 리스크**: 매주 월요일에 대량 체결 → 슬리피지 누적 가능. 실거래 slippage margin을 walk-forward에 반영 필요

### 6-2. 인프라 측

- **Universe 데이터 동기 수집**: 7개 종목 OHLCV를 rebal tick에 일괄 획득해야 함. API 제한 주의 (throttle lock 활용)
- **Portfolio state 복구**: 현재 `state/{TICKER}.json` 은 per-ticker. portfolio 일관성 보장을 위해 `state/portfolio.json` 추가 필요
- **기존 VB state와의 분리**: CSMOM 모드와 legacy 모드 충돌 방지 — bot_manager lifecycle에서 mutually exclusive

### 6-3. 검증 측

- **in-sample 착시 위험**: universe 내에서 뒤늦게 상장된 알트는 "과거 없음"이라 자동 제외되면서 survivorship bias 생김. portfolio_runner에서 listing 시점 반영 필수
- **B&H benchmark 정의**: "universe 동등비중 B&H"와 "BTC 단독 B&H" 두 기준 모두 리포트 (CSMOM이 BTC도 이겨야 실전 의미)

---

## 7. 다음 즉시 액션

1. 본 문서 승인 여부 결정
2. 승인 시 P1 착수: `backtest/portfolio_runner.py` 설계 상세 (함수 시그니처 · 데이터 타입 · 엣지 케이스) 문서화
3. 승인 전: 체크리스트 B1 (live 중단) · B5 (legacy 표기) · B6 (generic VB deprecation) 병행 가능
