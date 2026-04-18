# pyupbit API 정리

공식 문서(Quickstart / QUOTATION API / EXCHANGE API)와 저장소 소스를 기준으로 pyupbit에서 자주 쓰는 API를 한 번에 보기 쉽게 정리한 문서입니다.

---

## 1. 설치 및 시작

```bash
pip install pyupbit
```

기본 import 예시:

```python
import pyupbit
```

거래 API를 사용할 때는 `Upbit(access, secret)` 객체를 생성합니다.

```python
import pyupbit

access = "YOUR_ACCESS_KEY"
secret = "YOUR_SECRET_KEY"

upbit = pyupbit.Upbit(access, secret)
```

---

## 2. 전체 구조

pyupbit는 크게 두 영역으로 나뉩니다.

- **QUOTATION API**
  - 시세 조회용
  - 별도 API 키 없이 사용 가능
- **EXCHANGE API**
  - 주문 / 잔고 / 입출금 / 자산 조회용
  - 업비트 API 키 필요

---

## 3. QUOTATION API 정리

### 3.1 `get_tickers()`
업비트 마켓 코드를 조회합니다.

```python
pyupbit.get_tickers(fiat="", is_details=False, limit_info=False, verbose=False)
```

주요 파라미터

- `fiat`: `"KRW"`, `"BTC"`, `"USDT"` 등 마켓 필터
- `is_details`: 상세 정보 포함 여부
- `limit_info`: 요청 제한 정보 포함 여부
- `verbose`: 상세 응답 유지 여부

예시

```python
import pyupbit

all_tickers = pyupbit.get_tickers()
krw_tickers = pyupbit.get_tickers("KRW")
btc_tickers = pyupbit.get_tickers("BTC")
usdt_tickers = pyupbit.get_tickers("USDT")
```

반환

- 기본: `list[str]`
- `is_details=True` 또는 `verbose=True`: 상세 딕셔너리 목록
- `limit_info=True`: `(data, remaining_req)` 형태

---

### 3.2 `get_current_price()`
현재가를 조회합니다.

```python
pyupbit.get_current_price(ticker="KRW-BTC", limit_info=False, verbose=False)
```

주요 파라미터

- `ticker`: 단일 티커 문자열 또는 티커 리스트
- `limit_info`: 요청 제한 정보 포함 여부
- `verbose`: 원본 응답 유지 여부

예시

```python
import pyupbit

price = pyupbit.get_current_price("KRW-BTC")
prices = pyupbit.get_current_price(["KRW-BTC", "KRW-XRP"])
```

반환

- 단일 티커: `float`
- 여러 티커: `dict[str, float]`
- `verbose=True`: 원본 ticker 응답

주의

- 문서 예시는 한 번에 여러 종목도 조회 가능하다고 설명합니다.
- 저장소 소스 기준으로는 내부에서 다중 티커를 청크 단위로 잘라 처리합니다.

---

### 3.3 `get_ohlcv()`
OHLCV(시가, 고가, 저가, 종가, 거래량, 거래대금)를 `DataFrame`으로 반환합니다.

```python
pyupbit.get_ohlcv(
    ticker="KRW-BTC",
    interval="day",
    count=200,
    to=None,
    period=0.1
)
```

주요 파라미터

- `ticker`: 예) `"KRW-BTC"`
- `interval`: 조회 단위
- `count`: 조회 개수
- `to`: 특정 시점 이전까지 조회
- `period`: 200개 초과 요청 시 요청 간격(초)

지원 interval

- `day`
- `minute1`
- `minute3`
- `minute5`
- `minute10`
- `minute15`
- `minute30`
- `minute60`
- `minute240`
- `week`
- `month`

예시

```python
import pyupbit

df_day = pyupbit.get_ohlcv("KRW-BTC", interval="day")
df_min1 = pyupbit.get_ohlcv("KRW-BTC", interval="minute1")
df_week = pyupbit.get_ohlcv("KRW-BTC", interval="week")
df_10 = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=10)
df_old = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", to="20201010")
```

반환 컬럼

- `open`
- `high`
- `low`
- `close`
- `volume`
- `value`

