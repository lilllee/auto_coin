# GUIDE.md

이 문서는 `deep-research-report (1).md`에 있는 전략들을 `volatility_breakout.py`처럼 `Strategy` 구현체로 옮길 때 참고하는 작성 가이드다.  
핵심 목표는 **"어떤 계수를 dataclass 필드로 둘지"**, **"어떤 컬럼을 전처리해서 `MarketSnapshot.df`에 넣어야 하는지"**, **"`generate_signal()`에서 어디까지 판단할지"**를 일관되게 정하는 것이다.

---

## 1. 먼저 `volatility_breakout.py`에서 따라야 할 패턴

현재 예시 구현은 아래 원칙을 갖고 있다.

1. `@dataclass(frozen=True)`로 전략을 정의한다.
2. 사람이 조정할 값은 모두 **계수(coefficient / parameter)** 로 클래스 필드에 둔다.
3. `__post_init__()`에서 계수 범위를 검증한다.
4. `generate_signal()`은 **순수 함수**처럼 동작한다.
   - 주문 실행 X
   - 네트워크 호출 X
   - 시간 조회 X
   - 로깅/출력 X
5. 데이터가 부족하거나 결측이면 공격적으로 `Signal.HOLD`를 반환한다.
6. 현재 엔진이 `MarketSnapshot(df, current_price, has_position)` 구조이므로,  
   지표 계산은 전략 클래스 안에서 매번 하지 말고 **전처리 단계에서 컬럼으로 넣어두는 방식**이 가장 깔끔하다.

추가로 주의할 점:

- 현재 `base.py`의 `MarketSnapshot` docstring은 `open` / `target` / `maN`처럼 **변동성 돌파 전략에 치우친 설명**을 갖고 있다.
- SMA/EMA/ADX/ATR/Donchian 전략을 추가할 예정이라면, 구현 전에 `MarketSnapshot` 설명을 **전략 일반형 문서**로 넓히는 편이 좋다.
- 즉, 실제 인터페이스는 재사용 가능하지만 **문서 계약(contract)** 은 업데이트가 필요할 수 있다.

즉, 새 전략도 기본적으로 아래 형태를 유지하면 된다.

```python
@dataclass(frozen=True)
class SomeStrategy(Strategy):
    name: str = "some_strategy"
    some_window: int = 20
    some_threshold: float = 0.5

    def __post_init__(self) -> None:
        if self.some_window < 1:
            raise ValueError(...)
        if self.some_threshold <= 0:
            raise ValueError(...)

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.df.empty:
            return Signal.HOLD
        ...
```

---

## 2. 공통 설계 규칙

### 2-1. 어떤 값을 "계수"로 빼야 하나

먼저 전제를 하나 분명히 해야 한다.

- 이 문서의 기본값 중 일부는 **리서치 보고서에서 바로 확정된 정답값**이 아니라,
  `volatility_breakout.py` 스타일로 구현을 시작하기 위한 **scaffold / starter default** 다.
- 특히 ATR 채널 돌파, AdTurtle 섹션의 일부 값은 **"첫 구현용 기본값"** 으로 봐야 한다.
- 따라서 보고서 수치가 명시적으로 고정된 항목(예: SMA200, EMA27/125, ADX90, ATR14, 3.5ATR 스탑 등)과  
  문서 편의를 위해 제안한 초기값을 구분해서 읽어야 한다.

다음 값들은 하드코딩하지 말고 dataclass 필드로 두는 편이 좋다.

- 기간값: `ma_window`, `ema_fast_window`, `adx_window`, `atr_window`
- 배수값: `k`, `stop_atr_multiplier`, `trail_atr_multiplier`
- 임계값: `adx_threshold`, `break_even_atr`, `take_profit_pct`
- on/off 플래그: `require_ma_filter`, `use_take_profit`, `allow_sell_signal`

반대로 아래는 보통 계수로 빼지 않아도 된다.

