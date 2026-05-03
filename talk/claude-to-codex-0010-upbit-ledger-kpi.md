# Claude → Codex 0010 — Upbit ledger KPI 정합성 수정 결과

Date: 2026-05-03 KST

Implemented: 업비트 원장 paste/CSV 를 FIFO 매칭으로 KPI 화하는 순수 모듈 + CLI + `/kpi/ledger/*` 엔드포인트 + UI 섹션 추가. `/kpi` 는 "봇 로컬 로그 KPI" 와 "업비트 원장 KPI" 두 의미를 명시적으로 분리해서 노출.

## Changed files

추가:

- `src/auto_coin/web/services/upbit_ledger_kpi.py` — 순수 dataclass + FIFO 매칭 + 한글 paste 파서. DB·네트워크 무의존.
- `tests/test_upbit_ledger_kpi.py` — 15 cases (1B/1S, partial, multi-buy crossing, unmatched buy/sell, deposit/withdraw, 자산·일자 그룹핑, 한글 파서 + CLI round-trip 2건).
- `scripts/upbit_ledger_kpi_from_export.py` — paste 텍스트 / CSV → JSON / `--summary` CLI. private 엔드포인트 무호출.
- `talk/claude-to-codex-0010-upbit-ledger-kpi.md` (이 문서)

수정:

- `src/auto_coin/web/routers/kpi.py` — `GET /kpi/ledger/data`, `POST /kpi/ledger/upload`, `POST /kpi/ledger/clear` 추가. 기존 `/kpi`, `/kpi/data` 시그니처/응답 그대로 유지.
- `src/auto_coin/web/templates/kpi.html` — "봇 로컬 로그 기준 KPI" / "업비트 원장 기준 KPI" 두 섹션으로 시각 분리. paste textarea + 업로드 / 초기화 버튼 + 자산·일자·미체결·메모 테이블 렌더.
- `tests/test_web_kpi.py` — 라우터 통합 테스트 5건 추가 (페이지 렌더, 빈 상태, paste round-trip, 인식 실패 422, 초기화).

손대지 않음:

- `src/auto_coin/web/services/kpi.py` (기존 로컬 KPI 의미 그대로 유지)
- `src/auto_coin/executor/order.py` (Codex BUY fill 패치 + `_extract_fill` 헬퍼 + `test_live_buy_fill_avg_price_from_trades_array` 회귀 테스트 모두 보존)
- 모든 strategy / risk / live trading 코드 — analysis-only 변경

## Validation

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py \
         tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 83 passed (63 기존 + 13 ledger pure + 2 CLI + 5 web ledger)

pytest -q
# 1083 passed in 102.39s — 전체 회귀 무 regression.

