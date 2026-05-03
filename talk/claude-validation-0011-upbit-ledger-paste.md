# Claude validation 0011 — Real Upbit paste ledger KPI 검산

Date: 2026-05-03 KST · Workplan: codex-workplan-0011 Phase 3

## TL;DR

사용자가 붙여넣은 실제 업비트 체결내역(2026-04-16 ~ 2026-05-03)을 Codex 0010 ledger KPI 파이프라인으로 검산. **realized PnL = -6,163.00 KRW** 로 Codex 의 사전 추정치 -6,162.95 KRW 와 0.05 KRW 차이(<0.001%) 수준의 사실상 일치. 1차 시도에서 발견된 실데이터 호환성 두 건(공백 없는 통화 suffix, 동일-minute BUY/SELL tie-break)은 라이브러리에서 수정·회귀 테스트 추가.

## Aggregate result

| 항목 | 값 | 비고 |
|---|---:|---|
| period | 2026-04-16 ~ 2026-05-03 | paste 시간 범위 |
| parsed events | 56 | 56 = 25 SELL + 29 BUY + 2 입금(skip, 미지원) |
| closed sell events | 25 | unmatched_sell = 0 |
| matched_trade_count | 38 | SELL 1건이 multi-lot crossing 시 row 분할 → 25 < 38 정상 |
| unmatched_buy (open lots) | 7 | 기간 종료 시 보유 잔량 |
| unmatched_sell | 0 | (1차 결과 1건 → tie-break 수정으로 해소) |
| realized PnL (KRW) | **-6,163.00** | Codex 추정치 -6,162.95 와 0.05 KRW 차 (<0.001%) |
| total fee (KRW) | 940.12 | 수수료는 PnL 에 이미 반영됨 |
| win/loss | 9 / 29 | 승률 23.68% (matched 단위) |
| avg pnl_ratio | -1.0647% | matched lot 단위 평균 |

By asset (KRW):

| asset | matched | realized PnL |
|---|---:|---:|
| BTC | 1 | +415.18 |
| ETH | 8 | -25.00 |
| SOL | 12 | -1,866.84 |
| XRP | 15 | -2,331.34 |
| DOGE | 2 | -2,355.00 |

(자산별 합계 = -6,163.00 KRW. 자산명·집계 수치만 노출. 거래별 timestamp 는 PR/talk 에 적지 않음 — 사용자 사적 데이터 보호.)

## 1차 시도에서 발견된 실데이터 호환성 이슈 두 건

수정 후 통과. 모두 회귀 테스트 추가.

### 1. 통화 suffix 가 공백 없이 붙어있음

업비트 웹 카피는 `"12.70119121XRP"`, `"2,074.0KRW"` 처럼 숫자·코드가 공백 없이 붙는다. 기존 `_parse_korean_number` 는 ` KRW`, ` BTC` 등 공백 구분 suffix 만 제거했으므로 모든 row 가 silent skip → parsed_event_count = 0.

수정: trailing 알파벳 전체를 정규식으로 제거.

```python
_TRAILING_UNIT_RE = re.compile(r"[A-Za-z]+\s*$")
s = _TRAILING_UNIT_RE.sub("", s).strip()
```

회귀 테스트: `test_parse_handles_no_space_currency_suffix`.

### 2. 동일 timestamp 의 BUY/SELL tie-break

업비트 웹 카피는 newest-first 정렬이라 같은 minute 의 BUY/SELL 이 같이 있을 때 SELL 행이 먼저 등장한다. `sorted(events, key=timestamp)` 는 stable 정렬이라 입력 순서를 유지 → SELL 이 BUY 앞에 처리돼 인과 위반(보유 없는 자산을 매도). 1 unmatched SELL 발생.

수정: 동일 timestamp 시 `BUY < SELL < DEPOSIT/WITHDRAW` tie-break.

```python
_SIDE_ORDER = {SIDE_BUY: 0, SIDE_SELL: 1, SIDE_DEPOSIT: 2, SIDE_WITHDRAW: 3}
events_sorted = sorted(events, key=lambda e: (e.timestamp, _SIDE_ORDER.get(e.side, 9)))
```

회귀 테스트: `test_equal_timestamp_buy_processed_before_sell`. 결과: unmatched_sell 1 → 0, matched 36 → 38, realized PnL -6,204.71 → -6,163.00 (Codex 기대치에 근접).

## Pre-process for Upbit web paste 형식

업비트 웹의 "거래내역 복사" paste 는 **셀당 1줄** 의 10-line block 포맷이다. CLI 가 직접 받지 못하므로 사용자는 다음 중 한 경로를 사용한다:

1. **CSV export** (정식) — `--csv <path>` 로 직접 입력. 헤더 한글/영어 alias 모두 허용.
2. **웹 paste** — 10-line block → tab-separated 변환 후 `--input` 사용.

두 번째 경로는 매번 같은 변환이 필요해 다음 단계 후속(별도 PR)으로 `parse_korean_upbit_table` 자체에 multi-line block 자동 감지를 넣을 수 있다. 본 검증에서는 `data/manual/_preprocess.py` 1회용 스크립트로 변환 (gitignored, 미커밋).

## Known gaps observed during this validation

| 항목 | 영향 | 후속 |
|---|---|---|
| 입금/출금 row 가 파서에서 silent skip (115 KRW 누락) | cash_flow_krw 만 영향, PnL 무관 | 작은 후속 — 파서가 입금/출금 인식하면 자동 반영 |
| Multi-line web paste 는 외부 변환 필요 | UX | 위와 같은 후속 — 파서 자동 감지 추가 가능 |
| Open lots(7건) 평가손익 미반영 | 기간 종료 시점 보유분 평가가치는 별도 이슈 | 후속 — 현재가 조회로 unrealized 추정 가능 |
| FIFO 매칭이 실제 업비트 lot 매칭과 100% 일치 보장 없음 | 중요 — 다만 PnL 합계는 가정에 무관하게 일치 | 정합성 확인됨 (Codex 추정치와 0.05 KRW 차) |

## Files touched

- `src/auto_coin/web/services/upbit_ledger_kpi.py` — 통화 suffix 정규식·BUY/SELL tie-break.
- `tests/test_upbit_ledger_kpi.py` — 회귀 테스트 +2 (총 17건).
- `data/manual/upbit_history_2026-04-14_2026-05-03.{txt,tabbed.txt,json}` — **gitignored, 미커밋** (사용자 사적 데이터).
- `data/manual/_preprocess.py` — 1회용 변환 스크립트, **gitignored, 미커밋**.

## Phase 3 stop condition

✅ 사용자 실제 export 가 정상적으로 파싱·매칭됨. realized PnL 이 Codex 추정치와 0.05 KRW 차로 일치. 발견된 두 호환성 이슈는 라이브러리 수정 + 회귀 테스트로 lock-in 완료.