- `df.iloc[-1]`처럼 마지막 봉을 읽는 방식
- 데이터 없을 때 `HOLD` 반환
- `has_position`이면 신규 진입 막기 같은 공통 방어 로직

### 2-2. 컬럼 이름은 미리 표준화해 두는 게 좋다

`volatility_breakout.py`가 `target`, `ma5` 같은 컬럼을 기대하듯, 새 전략도 컬럼 이름을 문서로 먼저 고정하는 게 좋다.

권장 규칙:

- SMA: `sma200`
- EMA: `ema27`, `ema125`
- ATR: `atr14`
- ADX: `adx90`
- Donchian: `donchian_high_20`, `donchian_low_10`
- 채널값/스탑값처럼 전략 전용 값:
  - `upper_channel`
  - `lower_channel`
  - `breakout_long`
  - `turtle_entry`
  - `turtle_exit`

### 2-3. BUY만 낼지, SELL도 낼지 먼저 정해야 한다

현재 예시 `volatility_breakout.py`는 **진입만 판단**하고 청산은 외부 스케줄러/RiskManager가 처리한다.

그래서 새 전략은 둘 중 하나로 맞추면 된다.

#### 옵션 A. 기존 예시와 동일한 "엔트리 전용" 패턴
- 클래스는 `BUY` / `HOLD`만 반환
- 손절, 익절, 시간청산, 트레일링은 외부 모듈이 담당
- 현재 코드베이스 흐름과 가장 잘 맞음

#### 옵션 B. 전략 내부에서 `SELL`까지 반환
- `has_position=True`일 때 청산 조건을 계산해서 `Signal.SELL`
- 전략별 exit rule이 강한 경우 문서화가 명확함
- 대신 실거래/백테스트 엔진이 `SELL`을 확실히 처리해야 함

**이 디렉터리 기준으로는 옵션 A가 더 안전**하다.  
특히 보고서 전략 중 ATR 스탑/트레일링/배제구간은 외부 상태 관리가 필요한 경우가 많기 때문이다.

---

## 3. 전략별 작성 가이드

---

## 3-1. SMA200 추세 필터

### 추천 클래스명
- `Sma200RegimeStrategy`

### 추천 `name`
- `"sma200_regime"`

### 추천 계수

```python
ma_window: int = 200
allow_sell_signal: bool = False
```

추가로 선택 가능한 확장 계수:

```python
buffer_pct: float = 0.0
```

- `ma_window`: 기본값 200 고정이 핵심이다.
- `allow_sell_signal`: `True`면 보유 중 하향 이탈 시 `SELL` 반환.
- `buffer_pct`: 채찍질 완화용 완충값. 다만 **보고서 원형 전략에는 없는 값**이므로 기본은 `0.0` 권장.

### `__post_init__()` 검증 예시

- `ma_window >= 2`
- `buffer_pct >= 0`

### 필요한 DataFrame 컬럼

- `close`
- `sma200` 또는 `sma{ma_window}`

### 권장 전처리

```text
sma200 = close.rolling(200).mean()
```

### `generate_signal()` 로직

#### 엔트리 전용 패턴
1. 이미 보유 중이면 `HOLD`
2. `sma200` 결측이면 `HOLD`
3. `current_price >= sma200 * (1 + buffer_pct)` 이면 `BUY`
4. 아니면 `HOLD`

#### BUY/SELL 통합 패턴
1. 미보유 + 가격이 SMA200 위 => `BUY`
2. 보유 중 + 가격이 SMA200 아래 => `SELL`
3. 그 외 `HOLD`

### 구현 메모

- 이 전략은 계산이 단순해서 `volatility_breakout.py`와 가장 비슷하게 만들기 쉽다.
- 보고서 기준 핵심은 "종가가 SMA200 위면 risk-on, 아래면 cash" 이다.
- 따라서 가장 보수적인 구현은 **봉 마감 기준으로만 상태를 확정하고, 실제 체결은 다음 봉/다음 실행 시점에 반영**하는 방식이다.
- 현 구현이 실시간 `current_price`를 사용한다면,  
  **종가 기준 전략을 실시간 가격으로 실행할지**, **봉 마감 확정값만 쓸지**를 엔진 레벨에서 명확히 해야 한다.

