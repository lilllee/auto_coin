
# Upbit API 상세 정리 (Request / Response 포함)

> 기준: 업비트 공식 문서(v1.6.2)와 공개 REST/WebSocket 예시를 바탕으로 재구성한 개발용 정리본  
> 목적: "어떤 API를 어떤 형식으로 호출하고, 어떤 모양의 응답을 받는지"를 한 파일에서 빠르게 파악하기 위한 문서  
> 주의: Private API의 응답 예시는 **공식 문서의 응답 필드 설명 + 예시 스니펫**을 기준으로 재구성한 샘플이다. 실제 계정 상태/주문 상태에 따라 필드는 달라질 수 있다.

---

## 0. 공통

### 0-1. API 분류
- **Quotation API**
  - 인증 없이 시세 조회 가능
  - REST + WebSocket 제공
- **Exchange API**
  - API Key + JWT 인증 필요
  - 주문/잔고/입출금/서비스 정보 조회

### 0-2. 기본 Base URL
```text
REST: https://api.upbit.com
WebSocket Public: wss://api.upbit.com/websocket/v1
WebSocket Private: wss://api.upbit.com/websocket/v1/private
```

### 0-3. 인증 헤더
```http
Authorization: Bearer {JWT_TOKEN}
Content-Type: application/json
Accept: application/json
```

### 0-4. JWT Payload 예시
- 파라미터/Body 없는 경우
```json
{
  "access_key": "YOUR_ACCESS_KEY",
  "nonce": "UUID"
}
```

- Query 또는 Body 있는 경우
```json
{
  "access_key": "YOUR_ACCESS_KEY",
  "nonce": "UUID",
  "query_hash": "SHA512_HEX",
  "query_hash_alg": "SHA512"
}
```

### 0-5. Python 인증 예시
```python
import uuid
import hashlib
import jwt
from urllib.parse import urlencode

ACCESS_KEY = "YOUR_ACCESS_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"

def build_token(params=None):
    payload = {
        "access_key": ACCESS_KEY,
        "nonce": str(uuid.uuid4()),
    }

    if params:
        query_string = urlencode(params, doseq=True)
        query_hash = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
        payload["query_hash"] = query_hash
        payload["query_hash_alg"] = "SHA512"

    token = jwt.encode(payload, SECRET_KEY, algorithm="HS512")
    return token

headers = {
    "Authorization": f"Bearer {build_token()}",
    "Accept": "application/json",
}
```

### 0-6. Remaining-Req 헤더 예시
```text
Remaining-Req: group=default; min=1800; sec=29
```

- `group`: rate limit group
- `min`: deprecated, 무시
- `sec`: 현재 초당 잔여 요청 수

### 0-7. 자주 쓰는 권한 그룹
- 자산조회
- 주문하기
- 주문조회
- 출금하기
- 출금조회
- 입금조회

---

# 1. QUOTATION API

---

## 1-1. 페어 목록 조회

- **Method**: `GET`
- **URL**: `/v1/market/all`
- **인증**: 불필요
- **Rate Limit**: 마켓 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-trading-pairs

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `is_details` | boolean |  | 상세 정보 포함 여부 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/market/all?isDetails=false' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "korean_name": "비트코인",
    "english_name": "Bitcoin"
  },
  {
    "market": "KRW-ETH",
    "korean_name": "이더리움",
    "english_name": "Ethereum"
  }
]
```

### 핵심 필드
- `market`: 거래 페어 코드
- `korean_name`: 한글 종목명
- `english_name`: 영문 종목명

---

## 1-2. 초(Second) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/seconds`
- **인증**: 불필요
- **Rate Limit**: 캔들 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-candles-seconds

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 예: `KRW-BTC` |
| `to` | string |  | 기준 시각 |
| `count` | integer |  | 기본 1 |
| `unit` | integer |  | 초 단위 폭 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/seconds?market=KRW-BTC&count=1' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-06-30T23:59:59",
    "candle_date_time_kst": "2025-07-01T08:59:59",
    "opening_price": 145794000,
    "high_price": 145800000,
    "low_price": 145750000,
    "trade_price": 145759000,
    "timestamp": 1751327999000,
    "candle_acc_trade_price": 123456789.12,
    "candle_acc_trade_volume": 0.8451
  }
]
```

### 구현 메모
- 초 캔들은 **최근 3개월 이내** 데이터만 제공
- 체결이 없으면 해당 시각의 캔들은 생성되지 않음

---

## 1-3. 분(Minute) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/minutes/{unit}`
- **인증**: 불필요
- **Rate Limit**: 캔들 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-candles-minutes

