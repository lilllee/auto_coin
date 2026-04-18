

# Upbit WebSocket API 정리

> 기준 문서: Upbit Developer Center WebSocket Reference
> 
> 포함 범위:
> - 현재가 (Ticker)
> - 체결 (Trade)
> - 호가 (Orderbook)
> - 캔들 (Candle)
> - 내 주문 및 체결 (MyOrder)
> - 내 자산 (MyAsset)
> - 구독 중인 스트림 목록 조회

---

## 1. 공통 개요

업비트 WebSocket은 요청 메시지를 **JSON Array** 형태로 전송합니다. 일반적인 구성은 아래와 같습니다.

```json
[
  {
    "ticket": "example-ticket"
  },
  {
    "type": "ticker",
    "codes": ["KRW-BTC"]
  },
  {
    "format": "DEFAULT"
  }
]
```

### 공통 구성 요소

- `ticket`: 요청 식별자
- `type`: 구독할 데이터 타입
- `codes`: 구독 대상 마켓 코드 목록
- `format`: 응답 형식

### format

- `DEFAULT`: 전체 필드명 기반 응답
- `SIMPLE` / `SIMPLE_LIST`: 축약 필드명 기반 응답
- 일부 문서 예시에서는 `JSON LIST` 표기도 보임

> 실제 운영에서는 프로젝트 내 응답 파싱 전략에 맞춰 format을 고정해서 사용하는 것이 안전합니다.

---

## 2. 현재가 (Ticker)

### 2.1 요청 메시지 형식

현재가 데이터를 구독하려면 아래 형태의 Data Type Object를 전송합니다.

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | `ticker` | Required | - |
| `codes` | List:String | 구독할 마켓 목록. 반드시 대문자 | Required | - |
| `is_only_snapshot` | Boolean | 스냅샷만 수신 | Optional | `false` |
| `is_only_realtime` | Boolean | 실시간만 수신 | Optional | `false` |

### 2.2 요청 예시

#### DEFAULT

```json
[
  {
    "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49"
  },
  {
    "type": "ticker",
    "codes": ["KRW-BTC", "KRW-ETH"]
  },
  {
    "format": "DEFAULT"
  }
]
```

#### SIMPLE_LIST

```json
[
  {
    "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49"
  },
  {
    "type": "ticker",
    "codes": ["KRW-BTC", "KRW-ETH"]
  },
  {
    "format": "SIMPLE_LIST"
  }
]
```

### 2.3 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | `ticker` |
| `code` | `cd` | 마켓 코드 | String | 예: `KRW-BTC` |
| `opening_price` | `op` | 시가 | Double | |
| `high_price` | `hp` | 고가 | Double | |
| `low_price` | `lp` | 저가 | Double | |
| `trade_price` | `tp` | 현재가 | Double | |
| `prev_closing_price` | `pcp` | 전일 종가 | Double | |
| `change` | `c` | 전일 대비 방향 | String | `RISE`, `EVEN`, `FALL` |
| `change_price` | `cp` | 전일 대비 절대 변동폭 | Double | |
| `signed_change_price` | `scp` | 전일 대비 변동값(부호 포함) | Double | |
| `change_rate` | `cr` | 전일 대비 변동률 절대값 | Double | |
| `signed_change_rate` | `scr` | 전일 대비 변동률(부호 포함) | Double | |
| `trade_volume` | `tv` | 최근 체결량 | Double | |
| `acc_trade_volume` | `atv` | 누적 거래량(UTC 0시 기준) | Double | |
| `acc_trade_volume_24h` | `atv24h` | 24시간 누적 거래량 | Double | |
| `acc_trade_price` | `atp` | 누적 거래대금(UTC 0시 기준) | Double | |
| `acc_trade_price_24h` | `atp24h` | 24시간 누적 거래대금 | Double | |
| `trade_date` | `tdt` | 최근 거래 일자(UTC) | String | `yyyyMMdd` |
| `trade_time` | `ttm` | 최근 거래 시각(UTC) | String | `HHmmss` |
| `trade_timestamp` | `ttms` | 최근 체결 시각(ms) | Long | |
| `ask_bid` | `ab` | 최근 체결이 매수/매도 중 어느 쪽인지 | String | `ASK`, `BID` |
| `acc_ask_volume` | `aav` | 누적 매도량 | Double | |
| `acc_bid_volume` | `abv` | 누적 매수량 | Double | |
| `highest_52_week_price` | `h52wp` | 52주 최고가 | Double | |
| `highest_52_week_date` | `h52wdt` | 52주 최고가 달성일 | String | `yyyy-MM-dd` |
| `lowest_52_week_price` | `l52wp` | 52주 최저가 | Double | |
| `lowest_52_week_date` | `l52wdt` | 52주 최저가 달성일 | String | `yyyy-MM-dd` |
| `market_state` | `ms` | 거래 상태 | String | `PREVIEW`, `ACTIVE`, `DELISTED` |
| `is_trading_suspended` | `its` | 거래 정지 여부 | Boolean | Deprecated |
| `delisting_date` | `dd` | 거래지원 종료일 | Date | |
| `market_warning` | `mw` | 유의 종목 여부 | String | Deprecated |
| `timestamp` | `tms` | 수신 시각(ms) | Long | |
| `stream_type` | `st` | 스트림 구분 | String | `SNAPSHOT`, `REALTIME` |

