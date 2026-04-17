# 작업 위임 문서 — 검증 단계 (Codex용)

> **작성일:** 2026-04-15
> **대상:** Codex 또는 다음 AI 에이전트
> **목표:** 프리셋 A 페이퍼 가동 + 백테스트 러너 확장 + ADX 스윕

---

## 현재 상태

- **테스트:** 501 passed, ruff clean
- **전략:** 6개 등록 완료 (VB, SMA200, ATR채널, EMA+ADX, AdTurtle, **합성전략**)
- **합성전략:** `sma200_ema_adx_composite` — SMA200 레짐필터 + EMA+ADX 진입
- **백테스트 러너:** VB 전용 하드코딩 상태 (멀티전략 미지원)

---

## 작업 1: 프리셋 A 페이퍼 설정

### 목표
웹 UI에서 아래 설정을 적용하고 봇을 시작. **코드 변경 없음**, 설정만.

### 적용할 설정값

**전략 (`/settings/strategy`):**
| 항목 | 값 |
|------|-----|
| strategy_name | `sma200_ema_adx_composite` |
| sma_window | 200 |
| ema_fast_window | 27 |
| ema_slow_window | 125 |
| adx_window | 90 |
| adx_threshold | 14.0 |

**포트폴리오 (`/settings/portfolio`):**
| 항목 | 값 |
|------|-----|
| tickers | `KRW-BTC` (단일) |
| watch_tickers | (비워둠) |

**리스크 (`/settings/risk`):**
| 항목 | 값 |
|------|-----|
| max_position_ratio | 0.10 (10%) |
| stop_loss_ratio | -0.015 (-1.5%) |
| daily_loss_limit | -0.02 (-2%) |
| max_concurrent_positions | 1 |
| paper_initial_krw | 500000 |
| kill_switch | OFF |
| cooldown_minutes | 60 |

**스케줄 (`/settings/schedule`):**
| 항목 | 값 |
|------|-----|
| mode | paper |
| live_trading | OFF |
| check_interval_seconds | 30 |
| heartbeat_interval_hours | 6 |
| exit_hour_kst | 8 |
| exit_minute_kst | 55 |

> **시간 청산 주의:** 현재 exit_hour_kst는 전역 설정이라 전략별 OFF가 불가.
> 추세전략에는 시간 청산 OFF가 권장이나, 현 구조에서는 설정으로 비활성화할 수 없음.
> → **향후 개선 포인트** (exit 비활성화 옵션 추가 또는 전략별 exit 모드 분리)

### 설정 후 확인 사항
- 봇 시작 후 대시보드(`/`)에서 "sma200_ema_adx_composite" 전략 표시 확인
- 텔레그램 하트비트 메시지 수신 확인
- 로그에서 `strategy=sma200_ema_adx_composite` 확인

---

## 작업 2: 백테스트 러너 확장 (최소 변경)

### 목표
`backtest/runner.py`를 확장하여 합성전략 단일 실행 + ADX 스윕 가능하게.

### 현재 runner.py 문제점

```
src/auto_coin/backtest/runner.py (205줄)
```

| 문제 | 위치 | 설명 |
|------|------|------|
| VB 하드코딩 | line 23 | `from auto_coin.strategy.volatility_breakout import VolatilityBreakout` |
| VB 전용 진입 | line 81-93 | `high >= target` 비교로 진입 판단 (VB 로직) |
| enrich_daily 직접 호출 | line 162 | `enrich_for_strategy()` 미사용 |
| CLI에 strategy 옵션 없음 | line 172-184 | `--strategy`, `--params` 없음 |
| K 스윕만 가능 | line 182 | `--sweep`가 K값 전용 |

### 변경 범위 (최소)

#### 2-1. `backtest()` 함수 시그니처 변경

**Before:**
```python
def backtest(df, strategy: VolatilityBreakout, *, fee, slippage) -> BacktestResult:
```

**After:**
```python
from auto_coin.strategy.base import Strategy, MarketSnapshot, Signal

def backtest(df, strategy: Strategy, *, fee=0.0005, slippage=0.0) -> BacktestResult:
```

#### 2-2. 진입/청산 로직을 `generate_signal()` 기반으로 변경