### Path Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `unit` | int | Y | `1,3,5,10,15,30,60,240` |

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 예: `KRW-BTC` |
| `to` | string |  | 기준 시각 |
| `count` | integer |  | 기본 1 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/minutes/1?market=KRW-BTC&count=1' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-07-01T12:00:00",
    "candle_date_time_kst": "2025-07-01T21:00:00",
    "opening_price": 145800000,
    "high_price": 145820000,
    "low_price": 145790000,
    "trade_price": 145810000,
    "timestamp": 1751371200000,
    "candle_acc_trade_price": 587654321.12,
    "candle_acc_trade_volume": 4.0312,
    "unit": 1
  }
]
```

---

## 1-4. 일(Day) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/days`
- **인증**: 불필요
- **Rate Limit**: 캔들 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-candles-days

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 예: `KRW-BTC` |
| `to` | string |  | 기준 시각 |
| `count` | integer |  | 기본 1 |
| `converting_price_unit` | string |  | 예: `KRW` |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/days?market=KRW-BTC&count=1' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-07-01T00:00:00",
    "candle_date_time_kst": "2025-07-01T09:00:00",
    "opening_price": 145000000,
    "high_price": 146000000,
    "low_price": 144500000,
    "trade_price": 145800000,
    "prev_closing_price": 144900000,
    "change_price": 900000,
    "change_rate": 0.006211,
    "timestamp": 1751371200000,
    "candle_acc_trade_price": 9876543210.12,
    "candle_acc_trade_volume": 67.1234
  }
]
```

### 구현 메모
- `change_rate = (trade_price - prev_closing_price) / prev_closing_price`
- BTC 마켓 등의 일봉에서 `converting_price_unit=KRW` 사용 시 `converted_trade_price` 반환 가능

---

## 1-5. 주(Week) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/weeks`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-candles-weeks

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/weeks?market=KRW-BTC&count=1'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-06-30T00:00:00",
    "candle_date_time_kst": "2025-06-30T09:00:00",
    "opening_price": 140000000,
    "high_price": 146000000,
    "low_price": 139500000,
    "trade_price": 145800000,
    "timestamp": 1751371200000,
    "candle_acc_trade_price": 54321098765.43,
    "candle_acc_trade_volume": 350.1122
  }
]
```

---

## 1-6. 월(Month) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/months`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-candles-months

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/months?market=KRW-BTC&count=1'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-07-01T00:00:00",
    "candle_date_time_kst": "2025-07-01T09:00:00",
    "opening_price": 135000000,
    "high_price": 146000000,
    "low_price": 132000000,
    "trade_price": 145800000,
    "timestamp": 1751371200000,
    "candle_acc_trade_price": 210987654321.98,
    "candle_acc_trade_volume": 1450.2244
  }
]
```

---

## 1-7. 연(Year) 캔들 조회

- **Method**: `GET`
- **URL**: `/v1/candles/years`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-candles-years

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/candles/years?market=KRW-BTC&count=1'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "candle_date_time_utc": "2025-01-01T00:00:00",
    "candle_date_time_kst": "2025-01-01T09:00:00",
    "opening_price": 92000000,
    "high_price": 146000000,
    "low_price": 90000000,
    "trade_price": 145800000,
    "timestamp": 1751371200000,
    "candle_acc_trade_price": 1234567890123.45,
    "candle_acc_trade_volume": 9876.5432
  }
]
```

---

## 1-8. 페어 체결 이력 조회

- **Method**: `GET`
- **URL**: `/v1/trades/ticks`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-pair-trades

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 예: `KRW-BTC` |
| `to` | string |  | 기준 체결 ID/시각 |
| `count` | integer |  | 조회 개수 |
| `cursor` | string |  | 다음 페이지 커서 |
| `daysAgo` | integer |  | 과거 일자 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/trades/ticks?market=KRW-BTC&count=1' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "trade_date_utc": "2025-07-01",
    "trade_time_utc": "12:34:56",
    "timestamp": 1751373296000,
    "trade_price": 145810000,
    "trade_volume": 0.0025,
    "prev_closing_price": 144900000,
    "change_price": 910000,
    "ask_bid": "BID",
    "sequential_id": 1751373296000000
  }
]
```

---

## 1-9. 페어 단위 현재가 조회

- **Method**: `GET`
- **URL**: `/v1/ticker`
- **인증**: 불필요
- **Rate Limit**: 현재가 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-tickers

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `markets` | string | Y | 쉼표로 여러 종목 지정 가능 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "trade_date": "20250704",
    "trade_time": "051400",
    "trade_date_kst": "20250704",
    "trade_time_kst": "141400",
    "trade_timestamp": 1751606040000,
    "opening_price": 144900000,
    "high_price": 146200000,
    "low_price": 144300000,
    "trade_price": 145810000,
    "prev_closing_price": 144900000,
    "change": "RISE",
    "change_price": 910000,
    "change_rate": 0.00628019,
    "signed_change_price": 910000,
    "signed_change_rate": 0.00628019,
    "trade_volume": 0.0012,
    "acc_trade_price": 9876543210.12,
    "acc_trade_price_24h": 12345678901.23,
    "acc_trade_volume": 67.12345,
    "acc_trade_volume_24h": 81.56789,
    "highest_52_week_price": 160000000,
    "highest_52_week_date": "2025-03-14",
    "lowest_52_week_price": 85000000,
    "lowest_52_week_date": "2024-08-05",
    "timestamp": 1751606040123
  }
]
```

### 구현 메모
- `change`, `change_price`, `change_rate`는 전일 종가 기준
- 여러 종목을 한 번에 조회 가능

---

## 1-10. 마켓 단위 현재가 조회