주의

- 기본 조회 개수는 200개입니다.
- 200개를 초과해서 가져올 때는 내부적으로 200개씩 끊어서 요청합니다.
- 이때 `period`로 추가 요청 간격을 조정할 수 있습니다.

---

### 3.4 `get_ohlcv_from()`
시작 시점부터 OHLCV를 수집하는 보조 함수입니다. 공식 문서 메인 페이지에서는 크게 강조되지 않지만 저장소 소스에 공개 함수로 포함되어 있습니다.

```python
pyupbit.get_ohlcv_from(
    ticker="KRW-BTC",
    interval="day",
    fromDatetime=None,
    to=None,
    period=0.1
)
```

예시

```python
df = pyupbit.get_ohlcv_from(
    ticker="KRW-BTC",
    interval="day",
    fromDatetime="2024-01-01 00:00:00"
)
```

용도

- 특정 시작 시점부터 현재까지 데이터를 누적 조회하고 싶을 때 사용

---

### 3.5 `get_daily_ohlcv_from_base()`
기준 시각을 이동한 일봉 데이터를 계산합니다.

```python
pyupbit.get_daily_ohlcv_from_base(ticker="KRW-BTC", base=0)
```

예시

```python
import pyupbit

df_base12 = pyupbit.get_daily_ohlcv_from_base("KRW-BTC", base=12)
df_base13 = pyupbit.get_daily_ohlcv_from_base("KRW-BTC", base=13)
```

설명

- 일반 일봉 대신, 특정 시각 기준으로 하루를 나눈 일봉을 만들 때 유용합니다.

---

### 3.6 `get_orderbook()`
호가 정보를 조회합니다.

```python
pyupbit.get_orderbook(ticker="KRW-BTC", limit_info=False)
```

주요 파라미터

- `ticker`: 단일 티커 또는 티커 리스트
- `limit_info`: 요청 제한 정보 포함 여부

예시

```python
import pyupbit

orderbook = pyupbit.get_orderbook("KRW-BTC")
orderbooks = pyupbit.get_orderbook(["KRW-BTC", "KRW-XRP"])
```

주요 응답 필드

- `market`
- `timestamp`
- `total_ask_size`
- `total_bid_size`
- `orderbook_units`
  - `ask_price`
  - `bid_price`
  - `ask_size`
  - `bid_size`

---

### 3.7 시세 체결 / 웹소켓
공식 문서 목차에는 체결 조회, 티커 조회, 오더북 조회 섹션이 보이며, 저장소 README에는 웹소켓 사용 예시가 포함되어 있습니다.

#### `WebSocketManager`
```python
from pyupbit import WebSocketManager

if __name__ == "__main__":
    wm = WebSocketManager("ticker", ["KRW-BTC"])
    for _ in range(10):
        data = wm.get()
        print(data)
    wm.terminate()
```

#### `WebSocketClient`
```python
import multiprocessing as mp
import pyupbit

if __name__ == "__main__":
    queue = mp.Queue()
    proc = mp.Process(
        target=pyupbit.WebSocketClient,
        args=("ticker", ["KRW-BTC"], queue),
        daemon=True
    )
    proc.start()

    while True:
        data = queue.get()
        print(data)
```

웹소켓 첫 번째 인자 타입

- `"ticker"`
- `"orderbook"`
- `"transaction"`

주의

- README 기준 현재 버전 예시는 원화 시장 티커 중심으로 설명됩니다.
- `if __name__ == "__main__":` 가드 사용이 권장됩니다.

---

## 4. EXCHANGE API 정리

### 4.1 로그인 객체 생성

```python
import pyupbit

access = "YOUR_ACCESS_KEY"
secret = "YOUR_SECRET_KEY"

upbit = pyupbit.Upbit(access, secret)
```

---

### 4.2 자산 조회

#### `get_balances()`
전체 계좌 잔고를 조회합니다.

```python
upbit.get_balances(contain_req=False)
```

반환

- 보유 자산 목록
- 각 항목은 보통 아래 필드를 포함
  - `currency`
  - `balance`
  - `locked`
  - `avg_buy_price`
  - `avg_buy_price_modified`
  - `unit_currency`