**Before (VB 전용):**
```python
# line 81-93: high >= target 비교
if high < target:
    continue
if strategy.require_ma_filter:
    ...
entry_price = float(target) * (1.0 + slippage)
```

**After (범용):**
```python
for i in range(len(df) - 1):
    row = df.iloc[i]
    price = float(row["close"])  # 확정봉 종가 기준

    # 보유 중이면 청산 판단
    if in_position:
        snap = MarketSnapshot(df=df.iloc[:i+1], current_price=price, has_position=True)
        signal = strategy.generate_signal(snap)
        if signal is Signal.SELL:
            # 다음 봉 시가에 청산
            exit_price = float(df.iloc[i+1]["open"]) * (1.0 - slippage)
            ret = (exit_price * (1-fee)) / (entry_price * (1+fee)) - 1.0
            trades.append(Trade(...))
            in_position = False
            continue

    # 미보유면 진입 판단
    if not in_position:
        snap = MarketSnapshot(df=df.iloc[:i+1], current_price=price, has_position=False)
        signal = strategy.generate_signal(snap)
        if signal is Signal.BUY:
            entry_price = price * (1.0 + slippage)
            entry_date = df.index[i]
            in_position = True
```

**핵심 차이:**
- VB는 `high >= target`으로 일중 돌파를 가정했지만
- 범용 버전은 `generate_signal()`의 결과에 따름
- 합성전략의 SELL 시그널(SMA200 아래)도 처리됨

#### 2-3. `_run_one()` 확장

```python
import json
from auto_coin.strategy import create_strategy
from auto_coin.data.candles import enrich_for_strategy

def _run_one(df, strategy_name="volatility_breakout", strategy_params=None,
             fee=0.0005, slippage=0.0, ma_window=5, k=0.5) -> BacktestResult:
    params = strategy_params or {}
    enriched = enrich_for_strategy(df, strategy_name, params, ma_window=ma_window, k=k)
    strategy = create_strategy(strategy_name, params)
    return backtest(enriched, strategy, fee=fee, slippage=slippage)
```

#### 2-4. CLI 확장

기존 `--k`, `--sweep` 유지하면서 추가:

```python
p.add_argument("--strategy", default="volatility_breakout",
               help="전략 이름 (volatility_breakout, sma200_ema_adx_composite, ...)")
p.add_argument("--params", default="{}",
               help='전략 파라미터 JSON (예: \'{"adx_threshold": 14}\')')
p.add_argument("--sweep-param", type=str, default=None,
               help="스윕할 파라미터 이름 (예: adx_threshold)")
p.add_argument("--sweep-range", nargs=3, type=float, metavar=("START", "STOP", "STEP"),
               help="파라미터 스윕 범위 (예: 10 20 2)")
```

**사용 예시:**

```bash
# 합성전략 단일 실행
python3 -m auto_coin.backtest.runner \
  --strategy sma200_ema_adx_composite \
  --ticker KRW-BTC --days 365

# ADX threshold 스윕
python3 -m auto_coin.backtest.runner \
  --strategy sma200_ema_adx_composite \
  --ticker KRW-BTC --days 365 \
  --sweep-param adx_threshold \
  --sweep-range 10 20 2

# 기존 VB도 그대로 동작 (하위 호환)
python3 -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --k 0.5
```

#### 2-5. 마지막 보유 포지션 강제 청산

범용 백테스트에서 마지막 봉까지 보유 중이면 마지막 봉 종가에 청산:

```python
# 루프 종료 후
if in_position:
    last_price = float(df.iloc[-1]["close"]) * (1.0 - slippage)
    ret = (last_price * (1-fee)) / (entry_price * (1+fee)) - 1.0
    trades.append(Trade(...))
```

### 테스트 추가

기존 `tests/test_backtest.py` 패턴 유지하면서 추가:

- `test_backtest_composite_strategy` — 합성전략으로 백테스트 실행 가능
- `test_backtest_sell_signal_closes_position` — SELL 시그널로 포지션 청산
- `test_backtest_vb_backward_compat` — 기존 VB 백테스트 결과 동일
- `test_cli_strategy_param` — `--strategy` CLI 옵션 동작
- `test_cli_sweep_param` — `--sweep-param` CLI 옵션 동작