- **Method**: `GET`
- **URL**: `/v1/ticker/all`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-quote-tickers

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `quote_currencies` | string | Y | 예: `KRW` |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/ticker/all?quote_currencies=KRW'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "trade_price": 145810000,
    "change": "RISE",
    "timestamp": 1751606040123
  },
  {
    "market": "KRW-ETH",
    "trade_price": 5230000,
    "change": "FALL",
    "timestamp": 1751606040123
  }
]
```

---

## 1-11. 호가 조회

- **Method**: `GET`
- **URL**: `/v1/orderbook`
- **인증**: 불필요
- **Rate Limit**: 호가 그룹, 초당 10회
- **문서**: https://docs.upbit.com/kr/reference/list-orderbooks

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `markets` | string | Y | 예: `KRW-BTC` |
| `level` | string |  | 호가 모아보기 단위, 기본 `0` |
| `count` | integer |  | 기본 `30`, 최대 30호가 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orderbook?markets=KRW-BTC&level=0&count=15' \
  --header 'accept: application/json'
```

### Response 예시
```json
[
  {
    "market": "KRW-BTC",
    "timestamp": 1751606040123,
    "total_ask_size": 12.3456,
    "total_bid_size": 10.9876,
    "orderbook_units": [
      {
        "ask_price": 148520000,
        "bid_price": 148510000,
        "ask_size": 0.321,
        "bid_size": 0.456
      },
      {
        "ask_price": 148530000,
        "bid_price": 148500000,
        "ask_size": 0.111,
        "bid_size": 0.222
      }
    ],
    "level": 0
  }
]
```

---

## 1-12. 호가 정책 조회

- **Method**: `GET`
- **URL**: `/v1/orderbook/supported_levels`
- **인증**: 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-orderbook-instruments

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orderbook/supported_levels?market=KRW-BTC'
```

### Response 예시
```json
{
  "market": "KRW-BTC",
  "supported_levels": [0, 1000, 5000, 10000, 50000]
}
```

---

# 2. EXCHANGE API

---

## 2-1. 계정 잔고 조회

- **Method**: `GET`
- **URL**: `/v1/accounts`
- **인증**: 필요
- **권한**: 자산조회
- **Rate Limit**: Exchange 기본 그룹, 초당 30회
- **문서**: https://docs.upbit.com/kr/reference/get-balance

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/accounts' \
  --header 'Authorization: Bearer {JWT}' \
  --header 'Accept: application/json'
```

### Response 예시
```json
[
  {
    "currency": "KRW",
    "balance": "1000000.0",
    "locked": "0.0",
    "avg_buy_price": "0",
    "avg_buy_price_modified": false,
    "unit_currency": "KRW"
  },
  {
    "currency": "BTC",
    "balance": "0.01000000",
    "locked": "0.00100000",
    "avg_buy_price": "95000000",
    "avg_buy_price_modified": false,
    "unit_currency": "KRW"
  }
]
```

### 핵심 필드
- `balance`: 주문 가능 수량
- `locked`: 주문 등에 묶인 수량
- `avg_buy_price`: 평균 매수 단가
- `unit_currency`: 기준 통화

---

## 2-2. 페어별 주문 가능 정보 조회

- **Method**: `GET`
- **URL**: `/v1/orders/chance`
- **인증**: 필요
- **권한**: 주문조회
- **Rate Limit**: Exchange 기본 그룹, 초당 30회
- **문서**: https://docs.upbit.com/kr/reference/available-order-information

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 예: `KRW-BTC` |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orders/chance?market=KRW-BTC' \
  --header 'Authorization: Bearer {JWT}' \
  --header 'Accept: application/json'
```

### Response 예시
```json
{
  "bid_fee": "0.0005",
  "ask_fee": "0.0005",
  "maker_bid_fee": "0.0002",
  "maker_ask_fee": "0.0002",
  "market": {
    "id": "KRW-BTC",
    "name": "BTC/KRW",
    "order_sides": ["ask", "bid"],
    "bid_types": ["limit", "price", "best"],
    "ask_types": ["limit", "market", "best"],
    "bid": {
      "currency": "KRW",
      "min_total": "5000"
    },
    "ask": {
      "currency": "BTC",
      "min_total": "5000"
    },
    "max_total": "1000000000"
  },
  "bid_account": {
    "currency": "KRW",
    "balance": "1000000.0",
    "locked": "0.0"
  },
  "ask_account": {
    "currency": "BTC",
    "balance": "0.01",
    "locked": "0.0"
  }
}
```

### 구현 메모
- 실주문 전에 이 API로 최소 주문 금액, 지원 주문 타입, 잔고 확인
- `market.order_types`는 deprecated, `bid_types` / `ask_types` 사용 권장

---

## 2-3. 주문 생성

- **Method**: `POST`
- **URL**: `/v1/orders`
- **인증**: 필요
- **권한**: 주문하기
- **Rate Limit**: 주문 그룹, 초당 8회
- **문서**: https://docs.upbit.com/kr/reference/new-order

### Body Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string | Y | 페어 코드 |
| `side` | string | Y | `ask` / `bid` |
| `volume` | string | 조건부 | 수량 |
| `price` | string | 조건부 | 가격 또는 총액 |
| `ord_type` | string | Y | `limit` / `price` / `market` / `best` |
| `identifier` | string |  | 사용자 지정 주문 ID |
| `time_in_force` | string |  | `fok` / `ioc` / `post_only` |
| `smp_type` | string |  | `cancel_maker` / `cancel_taker` / `reduce` |

### 2-3-1. 지정가 주문 Request 예시
```bash
curl --request POST \
  --url 'https://api.upbit.com/v1/orders' \
  --header 'Authorization: Bearer {JWT}' \
  --header 'Content-Type: application/json' \
  --data '{
    "market": "KRW-BTC",
    "side": "bid",
    "volume": "0.001",
    "price": "50000000",
    "ord_type": "limit"
  }'