---

#### `get_balance()`
특정 자산의 사용 가능한 잔고를 조회합니다.

```python
upbit.get_balance(ticker="KRW", verbose=False, contain_req=False)
```

예시

```python
upbit.get_balance("KRW")
upbit.get_balance("KRW-BTC")
```

---

#### `get_balance_t()`
특정 자산의 `balance + locked` 값을 조회합니다.

```python
upbit.get_balance_t(ticker="KRW", contain_req=False)
```

---

#### `get_avg_buy_price()`
특정 자산의 평균 매수가를 조회합니다.

```python
upbit.get_avg_buy_price(ticker="KRW", contain_req=False)
```

---

#### `get_amount()`
특정 자산 또는 전체 자산(`ALL`) 기준 매수 금액을 계산합니다.

```python
upbit.get_amount(ticker, contain_req=False)
```

예시

```python
upbit.get_amount("KRW-BTC")
upbit.get_amount("ALL")
```

---

### 4.3 주문 관련

#### `get_chance()`
마켓별 주문 가능 정보를 조회합니다.

```python
upbit.get_chance(ticker, contain_req=False)
```

예시

```python
upbit.get_chance("KRW-BTC")
```

---

#### `get_order()`
주문 리스트를 조회합니다.

```python
upbit.get_order(ticker_or_uuid, state="wait", page=1, limit=100, contain_req=False)
```

설명

- 티커를 넣으면 해당 마켓의 주문 목록을 조회
- UUID를 넣으면 특정 주문 조회로 동작
- `state` 예시: `wait`, `watch`, `done`, `cancel`

예시

```python
upbit.get_order("KRW-LTC")
upbit.get_order("KRW-LTC", state="done")
upbit.get_order("ORDER_UUID")
```

---

#### `get_individual_order()`
UUID로 개별 주문 상세를 조회합니다.

```python
upbit.get_individual_order(uuid, contain_req=False)
```

---

#### `cancel_order()`
주문 UUID로 주문을 취소합니다.

```python
upbit.cancel_order(uuid, contain_req=False)
```

예시

```python
upbit.cancel_order("ORDER_UUID")
```

---

#### `buy_limit_order()`
지정가 매수 주문입니다.

```python
upbit.buy_limit_order(ticker, price, volume, contain_req=False)
```

예시

```python
upbit.buy_limit_order("KRW-XRP", 613, 10)
```

---

#### `sell_limit_order()`
지정가 매도 주문입니다.

```python
upbit.sell_limit_order(ticker, price, volume, contain_req=False)
```

예시

```python
upbit.sell_limit_order("KRW-XRP", 600, 20)
```

---

#### `buy_market_order()`
시장가 매수 주문입니다.

```python
upbit.buy_market_order(ticker, price, contain_req=False)
```

설명

- `price`는 매수 금액(KRW 기준)
- README 예시 기준 수수료 제외 금액으로 입력

예시

```python
upbit.buy_market_order("KRW-XRP", 10000)
```

---

#### `sell_market_order()`
시장가 매도 주문입니다.

```python
upbit.sell_market_order(ticker, volume, contain_req=False)
```

예시

```python
upbit.sell_market_order("KRW-XRP", 30)
```

---

### 4.4 출금 관련

#### `get_withdraw_list()`
출금 목록을 조회합니다.

```python
upbit.get_withdraw_list(currency, contain_req=False)
```

예시

```python
upbit.get_withdraw_list("KRW")
```

---

#### `get_individual_withdraw_order()`
개별 출금 건을 조회합니다.

```python
upbit.get_individual_withdraw_order(uuid, currency, contain_req=False)
```

---

#### `withdraw_coin()`
코인 출금을 요청합니다.

```python
upbit.withdraw_coin(
    currency,
    amount,
    address,
    secondary_address="None",
    transaction_type="default",
    contain_req=False
)
```

---

#### `withdraw_cash()`
원화 출금을 요청합니다.

```python
upbit.withdraw_cash(amount, contain_req=False)
```

---

### 4.5 입금 관련