### 변경하지 않을 것
- `Trade`, `BacktestResult` 데이터클래스 — 그대로 유지
- `_build_result()` — 그대로 유지
- `_is_finite()` — 그대로 유지
- RiskManager 통합 — 하지 않음
- 멀티 타임프레임 — 하지 않음

---

## 작업 3: ADX 스윕 실행

### 러너 확장 완료 후 실행할 명령어

```bash
# 1. 단일 실행 (기본값 확인)
python3 -m auto_coin.backtest.runner \
  --strategy sma200_ema_adx_composite \
  --ticker KRW-BTC --days 365

# 2. ADX 스윕
python3 -m auto_coin.backtest.runner \
  --strategy sma200_ema_adx_composite \
  --ticker KRW-BTC --days 365 \
  --sweep-param adx_threshold \
  --sweep-range 10 20 2

# 3. VB 비교 (같은 기간)
python3 -m auto_coin.backtest.runner \
  --ticker KRW-BTC --days 365 --k 0.5
```

### 결과 출력 형식 (예상)

```
# KRW-BTC  strategy=sma200_ema_adx_composite  candles=365
# ADX threshold sweep: [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
adx_threshold  trades  cum_return   mdd      win_rate
      10.0       18    +12.34%    -8.21%     44.4%
      12.0       15    +10.56%    -7.15%     46.7%
      14.0       12     +8.90%    -6.33%     50.0%
      16.0        8     +6.12%    -5.88%     50.0%
      18.0        5     +3.45%    -4.21%     60.0%
      20.0        3     +1.23%    -3.10%     66.7%
```

---

## 작업 4: 완료 후 보고

아래 3가지를 짧게 정리:

1. **페이퍼 시작 시 실제 적용 설정값** — 웹 UI 설정 스크린샷 또는 설정 요약
2. **백테스트 runner 가능/부족 범위:**
   - 가능: 전략별 단일 실행, 파라미터 스윕, VB 하위 호환
   - 부족: 손절/일일한도/쿨다운 미반영, 멀티타임프레임 미지원
3. **ADX 스윕 결과 표** — 위 형식으로 출력

---

## 참고 파일

| 파일 | 용도 |
|------|------|
| [`src/auto_coin/backtest/runner.py`](../src/auto_coin/backtest/runner.py) | **핵심 수정 대상** — 백테스트 러너 |
| [`src/auto_coin/strategy/__init__.py`](../src/auto_coin/strategy/__init__.py) | 전략 레지스트리, `create_strategy()` 팩토리 |
| [`src/auto_coin/strategy/sma200_ema_adx_composite.py`](../src/auto_coin/strategy/sma200_ema_adx_composite.py) | 합성전략 클래스 |
| [`src/auto_coin/strategy/base.py`](../src/auto_coin/strategy/base.py) | `Strategy` ABC, `MarketSnapshot`, `Signal` |
| [`src/auto_coin/data/candles.py`](../src/auto_coin/data/candles.py) | `enrich_for_strategy()` 디스패처 |
| [`tests/test_backtest.py`](../tests/test_backtest.py) | 기존 백테스트 테스트 (패턴 참고) |
| [`docs/전략_백테스트_개발_가이드.md`](전략_백테스트_개발_가이드.md) | 상세 확장 가이드 (코드 예시 포함) |
| [`docs/합성전략_운용_가이드.md`](합성전략_운용_가이드.md) | 프리셋/검증 기준/리스크 체크리스트 |
| [`CLAUDE.md`](../CLAUDE.md) | 프로젝트 규칙, 모듈 경계, 운영 상수 |

---

## 제약 사항

1. **기존 501 테스트 깨뜨리지 말 것**
2. **`strategy/` 순수 함수 유지** — I/O 금지
3. **VB 하위 호환** — `--k`, `--sweep` 기존 CLI 그대로 동작
4. **최소 변경** — runner.py만 수정, 다른 모듈 건드리지 않음
5. **커밋 단위:** 러너 확장 1커밋 → ADX 스윕 결과는 `reports/`에 저장 1커밋