### 2.4 응답 예시

#### DEFAULT

```json
{
  "type": "ticker",
  "code": "KRW-BTC",
  "opening_price": 31883000,
  "high_price": 32310000,
  "low_price": 31855000,
  "trade_price": 32287000,
  "prev_closing_price": 31883000.0,
  "acc_trade_price": 78039261076.51241,
  "change": "RISE",
  "change_price": 404000.0,
  "signed_change_price": 404000.0,
  "change_rate": 0.0126713295,
  "signed_change_rate": 0.0126713295,
  "ask_bid": "ASK",
  "trade_volume": 0.03103806,
  "acc_trade_volume": 2429.58834336,
  "trade_date": "20230221",
  "trade_time": "074102",
  "trade_timestamp": 1676965262139,
  "acc_ask_volume": 1146.25573608,
  "acc_bid_volume": 1283.33260728,
  "highest_52_week_price": 57678000.0,
  "highest_52_week_date": "2022-03-28",
  "lowest_52_week_price": 20700000.0,
  "lowest_52_week_date": "2022-12-30",
  "market_state": "ACTIVE",
  "is_trading_suspended": false,
  "delisting_date": null,
  "market_warning": "NONE",
  "timestamp": 1676965262177,
  "acc_trade_price_24h": 228827082483.7073,
  "acc_trade_volume_24h": 7158.80283560,
  "stream_type": "REALTIME"
}
```

---

## 3. 체결 (Trade)

### 3.1 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | `trade` | Required | - |
| `codes` | List:String | 구독할 마켓 목록. 반드시 대문자 | Required | - |
| `is_only_snapshot` | Boolean | 스냅샷만 수신 | Optional | `false` |
| `is_only_realtime` | Boolean | 실시간만 수신 | Optional | `false` |

### 3.2 요청 예시

```json
[
  {
    "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49"
  },
  {
    "type": "trade",
    "codes": ["KRW-BTC", "KRW-ETH"]
  },
  {
    "format": "DEFAULT"
  }
]
```

### 3.3 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | `trade` |
| `code` | `cd` | 마켓 코드 | String | |
| `trade_price` | `tp` | 체결 가격 | Double | |
| `trade_volume` | `tv` | 체결량 | Double | |
| `ask_bid` | `ab` | 매도/매수 구분 | String | `ASK`, `BID` |
| `prev_closing_price` | `pcp` | 전일 종가 | Double | |
| `change` | `c` | 전일 대비 방향 | String | `RISE`, `EVEN`, `FALL` |
| `trade_date` | `td` | 체결 일자(UTC) | String | `yyyyMMdd` |
| `trade_time` | `ttm` | 체결 시각(UTC) | String | `HHmmss` |
| `trade_timestamp` | `ttms` | 체결 시각(ms) | Long | |
| `timestamp` | `tms` | 수신 시각(ms) | Long | |
| `sequential_id` | `sid` | 체결 고유 순번 성격의 값 | Long | 정렬/중복 제거 시 활용 가능 |
| `stream_type` | `st` | 스트림 구분 | String | `SNAPSHOT`, `REALTIME` |