### 가장 단순한 구현 방향

`volatility_breakout.py` 스타일을 유지하려면:

- 클래스 안에서는 `sma200`과 현재가 비교만 한다.
- 실제 "다음 봉 시가 진입/청산" 해석은 백테스트/실행 엔진에서 담당한다.

---

## 3-2. EMA27/125 + ADX90 + ATR14 추세추종

### 추천 클래스명
- `EmaAdxAtrTrendStrategy`

### 추천 `name`
- `"ema_adx_atr_trend"`

### 추천 계수

```python
ema_fast_window: int = 27
ema_slow_window: int = 125
adx_window: int = 90
adx_threshold: float = 14.0
atr_window: int = 14
stop_atr_multiplier: float = 3.5
break_even_atr: float = 1.5
trail_atr_multiplier: float = 3.0
allow_sell_signal: bool = False
```

이 중 우선순위는 다음과 같다.

#### 전략 클래스에 반드시 둘 값
- `ema_fast_window`
- `ema_slow_window`
- `adx_threshold`
- `adx_window`
- `atr_window`

#### 외부 리스크 매니저로 넘겨도 되는 값
- `stop_atr_multiplier`
- `break_even_atr`
- `trail_atr_multiplier`

즉, **진입 신호 클래스**만 만들 거면 위 3개 ATR 관련 값은 문서상만 유지하고 실제 클래스 필드에서는 빼도 된다.

### `__post_init__()` 검증 예시

- `ema_fast_window >= 1`
- `ema_slow_window > ema_fast_window`
- `adx_window >= 1`
- `atr_window >= 1`
- `adx_threshold >= 0`
- `stop_atr_multiplier > 0`
- `break_even_atr >= 0`
- `trail_atr_multiplier > 0`

### 필요한 DataFrame 컬럼

- `ema27`
- `ema125`
- `adx90`
- `atr14`

가변 윈도우를 허용할 거면 아래 네이밍으로 통일하는 것이 좋다.

- `ema{ema_fast_window}`
- `ema{ema_slow_window}`
- `adx{adx_window}`
- `atr{atr_window}`

### `generate_signal()` 로직

#### 엔트리 전용 패턴
1. `has_position=True`면 `HOLD`
2. EMA/ADX 컬럼이 없거나 결측이면 `HOLD`
3. `ema_fast > ema_slow` 확인
4. `adx >= adx_threshold` 확인
5. 모두 만족하면 `BUY`

#### BUY/SELL 통합 패턴
보유 중일 때 아래 중 하나면 `SELL` 후보:

- `ema_fast <= ema_slow`
- 또는 외부가 계산한 `stop_price`, `trail_stop_price` 하향 돌파

하지만 ATR 기반 스탑/트레일링은 **진입가/최고가 상태**가 필요할 수 있으므로,  
현재의 `MarketSnapshot` 구조만으로는 외부 리스크 매니저로 분리하는 쪽이 더 자연스럽다.

### 구현 메모

- 이 전략의 핵심 계수는 보고서 기준으로 **27 / 125 / 90 / 14 / 14 / 3.5 / 1.5 / 3.0**이다.
- 단, `generate_signal()`만 구현하는 클래스라면 실제로 의미 있는 값은  
  **EMA fast/slow, ADX window/threshold** 쪽이다.
- ATR 값은 "진입 여부"보다 "진입 후 리스크 관리"에 더 가깝다.
- 보고서에 언급된 **쿨다운 등 추가 조건** 도 있다면, 이것 역시 현재 `MarketSnapshot`만으로는 부족할 수 있으므로
  전략 외부의 상태 관리자 또는 실행 엔진 규칙으로 분리하는 편이 낫다.