```

### 2-3-2. 시장가 매수 Request 예시
```json
{
  "market": "KRW-BTC",
  "side": "bid",
  "price": "100000",
  "ord_type": "price"
}
```

### 2-3-3. 시장가 매도 Request 예시
```json
{
  "market": "KRW-BTC",
  "side": "ask",
  "volume": "0.001",
  "ord_type": "market"
}
```

### 2-3-4. 최유리지정가 Request 예시
```json
{
  "market": "KRW-BTC",
  "side": "bid",
  "price": "100000",
  "ord_type": "best",
  "time_in_force": "ioc"
}
```

### Response 예시
```json
{
  "uuid": "3b67e543-8ad3-48d0-8451-0dad315cae73",
  "side": "bid",
  "ord_type": "limit",
  "price": "50000000",
  "state": "wait",
  "market": "KRW-BTC",
  "created_at": "2025-07-04T14:14:00+09:00",
  "volume": "0.001",
  "remaining_volume": "0.001",
  "reserved_fee": "25",
  "remaining_fee": "25",
  "paid_fee": "0",
  "locked": "50025",
  "executed_volume": "0",
  "trades_count": 0,
  "identifier": "my-order-001"
}
```

### 구현 메모
- `post_only`는 `smp_type`과 같이 사용 불가
- 시장가 매수(`ord_type=price`)는 `volume` 미입력
- 시장가 매도(`ord_type=market`)는 `price` 미입력

---

## 2-4. 주문 생성 테스트

- **Method**: `POST`
- **URL**: `/v1/orders/test`
- **인증**: 필요
- **권한**: 주문하기
- **Rate Limit**: 주문 테스트 그룹, 초당 8회
- **문서**: https://docs.upbit.com/kr/reference/order-test

### 용도
- 실제 주문 없이 요청 형식과 주문 가능 상태 검증
- `market_offline` 같은 오류를 사전에 확인 가능

### Request 예시
```json
{
  "market": "KRW-BTC",
  "side": "bid",
  "volume": "0.001",
  "price": "50000000",
  "ord_type": "limit"
}
```

### Response 예시
```json
{
  "uuid": "test-order-uuid",
  "side": "bid",
  "ord_type": "limit",
  "price": "50000000",
  "state": "wait",
  "market": "KRW-BTC",
  "created_at": "2025-10-27T10:00:00+09:00",
  "volume": "0.001",
  "remaining_volume": "0.001"
}
```

> 주의: 테스트 응답의 UUID/identifier는 실제 주문 조회·취소에 사용 불가

---

## 2-5. 개별 주문 조회

- **Method**: `GET`
- **URL**: `/v1/order`
- **인증**: 필요
- **권한**: 주문조회
- **문서**: https://docs.upbit.com/kr/reference/get-order

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `uuid` | string | 조건부 | 주문 UUID |
| `identifier` | string | 조건부 | 사용자 지정 주문 ID |

> `uuid` 또는 `identifier` 중 하나는 반드시 필요  
> 둘 다 주면 `uuid` 기준 조회

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/order?uuid=3b67e543-8ad3-48d0-8451-0dad315cae73' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "market": "KRW-USDT",
  "uuid": "3b67e543-8ad3-48d0-8451-0dad315cae73",
  "side": "ask",
  "ord_type": "market",
  "state": "done",
  "price": null,
  "avg_price": "1380.15",
  "volume": "15.0",
  "remaining_volume": "0.0",
  "reserved_fee": "0.0",
  "remaining_fee": "0.0",
  "paid_fee": "10.35",
  "locked": "0.0",
  "executed_volume": "15.0",
  "trades_count": 1,
  "created_at": "2025-08-09T11:11:11+09:00"
}
```

---

## 2-6. id로 주문 목록 조회

- **Method**: `GET`
- **URL**: `/v1/orders/uuids`
- **인증**: 필요
- **권한**: 주문조회
- **문서**: https://docs.upbit.com/kr/reference/list-orders-by-ids

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `uuids[]` | array[string] |  | UUID 목록 |
| `identifiers[]` | array[string] |  | identifier 목록 |

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orders/uuids?uuids[]=uuid1&uuids[]=uuid2' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
[
  {
    "uuid": "uuid1",
    "side": "ask",
    "ord_type": "market",
    "state": "done",
    "market": "KRW-USDT"
  },
  {
    "uuid": "uuid2",
    "side": "bid",
    "ord_type": "limit",
    "state": "wait",
    "market": "KRW-BTC"
  }
]
```

---

## 2-7. 체결 대기 주문 목록 조회

- **Method**: `GET`
- **URL**: `/v1/orders/open`
- **인증**: 필요
- **권한**: 주문조회
- **문서**: https://docs.upbit.com/kr/reference/list-open-orders

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string |  | 특정 페어 필터 |
| `state` | string |  | `wait` / `watch` |
| `states[]` | array[string] |  | 다중 상태 |
| `page` | integer |  | 기본 1 |
| `limit` | integer |  | 기본 100 |
| `order_by` | string |  | 정렬 |

> `state`와 `states[]`는 동시에 사용 불가

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orders/open?market=KRW-BTC&state=wait&page=1&limit=50' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
[
  {
    "uuid": "open-order-uuid",
    "side": "bid",
    "ord_type": "limit",
    "price": "50000000",
    "state": "wait",
    "market": "KRW-BTC",
    "created_at": "2025-07-04T14:14:00+09:00",
    "volume": "0.001",
    "remaining_volume": "0.001",
    "reserved_fee": "25",
    "remaining_fee": "25",
    "paid_fee": "0",
    "locked": "50025",
    "executed_volume": "0",
    "trades_count": 0
  }
]
```