### 3.4 응답 예시

```json
{
  "type": "trade",
  "code": "KRW-BTC",
  "trade_price": 50000000,
  "trade_volume": 0.001,
  "ask_bid": "BID",
  "prev_closing_price": 49500000,
  "change": "RISE",
  "trade_date": "20260418",
  "trade_time": "030101",
  "trade_timestamp": 1776471661000,
  "timestamp": 1776471661100,
  "sequential_id": 1776471661000000,
  "stream_type": "REALTIME"
}
```

---

## 4. 호가 (Orderbook)

### 4.1 level(호가 모아보기)

업비트 문서 기준으로 **KRW 마켓에서만** 지원하는 기능입니다. `level` 값을 지정하면 지정 단위로 ask/bid 가격대를 묶어서 받을 수 있습니다.

예:
- `KRW-BTC`에 `level=100000` 요청
- 10만 원 단위로 가격대가 그룹화됨
- 각 가격 구간별 주문 수량 합계가 size로 내려옴

> 지원 가능한 `level` 값은 종목별 호가 단위 정책에 따라 다르므로, 사용 전 반드시 업비트 정책/호가 정책 API 기준으로 확인해야 합니다.

### 4.2 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | `orderbook` | Required | - |
| `codes` | List:String | 구독할 마켓 목록. 반드시 대문자 | Required | - |
| `level` | Double/String | 호가 모아보기 단위 | Optional | `0` |
| `is_only_snapshot` | Boolean | 스냅샷만 수신 | Optional | `false` |
| `is_only_realtime` | Boolean | 실시간만 수신 | Optional | `false` |

### 4.3 요청 예시

```json
[
  {
    "ticket": "orderbook-ticket"
  },
  {
    "type": "orderbook",
    "codes": ["KRW-BTC"],
    "level": 0
  },
  {
    "format": "DEFAULT"
  }
]
```

### 4.4 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | `orderbook` |
| `code` | `cd` | 마켓 코드 | String | |
| `total_ask_size` | `tas` | 총 매도 잔량 | Double | |
| `total_bid_size` | `tbs` | 총 매수 잔량 | Double | |
| `orderbook_units` | `obu` | 호가 단위 배열 | List | |
| `orderbook_units.ask_price` | `ap` | 매도 호가 | Double | |
| `orderbook_units.bid_price` | `bp` | 매수 호가 | Double | |
| `orderbook_units.ask_size` | `as` | 매도 잔량 | Double | |
| `orderbook_units.bid_size` | `bs` | 매수 잔량 | Double | |
| `level` | `lv` | 묶음 단위 | Double/String | 요청 시 사용 |
| `timestamp` | `tms` | 수신 시각(ms) | Long | |
| `stream_type` | `st` | 스트림 구분 | String | `SNAPSHOT`, `REALTIME` |

### 4.5 응답 예시

```json
{
  "type": "orderbook",
  "code": "KRW-BTC",
  "total_ask_size": 12.3456,
  "total_bid_size": 10.9876,
  "orderbook_units": [
    {
      "ask_price": 150000000,
      "bid_price": 149999000,
      "ask_size": 0.45,
      "bid_size": 0.39
    },
    {
      "ask_price": 150001000,
      "bid_price": 149998000,
      "ask_size": 0.73,
      "bid_size": 0.22
    }
  ],
  "level": 0,
  "timestamp": 1776471661100,
  "stream_type": "REALTIME"
}
```

---

## 5. 캔들 (Candle)

### 5.1 실시간 전송 방식

- 캔들 스트림 전송 주기: **1초**
- 단, **체결이 발생하여 직전 캔들 대비 데이터 변경이 생긴 경우에만** 전송됩니다.
- 요청 시점에 해당 단위의 새 캔들이 아직 생성되지 않았다면, 이전 시간대 캔들이 최초 스냅샷으로 전달될 수 있습니다.

### 5.2 요청 타입

업비트 캔들 WebSocket은 단위별로 `type` 값을 나눠 사용합니다.

예시:
- `candle.1s`
- `candle.1m`
- `candle.3m`
- `candle.5m`
- `candle.10m`
- `candle.15m`
- `candle.30m`
- `candle.60m`
- `candle.240m`
- `candle.1d`
- `candle.1w`
- `candle.1M`