#### `get_deposit_list()`
입금 목록을 조회합니다.

```python
upbit.get_deposit_list(currency, contain_req=False)
```

---

#### `get_individual_deposit_order()`
개별 입금 건을 조회합니다.

```python
upbit.get_individual_deposit_order(uuid, currency, contain_req=False)
```

---

#### 문서 목차에는 있지만 현재 소스에서 공개 함수 확인이 어려운 항목
공식 문서의 EXCHANGE API 목차에는 아래 항목도 보입니다.

- 입금 주소 생성 요청
- 전체 입금 주소 조회
- 개별 입금 주소 조회
- 원화 입금하기

다만 현재 확인한 저장소 `exchange_api.py` 공개 메서드 목록에서는 위 항목에 대응하는 함수명이 명확히 드러나지 않았습니다.  
그래서 실제 사용 전에는 최신 저장소 코드나 업비트 공식 REST API 스펙을 함께 확인하는 것이 안전합니다.

---

### 4.6 서비스 정보

#### `get_deposit_withdraw_status()`
입출금 상태를 조회합니다.

```python
upbit.get_deposit_withdraw_status(contain_req=False)
```

---

#### `get_api_key_list()`
API 키 목록과 만료 정보를 조회합니다.

```python
upbit.get_api_key_list(contain_req=False)
```

---

## 5. 요청 제한 정리

### QUOTATION API
- WebSocket 연결 요청: 초당 5회, 분당 100회
- 종목 / 캔들 / 체결 / 티커 / 호가 API: 초당 10회, 분당 600회

### EXCHANGE API
- 주문 요청: 초당 8회, 분당 200회
- 주문 외 요청: 초당 30회, 분당 900회

---

## 6. 실무에서 많이 쓰는 조합

### 현재가 조회
```python
import pyupbit

price = pyupbit.get_current_price("KRW-BTC")
print(price)
```

### 티커 목록 조회
```python
import pyupbit

tickers = pyupbit.get_tickers("KRW")
print(tickers[:10])
```

### 캔들 조회
```python
import pyupbit

df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=200)
print(df.tail())
```

### 로그인 후 잔고 조회
```python
import pyupbit

upbit = pyupbit.Upbit(access, secret)
print(upbit.get_balances())
print(upbit.get_balance("KRW"))
```

### 지정가 주문
```python
upbit.buy_limit_order("KRW-XRP", 613, 10)
upbit.sell_limit_order("KRW-XRP", 700, 10)
```

### 시장가 주문
```python
upbit.buy_market_order("KRW-XRP", 10000)
upbit.sell_market_order("KRW-XRP", 30)
```

---

## 7. 빠르게 보기 위한 함수 목록

### QUOTATION API
- `get_tickers()`
- `get_current_price()`
- `get_ohlcv()`
- `get_ohlcv_from()`
- `get_daily_ohlcv_from_base()`
- `get_orderbook()`
- `WebSocketManager`
- `WebSocketClient`

### EXCHANGE API
- `Upbit(access, secret)`
- `get_balances()`
- `get_balance()`
- `get_balance_t()`
- `get_avg_buy_price()`
- `get_amount()`
- `get_chance()`
- `get_order()`
- `get_individual_order()`
- `cancel_order()`
- `buy_limit_order()`
- `sell_limit_order()`
- `buy_market_order()`
- `sell_market_order()`
- `get_withdraw_list()`
- `get_individual_withdraw_order()`
- `withdraw_coin()`
- `withdraw_cash()`
- `get_deposit_list()`
- `get_individual_deposit_order()`
- `get_deposit_withdraw_status()`
- `get_api_key_list()`

---

## 8. 참고
정리 기준

- pyupbit 공식 문서:
  - Quickstart
  - QUOTATION API
  - EXCHANGE API
- pyupbit 저장소 README
- pyupbit 저장소의 `quotation_api.py`, `exchange_api.py`

문서 페이지에는 섹션 제목만 있고 상세 예시가 비어 있는 부분이 있어, 실제 함수명과 시그니처는 저장소 소스를 함께 참고해 보완했습니다.