### 추천 분리 방식

#### 전략 클래스
- 진입 조건만 담당
- `BUY` / `HOLD`

#### 외부 리스크 매니저
- 초기 스탑: `entry - 3.5 * atr`
- BE 스탑: `profit >= 1.5 * atr`
- 트레일링: `highest_since_entry - 3.0 * atr`

이렇게 나누면 `volatility_breakout.py`의 설계 철학과 가장 잘 맞는다.

---

## 3-3. ATR 변동성 채널 돌파

### 추천 클래스명
- `AtrChannelBreakoutStrategy`

### 추천 `name`
- `"atr_channel_breakout"`

### 추천 계수

```python
atr_window: int = 14
channel_multiplier: float = 1.0
stop_loss_pct: float = 0.015
take_profit_pct: float = 0.10
use_pullback_exit: bool = True
allow_sell_signal: bool = False
```

설명:

- `atr_window`: 보고서에서는 ADR/ATR 기간 탐색이 있었지만 구현 시작점은 14가 무난하다.
- `channel_multiplier`: 보고서 표현이 `Low + ATR`, `High - ATR` 형태라 기본값 1.0.
- `stop_loss_pct`: 보고서 범위 1~2%를 반영해 기본 1.5%.
- `take_profit_pct`: 보고서 범위 10~16%를 반영해 기본 10%.
- `use_pullback_exit`: `(high - atr)` 되밀림 청산을 쓸지 여부.

> 주의: 여기서 `atr_window=14`는 **구현 시작용 기본값** 이다.  
> 보고서 핵심은 "ATR/ADR 기반 채널 돌파"이며, 이 숫자 자체가 보고서의 단일 정답이라고 보면 안 된다.

### `__post_init__()` 검증 예시

- `atr_window >= 1`
- `channel_multiplier > 0`
- `0 < stop_loss_pct < 1`
- `0 < take_profit_pct < 1`

### 필요한 DataFrame 컬럼

아래 중 하나로 고정하는 것을 권장한다.

#### 방식 A. 원재료 컬럼만 넣고 전략 클래스에서 조합
- `high`
- `low`
- `close`
- `atr14`

#### 방식 B. 채널 컬럼을 전처리에서 완성
- `upper_channel`
- `lower_channel`

`volatility_breakout.py` 스타일과 가장 비슷한 것은 **방식 B**다.  
즉, 전략 클래스는 계산보다 **비교**에 집중하게 만드는 편이 좋다.

### 권장 전처리

```text
upper_channel = low + atr * channel_multiplier
lower_channel = high - atr * channel_multiplier
```

### `generate_signal()` 로직

#### 엔트리 전용 패턴
1. 보유 중이면 `HOLD`
2. `upper_channel` 결측이면 `HOLD`
3. `current_price > upper_channel`이면 `BUY`

#### BUY/SELL 통합 패턴
보유 중이고 아래 중 하나면 `SELL`

- `current_price < lower_channel` and `use_pullback_exit`
- `current_price <= entry_price * (1 - stop_loss_pct)`
- `current_price >= entry_price * (1 + take_profit_pct)`

하지만 마지막 두 조건은 **entry_price 상태**가 필요하므로,  
현 구조에서는 역시 외부 RiskManager가 처리하는 편이 낫다.

### 구현 메모

- 이 전략은 `volatility_breakout.py`와 매우 비슷하게 만들 수 있다.
- 차이는 `target` 대신 `upper_channel`을 쓰는 점뿐이다.
- 그래서 실제 구현 형태도 아래처럼 단순화 가능하다.

```text
if has_position: HOLD
if current_price <= upper_channel: HOLD
return BUY
```

즉, **진입 전용 전략**으로는 구현 난도가 낮다.

---

## 3-4. AdTurtle (개선형 Turtle)

### 추천 클래스명
- `AdTurtleStrategy`

### 추천 `name`
- `"ad_turtle"`

### 추천 계수