---

## 2-8. 종료 주문 목록 조회

- **Method**: `GET`
- **URL**: `/v1/orders/closed`
- **인증**: 필요
- **권한**: 주문조회
- **문서**: https://docs.upbit.com/kr/reference/list-closed-orders

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `market` | string |  | 특정 페어 필터 |
| `state` | string |  | `done,cancel` / `done` / `cancel` |
| `states[]` | array[string] |  | 다중 상태 |
| `start_time` | string |  | 조회 시작 시각 |
| `end_time` | string |  | 조회 종료 시각 |
| `limit` | integer |  | 기본 100 |
| `order_by` | string |  | `asc` / `desc` |

> 조회 기간(window)은 최대 7일  
> `state`와 `states[]`는 동시에 사용 불가

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/orders/closed?market=KRW-BTC&state=done&limit=20' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
[
  {
    "uuid": "closed-order-uuid",
    "side": "ask",
    "ord_type": "market",
    "state": "done",
    "market": "KRW-BTC",
    "created_at": "2025-07-04T10:00:00+09:00",
    "volume": "0.002",
    "remaining_volume": "0",
    "paid_fee": "145.8",
    "executed_volume": "0.002",
    "trades_count": 1
  }
]
```

---

## 2-9. 개별 주문 취소 접수

- **Method**: `DELETE`
- **URL**: `/v1/order`
- **인증**: 필요
- **권한**: 주문하기
- **문서**: https://docs.upbit.com/kr/reference/cancel-order

### Query Params
| 이름 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `uuid` | string | 조건부 | 주문 UUID |
| `identifier` | string | 조건부 | 사용자 지정 주문 ID |

### Request 예시
```bash
curl --request DELETE \
  --url 'https://api.upbit.com/v1/order?uuid=3b67e543-8ad3-48d0-8451-0dad315cae73' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "uuid": "3b67e543-8ad3-48d0-8451-0dad315cae73",
  "side": "bid",
  "ord_type": "limit",
  "price": "50000000",
  "state": "cancel",
  "market": "KRW-BTC",
  "created_at": "2025-07-04T14:14:00+09:00",
  "volume": "0.001",
  "remaining_volume": "0.001",
  "reserved_fee": "25",
  "remaining_fee": "25",
  "paid_fee": "0",
  "locked": "0",
  "executed_volume": "0",
  "trades_count": 0
}
```

---

## 2-10. id로 주문 목록 취소 접수

- **Method**: `DELETE`
- **URL**: `/v1/orders/uuids`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/cancel-orders-by-ids

### Request 예시
```json
{
  "uuids": ["uuid1", "uuid2"]
}
```

### Response 예시
```json
[
  {
    "uuid": "uuid1",
    "state": "cancel"
  },
  {
    "uuid": "uuid2",
    "state": "cancel"
  }
]
```

---

## 2-11. 주문 일괄 취소 접수

- **Method**: `DELETE`
- **URL**: `/v1/orders/open`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/batch-cancel-orders

### Request 예시
```json
{
  "market": "KRW-BTC",
  "side": "bid"
}
```

### Response 예시
```json
[
  {
    "uuid": "uuid1",
    "state": "cancel"
  },
  {
    "uuid": "uuid2",
    "state": "cancel"
  }
]
```

---

## 2-12. 취소 후 재주문

- **Method**: `POST`
- **URL**: `/v1/orders/cancel_replace`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/cancel-and-new-order

### Request 예시
```json
{
  "uuid": "old-order-uuid",
  "new_order": {
    "market": "KRW-BTC",
    "side": "bid",
    "price": "49000000",
    "volume": "0.001",
    "ord_type": "limit"
  }
}
```

### Response 예시
```json
{
  "canceled_order": {
    "uuid": "old-order-uuid",
    "state": "cancel"
  },
  "new_order": {
    "uuid": "new-order-uuid",
    "state": "wait",
    "market": "KRW-BTC"
  }
}
```

---

## 2-13. 출금 가능 정보 조회

- **Method**: `GET`
- **URL**: `/v1/withdraws/chance`
- **인증**: 필요
- **권한**: 출금조회
- **문서**: https://docs.upbit.com/kr/reference/available-withdrawal-information

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/withdraws/chance?currency=BTC' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "member_level": {
    "security_level": 4,
    "email_verified": true,
    "identity_auth_verified": true,
    "bank_account_verified": true,
    "wallet_locked": false
  },
  "currency": {
    "code": "BTC",
    "withdraw_fee": "0.0005",
    "is_coin": true
  },
  "account": {
    "currency": "BTC",
    "balance": "0.01",
    "locked": "0.0"
  },
  "withdraw_limit": {
    "minimum": "0.001",
    "onetime": "10",
    "daily": "20",
    "remaining_daily": "19.99"
  }
}
```

---

## 2-14. 출금 허용 주소 목록 조회