### 5.3 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | 예: `candle.1m` | Required | - |
| `codes` | List:String | 구독할 마켓 목록. 반드시 대문자 | Required | - |
| `is_only_snapshot` | Boolean | 스냅샷만 수신 | Optional | `false` |
| `is_only_realtime` | Boolean | 실시간만 수신 | Optional | `false` |

### 5.4 요청 예시

```json
[
  {
    "ticket": "candle-ticket"
  },
  {
    "type": "candle.1m",
    "codes": ["KRW-BTC"]
  },
  {
    "format": "DEFAULT"
  }
]
```

### 5.5 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | 예: `candle.1m` |
| `code` | `cd` | 마켓 코드 | String | |
| `candle_date_time_utc` | `cdttmu` | 캔들 시각(UTC) | String | ISO 계열 문자열 |
| `candle_date_time_kst` | `cdttmk` | 캔들 시각(KST) | String | ISO 계열 문자열 |
| `opening_price` | `op` | 시가 | Double | |
| `high_price` | `hp` | 고가 | Double | |
| `low_price` | `lp` | 저가 | Double | |
| `trade_price` | `tp` | 종가 성격의 현재 체결가 | Double | |
| `candle_acc_trade_volume` | `catv` | 누적 거래량 | Double | 해당 캔들 구간 기준 |
| `candle_acc_trade_price` | `catp` | 누적 거래대금 | Double | 해당 캔들 구간 기준 |
| `timestamp` | `tms` | 수신 시각(ms) | Long | |
| `stream_type` | `st` | 스트림 구분 | String | `SNAPSHOT`, `REALTIME` |

### 5.6 응답 예시

```json
{
  "type": "candle.1m",
  "code": "KRW-BTC",
  "candle_date_time_utc": "2026-04-18T03:01:00",
  "candle_date_time_kst": "2026-04-18T12:01:00",
  "opening_price": 150000000,
  "high_price": 150050000,
  "low_price": 149980000,
  "trade_price": 150010000,
  "candle_acc_trade_volume": 1.2345,
  "candle_acc_trade_price": 185000000.123,
  "timestamp": 1776471661100,
  "stream_type": "REALTIME"
}
```

---

## 6. 내 주문 및 체결 (MyOrder)

> **인증 필요**
>
> 내 주문 및 체결 스트림은 실제 주문/체결이 발생할 때만 이벤트가 전송됩니다. 연결 후 아무 이벤트가 없다면 정상일 수 있습니다.

### 6.1 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | `myOrder` | Required | - |
| `codes` | List | 구독할 마켓 목록 | Optional | 생략 또는 빈 배열이면 전체 마켓 |

### 6.2 요청 예시

#### 전체 마켓 구독

```json
[
  {
    "ticket": "0e66c0ac-7e13-43ef-91fb-2a87c2956c49"
  },
  {
    "type": "myOrder"
  }
]
```

#### 특정 또는 빈 배열 기반 요청

```json
[
  {
    "ticket": "test-myOrder"
  },
  {
    "type": "myOrder",
    "codes": []
  }
]
```

### 6.3 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | `myOrder` |
| `code` | `cd` | 마켓 코드 | String | |
| `uuid` | `uid` | 주문 UUID | String | |
| `ask_bid` | `ab` | 매수/매도 구분 | String | `ASK`, `BID` |
| `order_type` | `ot` | 주문 타입 | String | 예: `limit`, `price`, `market` |
| `state` | `s` | 주문 상태 | String | 예: `wait`, `trade`, `done`, `cancel` |
| `trade_uuid` | `tuid` | 체결 UUID | String | 체결 발생 시 |
| `price` | `p` | 주문 가격 | Double/String | |
| `avg_price` | `ap` | 평균 체결 가격 | Double/String | |
| `volume` | `v` | 주문 수량 | Double/String | |
| `remaining_volume` | `rv` | 미체결 수량 | Double/String | |
| `executed_volume` | `ev` | 누적 체결 수량 | Double/String | |
| `reserved_fee` | `rsf` | 예약 수수료 | Double/String | |
| `remaining_fee` | `rmf` | 남은 수수료 | Double/String | |
| `paid_fee` | `pf` | 지불 수수료 | Double/String | |
| `locked` | `l` | 잠금 금액/수량 | Double/String | |
| `executed_funds` | `ef` | 누적 체결 대금 | Double/String | |
| `trade_fee` | `tf` | 체결 수수료 | Double/String | |
| `is_maker` | `im` | 메이커 여부 | Boolean | |
| `identifier` | `idt` | 사용자 지정 주문 식별자 | String | |
| `trade_timestamp` | `tts` | 체결 시각(ms) | Long | |
| `order_timestamp` | `ots` | 주문 시각(ms) | Long | |
| `stream_type` | `st` | 스트림 구분 | String | `REALTIME` 중심 |