```python
entry_window: int = 20
exit_window: int = 10
atr_window: int = 14
initial_stop_atr_multiplier: float = 2.0
reentry_buffer_atr: float = 1.0
use_exclusion_zone: bool = True
allow_pyramiding: bool = False
allow_sell_signal: bool = False
```

설명:

- `entry_window`, `exit_window`: Donchian 상단/하단 기간
- `atr_window`: ATR 기간
- `initial_stop_atr_multiplier`: Turtle류에서 흔한 2ATR 시작값
- `reentry_buffer_atr`: 손절 후 재진입 금지 폭
- `use_exclusion_zone`: 배제구간 사용 여부
- `allow_pyramiding`: 피라미딩 허용 여부

> 주의: `entry_window=20`, `exit_window=10`, `atr_window=14`, `reentry_buffer_atr=1.0`은  
> **보고서의 단일 확정 계수라기보다 보수적 초기 스캐폴드 값** 으로 읽는 것이 맞다.

주의: 보고서에는 "AdTurtle B 최적값"의 성과가 있지만,  
**모든 정확한 세부 파라미터가 이 디렉터리 코드에 정리된 것은 아니다.**  
따라서 구현 첫 버전은 **과도한 최적값 복제보다 보수적 일반형**으로 시작하는 게 맞다.

### `__post_init__()` 검증 예시

- `entry_window >= 2`
- `exit_window >= 1`
- `atr_window >= 1`
- `initial_stop_atr_multiplier > 0`
- `reentry_buffer_atr >= 0`

추가 권장:
- `entry_window > exit_window`

### 필요한 DataFrame 컬럼

- `donchian_high_{entry_window}`
- `donchian_low_{exit_window}`
- `atr{atr_window}`

배제구간까지 클래스가 직접 처리하려면 추가 상태가 필요할 수 있다.

예:
- `last_stop_price`
- `reentry_upper_bound`
- `reentry_lower_bound`

하지만 이런 값은 현재 `MarketSnapshot.df`만으로는 충분히 깔끔하지 않을 수 있다.

### `generate_signal()` 로직

#### 최소 구현(추천)
1. 보유 중이면 `HOLD`
2. `donchian_high_X` 결측이면 `HOLD`
3. `current_price > donchian_high_X`면 `BUY`
4. 단, 배제구간 사용 중이면 재진입 금지 조건을 먼저 체크

#### SELL까지 넣는 경우
보유 중이고 아래 조건이면 `SELL`

- `current_price < donchian_low_Y`
- 또는 `current_price <= entry_price - initial_stop_atr_multiplier * atr`

### 구현 메모

이 전략은 네 전략 중 **현재 인터페이스와 가장 덜 맞는 편**이다.

이유:

1. 배제구간은 "직전 손절 가격" 같은 상태가 필요하다.
2. 피라미딩은 현재 포지션 수량/추가 진입 횟수 상태가 필요하다.
3. ATR 스탑은 진입가와 이후 최고가 추적이 필요하다.

그래서 첫 구현은 아래처럼 나누는 것이 좋다.

#### 1단계: 전략 클래스
- Donchian 돌파 진입만 판단
- 배제구간이 없다면 가장 단순

#### 2단계: 외부 상태 관리자
- 손절 후 exclusion zone 저장
- 재진입 허용 여부 판단
- ATR 스탑 관리
- 피라미딩 관리

즉, AdTurtle은 `volatility_breakout.py`처럼 "한 파일로 깔끔하게 끝나는 전략"이라기보다,  
**전략 + 리스크/상태 매니저**의 조합으로 보는 게 맞다.

---

## 4. 어떤 전략이 `volatility_breakout.py`와 가장 비슷한가

구현 난이도 기준으로 정리하면 아래 순서가 좋다.

1. **SMA200**
   - 단순 비교형
   - 상태 거의 필요 없음
2. **ATR 채널 돌파**
   - `target` 대신 `upper_channel`만 쓰면 됨
   - 진입 전용으로 만들기 쉬움