- **Method**: `GET`
- **URL**: `/v1/withdraws/coin_addresses`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/list-withdrawal-addresses

### Response 예시
```json
[
  {
    "currency": "BTC",
    "net_type": "BTC",
    "address": "bc1qxxxxxxxxxxxxxxxx",
    "secondary_address": null
  }
]
```

---

## 2-15. 디지털 자산 출금 요청

- **Method**: `POST`
- **URL**: `/v1/withdraws/coin`
- **인증**: 필요
- **권한**: 출금하기
- **문서**: https://docs.upbit.com/kr/reference/withdraw

### Request 예시
```json
{
  "currency": "BTC",
  "amount": "0.001",
  "address": "bc1qxxxxxxxxxxxxxxxx",
  "transaction_type": "default"
}
```

### Response 예시
```json
{
  "type": "withdraw",
  "uuid": "withdraw-uuid",
  "currency": "BTC",
  "net_type": "BTC",
  "txid": null,
  "state": "WAITING",
  "created_at": "2025-07-04T15:00:00+09:00",
  "amount": "0.001",
  "fee": "0.0005"
}
```

---

## 2-16. 원화 출금 요청

- **Method**: `POST`
- **URL**: `/v1/withdraws/krw`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/withdraw-krw

### Request 예시
```json
{
  "amount": "10000"
}
```

### Response 예시
```json
{
  "type": "withdraw",
  "uuid": "krw-withdraw-uuid",
  "currency": "KRW",
  "state": "WAITING",
  "created_at": "2025-07-04T15:10:00+09:00",
  "amount": "10000",
  "fee": "1000"
}
```

---

## 2-17. 개별 출금 조회

- **Method**: `GET`
- **URL**: `/v1/withdraw`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/get-withdrawal

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/withdraw?uuid=withdraw-uuid' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "type": "withdraw",
  "uuid": "withdraw-uuid",
  "currency": "BTC",
  "state": "DONE",
  "txid": "0xabc123...",
  "created_at": "2025-07-04T15:00:00+09:00",
  "done_at": "2025-07-04T15:03:00+09:00",
  "amount": "0.001",
  "fee": "0.0005"
}
```

---

## 2-18. 출금 목록 조회

- **Method**: `GET`
- **URL**: `/v1/withdraws`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/list-withdrawals

### Response 예시
```json
[
  {
    "uuid": "withdraw-uuid",
    "currency": "BTC",
    "state": "DONE",
    "amount": "0.001",
    "fee": "0.0005"
  }
]
```

---

## 2-19. 디지털 자산 출금 취소 요청

- **Method**: `DELETE`
- **URL**: `/v1/withdraw`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/cancel-withdrawal

### Request 예시
```bash
curl --request DELETE \
  --url 'https://api.upbit.com/v1/withdraw?uuid=withdraw-uuid' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "uuid": "withdraw-uuid",
  "state": "CANCELLED"
}
```

---

## 2-20. 디지털 자산 입금 가능 정보 조회

- **Method**: `GET`
- **URL**: `/v1/deposits/chance/coin`
- **인증**: 필요
- **권한**: 입금조회
- **문서**: https://docs.upbit.com/kr/reference/available-deposit-information

### Response 예시
```json
{
  "member_level": {
    "security_level": 4,
    "wallet_locked": false
  },
  "currency": {
    "code": "BTC",
    "is_coin": true,
    "wallet_state": "working"
  }
}
```

---

## 2-21. 입금 주소 생성 요청

- **Method**: `POST`
- **URL**: `/v1/deposits/generate_coin_address`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/create-deposit-address

### Request 예시
```json
{
  "currency": "BTC"
}
```

### Response 예시
```json
{
  "success": true,
  "currency": "BTC",
  "deposit_address": "bc1qxxxxxxxxxxxxxxxx",
  "secondary_address": null
}
```

---

## 2-22. 개별 입금 주소 조회

- **Method**: `GET`
- **URL**: `/v1/deposits/coin_address`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/get-deposit-address

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/deposits/coin_address?currency=BTC' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
{
  "currency": "BTC",
  "deposit_address": "bc1qxxxxxxxxxxxxxxxx",
  "secondary_address": null
}
```

---

## 2-23. 입금 주소 목록 조회

- **Method**: `GET`
- **URL**: `/v1/deposits/coin_addresses`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/list-deposit-addresses

### Response 예시
```json
[
  {
    "currency": "BTC",
    "deposit_address": "bc1qxxxxxxxxxxxxxxxx",
    "secondary_address": null
  }
]
```

---

## 2-24. 원화 입금

- **Method**: `POST`
- **URL**: `/v1/deposits/krw`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/deposit-krw

### Request 예시
```json
{
  "amount": "50000"
}
```

### Response 예시
```json
{
  "uuid": "krw-deposit-uuid",
  "currency": "KRW",
  "state": "PROCESSING",
  "amount": "50000",
  "created_at": "2025-07-04T16:00:00+09:00"
}
```

---

## 2-25. 개별 입금 조회

- **Method**: `GET`
- **URL**: `/v1/deposit`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/get-deposit

### Response 예시
```json
{
  "uuid": "deposit-uuid",
  "currency": "BTC",
  "state": "ACCEPTED",
  "txid": "0xdeposithash",
  "amount": "0.005",
  "created_at": "2025-07-04T12:00:00+09:00"
}
```