### 6.4 응답 예시

```json
{
  "type": "myOrder",
  "code": "KRW-BTC",
  "uuid": "order-uuid-example",
  "ask_bid": "BID",
  "order_type": "limit",
  "state": "trade",
  "trade_uuid": "trade-uuid-example",
  "price": "150000000",
  "avg_price": "149950000",
  "volume": "0.01",
  "remaining_volume": "0.004",
  "executed_volume": "0.006",
  "reserved_fee": "7500",
  "remaining_fee": "3000",
  "paid_fee": "4500",
  "locked": "600000",
  "executed_funds": "899700",
  "trade_fee": "4500",
  "is_maker": false,
  "identifier": "strategy-order-001",
  "trade_timestamp": 1776471661000,
  "order_timestamp": 1776471600000,
  "stream_type": "REALTIME"
}
```

---

## 7. 내 자산 (MyAsset)

> **인증 필요**
>
> 내 자산 스트림은 실제 자산 변동이 발생했을 때만 전송됩니다.

### 7.1 최초 이용 시 주의사항

업비트 문서에서는 내 자산 WebSocket을 처음 사용하는 경우, REST API 기준 잔고와 이벤트 수신 타이밍을 함께 고려해 상태 동기화를 설계할 것을 권장합니다. 실시간 스트림만으로 전체 상태를 초기화하려 하지 말고, 초기 스냅샷 전략을 별도로 두는 편이 안전합니다.

### 7.2 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 | 기본값 |
|---|---|---|---|---|
| `type` | String | `myAsset` | Required | - |

### 7.3 요청 예시

```json
[
  {
    "ticket": "asset-ticket"
  },
  {
    "type": "myAsset"
  }
]
```

### 7.4 구독 데이터 명세

| 필드명 | 축약형 | 설명 | 타입 | 비고 |
|---|---|---|---|---|
| `type` | `ty` | 데이터 타입 | String | `myAsset` |
| `assets` | `as` | 자산 목록 | List | |
| `assets.currency` | `c` | 화폐 코드 | String | 예: `KRW`, `BTC` |
| `assets.balance` | `b` | 보유 수량 | Double/String | |
| `assets.locked` | `l` | 주문 등에 묶인 수량 | Double/String | |
| `assets.avg_buy_price` | `abp` | 평균 매수 가격 | Double/String | |
| `assets.avg_buy_price_modified` | `abpm` | 평균 매수가 보정 여부 | Boolean | |
| `assets.unit_currency` | `uc` | 기준 화폐 | String | 예: `KRW` |
| `timestamp` | `tms` | 수신 시각(ms) | Long | |
| `stream_type` | `st` | 스트림 구분 | String | `REALTIME` 중심 |

### 7.5 응답 예시

```json
{
  "type": "myAsset",
  "assets": [
    {
      "currency": "KRW",
      "balance": "1000000",
      "locked": "0",
      "avg_buy_price": "0",
      "avg_buy_price_modified": false,
      "unit_currency": "KRW"
    },
    {
      "currency": "BTC",
      "balance": "0.01",
      "locked": "0.002",
      "avg_buy_price": "149000000",
      "avg_buy_price_modified": false,
      "unit_currency": "KRW"
    }
  ],
  "timestamp": 1776471661100,
  "stream_type": "REALTIME"
}
```

---

## 8. 구독 중인 스트림 목록 조회

이 요청은 일반 구독 메시지처럼 `type`이 아니라 **`method` 필드**를 사용합니다. 즉, 데이터 구독이 아니라 **Operation 요청** 성격입니다.