3. **EMA+ADX+ATR**
   - 진입은 쉽지만 exit/risk가 외부 상태를 요구
4. **AdTurtle**
   - 배제구간/피라미딩 때문에 상태 관리가 가장 많음

즉, 실제 코드 작성 순서도 아래처럼 추천한다.

1. `Sma200RegimeStrategy`
2. `AtrChannelBreakoutStrategy`
3. `EmaAdxAtrTrendStrategy`
4. `AdTurtleStrategy`

---

## 5. 구현 시 추천 파일 구조

`volatility_breakout.py`와 비슷하게 유지하려면 파일을 전략별로 나누는 것이 좋다.

```text
strategy/
  base.py
  volatility_breakout.py
  sma200_regime.py
  atr_channel_breakout.py
  ema_adx_atr_trend.py
  ad_turtle.py
```

전처리 함수까지 분리하고 싶다면:

```text
strategy/
  indicators.py
  enrich.py
  ...
```

### 추천 역할 분리

#### 전략 클래스
- 진입/기본 청산 규칙 해석
- 결측치 방어
- `Signal` 반환

#### 전처리 함수
- SMA / EMA / ATR / ADX / Donchian 계산
- 컬럼명 표준화

#### 리스크 매니저
- 손절/익절
- 트레일링
- 시간청산
- exclusion zone
- 포지션 크기 계산

---

## 6. 전략별 "필수 계수"만 빠르게 요약

### 6-1. SMA200

```python
ma_window: int = 200
allow_sell_signal: bool = False
buffer_pct: float = 0.0  # 선택
```

### 6-2. EMA+ADX+ATR

```python
ema_fast_window: int = 27
ema_slow_window: int = 125
adx_window: int = 90
adx_threshold: float = 14.0
atr_window: int = 14
stop_atr_multiplier: float = 3.5
break_even_atr: float = 1.5
trail_atr_multiplier: float = 3.0
allow_sell_signal: bool = False
```

### 6-3. ATR 채널 돌파

> 아래 값들은 **starter default** 로 읽는 것이 안전하다.

```python
atr_window: int = 14
channel_multiplier: float = 1.0
stop_loss_pct: float = 0.015
take_profit_pct: float = 0.10
use_pullback_exit: bool = True
allow_sell_signal: bool = False
```

### 6-4. AdTurtle

> 아래 값들은 **starter default** 이며, 보고서 확정 정답값으로 단정하면 안 된다.

```python
entry_window: int = 20
exit_window: int = 10
atr_window: int = 14
initial_stop_atr_multiplier: float = 2.0
reentry_buffer_atr: float = 1.0
use_exclusion_zone: bool = True
allow_pyramiding: bool = False
allow_sell_signal: bool = False
```

---

## 7. 최종 권장사항

이 디렉터리의 현재 구조를 기준으로 하면 아래 원칙이 가장 실전적이다.

1. **전략 클래스는 최대한 단순하게 유지한다.**
   - 특히 `volatility_breakout.py`처럼 진입 위주가 깔끔하다.
2. **지표 계산은 전처리로 뺀다.**
   - 전략 클래스 안에서 rolling/EMA/ATR를 매번 다시 계산하지 않는다.
3. **상태가 필요한 청산 규칙은 외부로 뺀다.**
   - ATR 스탑
   - 트레일링
   - exclusion zone
   - 피라미딩
4. **첫 구현은 원형 전략을 그대로 두고, 최적화 파라미터 추가는 나중에 한다.**
   - 특히 AdTurtle, ATR 채널 돌파는 과최적화 위험이 크다.

한 줄로 정리하면:

> `volatility_breakout.py`처럼 만들고 싶다면,  
> **전략 클래스에는 "지금 사도 되는가?"만 넣고,  
> "어떻게 나올 것인가?"는 외부 리스크 매니저/상태 관리자로 분리하는 방향이 가장 안정적이다.**