---

## 2-26. 입금 목록 조회

- **Method**: `GET`
- **URL**: `/v1/deposits`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/list-deposits

### Response 예시
```json
[
  {
    "uuid": "deposit-uuid",
    "currency": "BTC",
    "state": "ACCEPTED",
    "amount": "0.005"
  }
]
```

---

## 2-27. 계정주 확인 서비스 지원 거래소 목록 조회

- **Method**: `GET`
- **URL**: `/v1/travel_rule/vasps`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/list-travelrule-vasps

### Response 예시
```json
[
  {
    "vasp_name": "Binance",
    "vasp_uuid": "vasp-uuid-1"
  }
]
```

---

## 2-28. 입금 UUID로 계정주 검증 요청

- **Method**: `POST`
- **URL**: `/v1/travel_rule/deposit/uuid`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/verify-travelrule-by-uuid

### Request 예시
```json
{
  "vasp_uuid": "vasp-uuid-1",
  "deposit_uuid": "deposit-uuid"
}
```

### Response 예시
```json
{
  "verified": true,
  "owner_name": "HONG GILDONG"
}
```

---

## 2-29. 입금 TxID로 계정주 검증 요청

- **Method**: `POST`
- **URL**: `/v1/travel_rule/deposit/txid`
- **인증**: 필요
- **문서**: https://docs.upbit.com/kr/reference/verify-travelrule-by-txid

### Request 예시
```json
{
  "vasp_uuid": "vasp-uuid-1",
  "txid": "0xabc123"
}
```

### Response 예시
```json
{
  "verified": true,
  "owner_name": "HONG GILDONG"
}
```

---

## 2-30. 입출금 서비스 상태 조회

- **Method**: `GET`
- **URL**: `/v1/status/wallet`
- **인증**: 필요
- **권한**: 별도 권한 불필요
- **문서**: https://docs.upbit.com/kr/reference/get-service-status

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/status/wallet' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
[
  {
    "currency": "BTC",
    "wallet_state": "working",
    "block_state": "normal",
    "block_height": 850000,
    "block_updated_at": "2025-07-04T14:00:00+09:00"
  }
]
```

---

## 2-31. API Key 목록 조회

- **Method**: `GET`
- **URL**: `/v1/api_keys`
- **인증**: 필요
- **권한**: 별도 권한 불필요
- **문서**: https://docs.upbit.com/kr/reference/list-api-keys

### Request 예시
```bash
curl --request GET \
  --url 'https://api.upbit.com/v1/api_keys' \
  --header 'Authorization: Bearer {JWT}'
```

### Response 예시
```json
[
  {
    "access_key": "abcd134567890231bacbd",
    "expire_at": "2026-07-01T09:00:00+09:00"
  }
]
```

---

# 3. WEBSOCKET

---

## 3-1. Public 연결 예시

```javascript
const ws = new WebSocket("wss://api.upbit.com/websocket/v1");

ws.onopen = () => {
  ws.send(JSON.stringify([
    { ticket: "my-client-001" },
    { type: "ticker", codes: ["KRW-BTC", "KRW-ETH"] },
    { format: "DEFAULT" }
  ]));
};