### 8.1 format 주의사항

현재 구독 중인 스트림 목록을 조회할 때 `format` 값을 다르게 보내면, **기존 구독 스트림의 응답 형식 자체가 변경될 수 있음**에 주의해야 합니다.

예:
- 기존 실시간 수신을 `SIMPLE`로 받고 있었는데
- 목록 조회를 `DEFAULT`로 보내면
- 이후 실시간 데이터도 `DEFAULT` 형식으로 바뀔 수 있음

### 8.2 요청 메시지 형식

| 필드명 | 타입 | 설명 | 필수 |
|---|---|---|---|
| `method` | String | 구독 목록 조회 operation | Required |
| `ticket` | String | 요청 식별자 | Required |
| `format` | String | 응답 형식 | Optional |

### 8.3 요청 예시

```json
[
  {
    "ticket": "subscription-check"
  },
  {
    "method": "LIST_SUBSCRIPTIONS"
  },
  {
    "format": "DEFAULT"
  }
]
```

### 8.4 응답 개요

응답에는 현재 연결에서 구독 중인 스트림들의 목록이 내려옵니다. 일반적으로 각 스트림의 타입, 코드 목록, 요청 시 옵션 등이 포함됩니다.

예시 개념:

```json
{
  "ticket": "subscription-check",
  "subscriptions": [
    {
      "type": "ticker",
      "codes": ["KRW-BTC"]
    },
    {
      "type": "orderbook",
      "codes": ["KRW-BTC"],
      "level": 0
    }
  ]
}
```

---

## 9. 프로젝트 적용 시 체크포인트

### 9.1 마켓 코드는 항상 대문자

예:
- `KRW-BTC`
- `KRW-ETH`

### 9.2 스냅샷 / 실시간 옵션 분리

- 초기 진입 시 `is_only_snapshot`으로 최초 상태 확인
- 이후 `is_only_realtime` 또는 기본 실시간 구독으로 전환

### 9.3 stream_type 활용

응답의 `stream_type`으로 스냅샷과 실시간 이벤트를 분리 처리하면 상태 관리가 쉬워집니다.

### 9.4 MyOrder / MyAsset은 이벤트가 없으면 조용한 것이 정상

- 데이터가 안 온다고 곧바로 장애로 판단하면 안 됨
- ping/pong, keepalive, reconnect 정책을 별도로 설계해야 함

### 9.5 Orderbook level은 사전 검증 필요

지원하지 않는 `level`을 요청하면 데이터가 오지 않을 수 있으므로 운영 코드에서는 마켓별 정책 확인이 선행되어야 합니다.

### 9.6 초기 상태 동기화 전략 필요

실시간 스트림만으로 전체 상태를 복원하지 말고 다음 조합을 권장:

- 공개 데이터: REST 초기 조회 + WebSocket 증분 반영
- 개인 데이터: 잔고/주문 REST 초기 조회 + MyOrder/MyAsset 이벤트 반영

---

## 10. 권장 구현 방향

### 공개 채널

- `ticker`: 가격/등락/누적 거래량 모니터링
- `trade`: 체결 단위 시세 흐름 분석
- `orderbook`: 호가창 기반 매수/매도 압력 분석
- `candle.*`: 전략용 캔들 갱신 반영

### 개인 채널

- `myOrder`: 주문 상태 전이 추적 (`wait` → `trade` → `done` / `cancel`)
- `myAsset`: 잔고 변화 추적

### 운영 레벨 추천

- WebSocket 연결 관리자 분리
- 타입별 파서 분리
- 마켓별 상태 저장소 분리
- reconnect/backfill 로직 필수
- 수신 이벤트 원본 로깅 옵션 제공

---

## 11. 참고 링크

- https://docs.upbit.com/kr/reference/websocket-ticker
- https://docs.upbit.com/kr/reference/websocket-trade
- https://docs.upbit.com/kr/reference/websocket-orderbook
- https://docs.upbit.com/kr/reference/websocket-candle
- https://docs.upbit.com/kr/reference/websocket-myorder
- https://docs.upbit.com/kr/reference/websocket-myasset
- https://docs.upbit.com/kr/reference/list-subscriptions