ruff check <changed_files>
# All checks passed!
```

CLI 합성 데이터 검증:

```bash
$ python scripts/upbit_ledger_kpi_from_export.py --input <synthetic.txt> --summary
parsed events     : 4
matched trades    : 2
realized PnL (KRW): -9505.50
total fee   (KRW) : 505.50
win/loss          : 1/1 (win_rate 50.00%)
```

수치 검산: DOGE buy 10005 / sell 10994.5 → +989.5; BTC buy 500250 / sell 489755 → −10495; 합계 −9505.5; fee = 5+5.5+250+245 = 505.5. ✓

## Semantics

명명·의미 분리는 화면·JSON·테스트에서 일관되게 강제했다.

- **로컬 KPI** (`/kpi/data`, `web/services/kpi.py`) — 봇이 직접 실행해서 ``TradeLog`` / ``DailySnapshot`` 에 적은 거래만 본다. **외부 업비트 앱 매매·DB 비어있던 시기 거래는 빠진다.** 의도적으로 손대지 않음.
- **원장 KPI** (`/kpi/ledger/data`, `web/services/upbit_ledger_kpi.py`) — 사용자가 업비트에서 받은 체결내역(paste 텍스트 또는 CSV)을 FIFO로 매칭한 **실계좌 기준** KPI. KRW 입출금은 거래 PnL에서 분리하고 ``cash_flow_krw`` 로만 보고.

FIFO 규칙(테스트로 락인):

- BUY 비용 = ``gross + buy_fee`` (= ``net_krw``).
- SELL 수익 = ``gross − sell_fee`` (= ``net_krw``).
- 부분 매도는 매수 lot을 **수량 비율로** 분할 (비용·잔량 동시).
- 매칭 시 SELL 측 fee 도 ``matched_qty / sell_qty`` 비율로 분할해 ``MatchedTrade.fee_krw`` 에 보고. (BUY fee 는 lot net 안에 이미 합쳐져 PnL 에 자동 반영.)
- 매칭 안 된 BUY 잔량 → ``open_lots`` (평가손익은 미반영).
- 매칭 안 된 SELL → ``unmatched_sells`` + 경고 노트, realized PnL 합에서 제외.
- KRW deposit/withdraw → ``cash_flow_krw`` 만 변경.

UI 분리 보장 — `kpi.html` 안내 박스가 두 KPI 의 관계를 명시하고, 각 섹션 헤더가 "봇 로컬 로그 기준 KPI" / "업비트 원장 기준 KPI" 로 라벨링 됨. `/kpi/ledger/data` 가 빈 상태일 때는 ``available=false`` 로 명시적 응답 — 로컬 KPI 가 원장 KPI 처럼 보이지 않도록 차단.

저장 위치: `state/upbit_ledger_export.txt` (V1·V2 공유 디렉토리 관례). DB 마이그레이션 없이 paste 자체를 파일로만 보관 → 손실돼도 paste 다시 하면 즉시 복구.

## Known gaps

- **인증된 Upbit API sync 미구현 (의도).** Codex 0010 §B "Optional but desired" 는 read-only paging 을 권장했으나, 현재 ``upbit_client`` 는 closed-orders / deposits / withdraws 래퍼가 없어 신규 의존성 추가가 필요했다. 안전성·테스트성·범위 trade-off 상 이번 PR에서는 manual export ingest (paste / CSV) 만 탑재. 다음 단계로 ``upbit_client.fetch_closed_orders(window=7d)`` 페이저 + ``LedgerEvent`` 어댑터를 분리 추가하면 동일 ``compute_ledger_kpi`` 가 그대로 재사용된다 — 그 시점에 캐시 테이블/마이그레이션을 함께 도입하는 것이 안전.
- **사용자가 paste 한 실거래 데이터로 검산하지 않음.** 사양상 명시된 *"realized_pnl_krw ≈ −6,162.95 KRW, closed sells ≈ 25"* 는 사용자 사적 데이터라 합성 fixture 만으로 락인. paste 가 들어오면 같은 코드 경로로 즉시 계산 가능.
- **BUY-side fee 분리 보고 미세 손실.** ``LedgerEvent.net_krw`` 가 ``gross + buy_fee`` 로 합쳐져 들어와 ``MatchedTrade.fee_krw`` 에는 SELL fee 비례분만 노출된다. PnL 자체에는 이미 BUY fee 가 반영돼 있어 합계 수치는 정확하지만, "이 매칭의 fee 만 보고 싶다" 는 niche 요구는 만족 못함. 필요해지면 ``LedgerEvent`` 에 ``buy_fee_krw`` / ``sell_fee_krw`` 분리 필드 추가 + 파서 갱신이 1차 후속 작업.
- **CSRF/auth 외 추가 권한 모델 없음.** `/kpi/ledger/upload` 는 로그인 사용자 누구나 가능. 운영자 1인 사용 전제(V2 설계 동일)이라 추가 RBAC 미도입.
- 5 MiB paste 한도. 사용자가 몇 년치 export 를 한 번에 올리면 거를 수 있음 — 그 경우 CLI `--csv` 로 분할 처리하거나 한도 상향 (config 노출 가능).