ws.onmessage = (event) => {
  console.log(event.data);
};
```

---

## 3-2. Private 연결 예시

```javascript
const ws = new WebSocket("wss://api.upbit.com/websocket/v1/private", {
  headers: {
    Authorization: `Bearer ${JWT_TOKEN}`
  }
});
```

---

## 3-3. 현재가 (Ticker)

- **타입**: `ticker`
- **연결**: Public
- **문서**: https://docs.upbit.com/kr/reference/websocket-ticker

### 구독 Request 예시
```json
[
  { "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49" },
  { "type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"] },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "ticker",
  "code": "KRW-BTC",
  "opening_price": 144900000,
  "high_price": 146200000,
  "low_price": 144300000,
  "trade_price": 145810000,
  "prev_closing_price": 144900000,
  "change": "RISE",
  "change_price": 910000,
  "signed_change_rate": 0.00628019,
  "acc_trade_price": 9876543210.12,
  "acc_trade_volume": 67.12345,
  "trade_timestamp": 1751606040123,
  "stream_type": "REALTIME"
}
```

---

## 3-4. 체결 (Trade)

- **타입**: `trade`
- **연결**: Public
- **문서**: https://docs.upbit.com/kr/reference/websocket-trade

### 구독 Request 예시
```json
[
  { "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49" },
  { "type": "trade", "codes": ["KRW-BTC", "KRW-ETH"] },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "trade",
  "code": "KRW-BTC",
  "trade_price": 145810000,
  "trade_volume": 0.0012,
  "ask_bid": "BID",
  "prev_closing_price": 144900000,
  "change": "RISE",
  "change_price": 910000,
  "trade_timestamp": 1751606040123,
  "sequential_id": 1751606040123000,
  "stream_type": "REALTIME"
}
```

---

## 3-5. 호가 (Orderbook)

- **타입**: `orderbook`
- **연결**: Public
- **문서**: https://docs.upbit.com/kr/reference/websocket-orderbook

### 구독 Request 예시
```json
[
  { "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49" },
  { "type": "orderbook", "codes": ["KRW-BTC"], "level": 10000 },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "orderbook",
  "code": "KRW-BTC",
  "total_ask_size": 12.3456,
  "total_bid_size": 10.9876,
  "orderbook_units": [
    {
      "ask_price": 148520000,
      "bid_price": 148510000,
      "ask_size": 0.321,
      "bid_size": 0.456
    }
  ],
  "timestamp": 1751606040123,
  "level": 10000,
  "stream_type": "REALTIME"
}
```

---

## 3-6. 캔들 (Candle)

- **타입**: `candle.1s`, `candle.1m`, `candle.3m` ...
- **연결**: Public
- **문서**: https://docs.upbit.com/kr/reference/websocket-candle

### 구독 Request 예시
```json
[
  { "ticket": "my-candle-client" },
  { "type": "candle.1s", "codes": ["KRW-BTC"] },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "candle.1s",
  "code": "KRW-BTC",
  "candle_date_time_utc": "2025-01-02T04:28:05",
  "candle_date_time_kst": "2025-01-02T13:28:05",
  "opening_price": 142009000.0,
  "high_price": 142009000.0,
  "low_price": 142009000.0,
  "trade_price": 142009000.0,
  "candle_acc_trade_volume": 0.00606119,
  "candle_acc_trade_price": 860743.53071,
  "timestamp": 1735792085824,
  "stream_type": "REALTIME"
}
```

---

## 3-7. 내 주문 및 체결 (MyOrder)

- **타입**: `myOrder`
- **연결**: Private
- **권한**: 주문조회
- **문서**: https://docs.upbit.com/kr/reference/websocket-myorder

### 구독 Request 예시
```json
[
  { "ticket": "private-order-client" },
  { "type": "myOrder" },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "myOrder",
  "code": "KRW-BTC",
  "uuid": "ac2dc2a3-fce9-40a2-a4f6-5987c25c438f",
  "ask_bid": "BID",
  "order_type": "limit",
  "state": "trade",
  "trade_uuid": "68315169-fba4-4175-ade3-aff14a616657",
  "price": 0.001453,
  "avg_price": 0.00145372,
  "volume": 30925891.29839369,
  "remaining_volume": 29968038.09235948,
  "executed_volume": 30925891.29839369,
  "trades_count": 1,
  "reserved_fee": 44.23943970238218,
  "timestamp": 1710146517267,
  "stream_type": "REALTIME"
}
```

---

## 3-8. 내 자산 (MyAsset)

- **타입**: `myAsset`
- **연결**: Private
- **권한**: 자산조회
- **문서**: https://docs.upbit.com/kr/reference/websocket-myasset

### 구독 Request 예시
```json
[
  { "ticket": "private-asset-client" },
  { "type": "myAsset" },
  { "format": "DEFAULT" }
]
```

### Response 예시
```json
{
  "type": "myAsset",
  "asset_uuid": "e635f223-1609-4969-8fb6-4376937baad6",
  "assets": [
    {
      "currency": "KRW",
      "balance": 1386929.3723106677,
      "locked": 10329.670127489598
    }
  ],
  "asset_timestamp": 1710146517259,
  "timestamp": 1710146517267,
  "stream_type": "REALTIME"
}
```

---

## 3-9. 구독 중인 스트림 목록 조회

- **타입**: `list_subscriptions`
- **연결**: Public / Private
- **문서**: https://docs.upbit.com/kr/reference/list-subscriptions

### Request 예시
```json
[
  { "ticket": "client-001" },
  { "type": "list_subscriptions" }
]
```

### Response 예시
```json
[
  {
    "type": "ticker",
    "codes": ["KRW-BTC", "KRW-ETH"]
  },
  {
    "type": "orderbook",
    "codes": ["KRW-BTC"]
  }
]
```

---

# 4. Deprecated

## 4-1. 호가 모아보기 단위 조회 (Deprecated)

- **Method**: `GET`
- **URL**: `/v1/orderbook/supported_levels`
- **문서**: https://docs.upbit.com/kr/reference/list-orderbook-levels

> 현재는 호가 정책 조회 문서를 우선 참조

---

# 5. 실전 구현 포인트

## 5-1. 현재가 반응 전략에 꼭 필요한 최소 API
1. `GET /v1/ticker`
2. `GET /v1/orderbook`
3. `GET /v1/orders/chance`
4. `POST /v1/orders`
5. `GET /v1/order`
6. `DELETE /v1/order`
7. WebSocket `ticker`
8. WebSocket `trade`
9. WebSocket `orderbook`
10. Private WebSocket `myOrder`

## 5-2. 추천 호출 흐름
```text
1) 시작 시 market/all 로 거래 대상 로드
2) ticker + orderbook WebSocket 구독
3) 진입 전 orders/chance 로 잔고/최소주문/지원 타입 확인
4) orders 로 주문 생성
5) myOrder 또는 GET /order 로 체결 추적
6) 필요 시 DELETE /order 로 취소
7) accounts / myAsset 으로 잔고 동기화
```

## 5-3. 운영 시 주의
- REST만으로 실시간 추적하면 느리다
- 시세 감지는 WebSocket, 실행은 REST 조합이 일반적
- 주문 전 `orders/chance` 확인 습관 필요
- `Remaining-Req` 헤더 기반으로 rate limit 관리 필수
- `uuid`와 `identifier`를 혼동하지 말 것
- 시장가 매수/매도는 `price`, `volume` 필수 여부가 서로 다름

---
