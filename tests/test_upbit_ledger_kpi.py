"""Codex 0010 — `web/services/upbit_ledger_kpi.py` 순수 함수 테스트.

다루는 시나리오 (모두 합성 데이터):
    1) 1 buy / 1 sell — 정확한 PnL & 수수료 적용
    2) 1 buy / 부분 매도 (lot 분할)
    3) 다수 buy / 1 sell — FIFO 두 lot 가로지르기
    4) unmatched buy → open_lots
    5) unmatched sell → 경고 + realized 제외
    6) KRW deposit/withdraw → cash flow에만 반영
    7) 한글 paste 텍스트 파서
    8) compute_ledger_kpi 빈 입력
"""

from __future__ import annotations

from datetime import datetime

import pytest

from auto_coin.web.services.upbit_ledger_kpi import (
    SIDE_BUY,
    SIDE_SELL,
    LedgerEvent,
    compute_ledger_kpi,
    krw_deposit,
    krw_withdraw,
    parse_korean_upbit_table,
)


def _ev(
    *, ts: datetime, asset: str, side: str,
    qty: float, price: float, fee: float = 0.0,
    market: str | None = "KRW",
) -> LedgerEvent:
    gross = qty * price
    if side == SIDE_BUY:
        net = gross + fee
    elif side == SIDE_SELL:
        net = gross - fee
    else:
        net = gross
    return LedgerEvent(
        timestamp=ts, asset=asset, market=market, side=side,  # type: ignore[arg-type]
        quantity=qty, price=price, gross_krw=gross, fee_krw=fee,
        net_krw=net, source="test",
    )


# ---------------------------------------------------------------------------
# FIFO core
# ---------------------------------------------------------------------------

def test_compute_ledger_kpi_empty():
    r = compute_ledger_kpi([])
    assert r.parsed_event_count == 0
    assert r.matched_trade_count == 0
    assert r.realized_pnl_krw == 0.0
    assert r.period_start is None
    assert r.period_end is None


def test_simple_buy_then_sell_with_fees():
    """100원에 1개 buy(fee 1) → 110원에 1개 sell(fee 1.1) → PnL = (110-1.1) - (100+1) = 7.9"""
    events = [
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="DOGE", side=SIDE_BUY,
            qty=1.0, price=100.0, fee=1.0),
        _ev(ts=datetime(2026, 4, 14, 11, 0), asset="DOGE", side=SIDE_SELL,
            qty=1.0, price=110.0, fee=1.1),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    assert r.unmatched_buy_count == 0
    assert r.unmatched_sell_count == 0
    assert r.realized_pnl_krw == pytest.approx(7.9)
    assert r.win_count == 1
    assert r.loss_count == 0
    assert r.win_rate == 100.0
    # ratio = 7.9 / 101 ≈ 0.07822...
    assert r.avg_pnl_ratio == pytest.approx(7.9 / 101.0)
    # 총 fee = buy_fee 1.0 + sell_fee 1.1 = 2.1
    assert r.total_fee_krw == pytest.approx(2.1)


def test_partial_sells_split_lot_proportionally():
    """1개 buy(100, fee 1) → 0.6 sell(110, fee 0.66) → 0.4 sell(120, fee 0.48).

    각 부분 매도에서 buy lot 비용은 비율 분할.
    매칭1: buy_cost = 101 * 0.6 = 60.6, sell_proceeds = 66 - 0.66 = 65.34 → PnL 4.74
    매칭2: buy_cost = 101 * 0.4 = 40.4, sell_proceeds = 48 - 0.48 = 47.52 → PnL 7.12
    합계 PnL = 11.86, open_lots = 0.
    """
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="BTC", side=SIDE_BUY,
            qty=1.0, price=100.0, fee=1.0),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="BTC", side=SIDE_SELL,
            qty=0.6, price=110.0, fee=0.66),
        _ev(ts=datetime(2026, 4, 14, 11, 0), asset="BTC", side=SIDE_SELL,
            qty=0.4, price=120.0, fee=0.48),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 2
    assert r.unmatched_buy_count == 0
    assert r.unmatched_sell_count == 0
    assert r.realized_pnl_krw == pytest.approx(4.74 + 7.12, rel=1e-9)
    # 첫 매칭의 buy_net_krw == 60.6
    m1, m2 = r.matched_trades
    assert m1.buy_net_krw == pytest.approx(60.6)
    assert m1.sell_net_krw == pytest.approx(65.34)
    assert m2.buy_net_krw == pytest.approx(40.4)
    assert m2.sell_net_krw == pytest.approx(47.52)


def test_multiple_buys_one_sell_crossing_lots():
    """buy 0.5@100 (fee 0.5) + buy 0.5@200 (fee 1.0) → sell 1.0@250 (fee 2.5).

    FIFO:
      lot1 비용 = 50.5 (전부 소진)
      lot2 비용 = 101.0 (전부 소진)
    SELL 비례 분할:
      매칭1: 0.5 * 250 - 2.5*0.5 = 125 - 1.25 = 123.75 / cost 50.5 → PnL 73.25
      매칭2: 0.5 * 250 - 2.5*0.5 = 125 - 1.25 = 123.75 / cost 101 → PnL 22.75
    합계 = 96.0, win 2.
    """
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="ETH", side=SIDE_BUY,
            qty=0.5, price=100.0, fee=0.5),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="ETH", side=SIDE_BUY,
            qty=0.5, price=200.0, fee=1.0),
        _ev(ts=datetime(2026, 4, 14, 11, 0), asset="ETH", side=SIDE_SELL,
            qty=1.0, price=250.0, fee=2.5),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 2
    assert r.unmatched_buy_count == 0
    assert r.unmatched_sell_count == 0
    assert r.realized_pnl_krw == pytest.approx(96.0)
    assert r.win_count == 2
    assert r.loss_count == 0


def test_unmatched_buy_becomes_open_lot():
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="XRP", side=SIDE_BUY,
            qty=10.0, price=100.0, fee=2.0),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="XRP", side=SIDE_SELL,
            qty=4.0, price=110.0, fee=0.88),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    assert r.unmatched_buy_count == 1
    assert r.unmatched_sell_count == 0
    open_lot = r.open_lots[0]
    assert open_lot.asset == "XRP"
    assert open_lot.quantity == pytest.approx(6.0)
    # 잔량 비례 buy_net_krw = 1002 * (6/10) = 601.2
    assert open_lot.buy_net_krw == pytest.approx(601.2)


def test_unmatched_sell_warning_and_excluded_from_realized():
    """대응 BUY 없는 SELL은 unmatched로 분리 + realized PnL에는 포함되지 않는다."""
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="DOGE", side=SIDE_SELL,
            qty=1.0, price=110.0, fee=1.1),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 0
    assert r.unmatched_sell_count == 1
    assert r.realized_pnl_krw == 0.0
    assert any("unmatched SELL" in note for note in r.notes)


def test_partial_sell_unmatched_leftover():
    """SELL 0.5 한 다음 BUY 0.3만 남아있는 상황의 SELL 0.5 → 0.3 matched + 0.2 unmatched."""
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="SOL", side=SIDE_BUY,
            qty=0.3, price=100.0, fee=0.3),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="SOL", side=SIDE_SELL,
            qty=0.5, price=120.0, fee=0.6),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    assert r.unmatched_sell_count == 1
    assert r.matched_trades[0].quantity == pytest.approx(0.3)
    leftover = r.unmatched_sells[0]
    assert leftover.quantity == pytest.approx(0.2)


def test_krw_deposit_withdraw_excluded_from_trading_pnl():
    events = [
        krw_deposit(datetime(2026, 4, 14, 8, 0), 100_000.0),
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="DOGE", side=SIDE_BUY,
            qty=1.0, price=100.0, fee=0.1),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="DOGE", side=SIDE_SELL,
            qty=1.0, price=90.0, fee=0.09),
        krw_withdraw(datetime(2026, 4, 14, 12, 0), 50_000.0),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    # PnL = (90 - 0.09) - (100 + 0.1) = -10.19
    assert r.realized_pnl_krw == pytest.approx(-10.19)
    assert r.cash_flow_krw == pytest.approx(50_000.0)
    # 입출금이 trade count에 잡히지 않는다
    assert r.win_count == 0
    assert r.loss_count == 1


def test_breakdowns_per_asset_and_per_day():
    """자산별/일자별 그룹핑이 채워진다."""
    events = [
        _ev(ts=datetime(2026, 4, 14, 9, 0), asset="BTC", side=SIDE_BUY,
            qty=1.0, price=100.0, fee=0.1),
        _ev(ts=datetime(2026, 4, 14, 10, 0), asset="BTC", side=SIDE_SELL,
            qty=1.0, price=110.0, fee=0.11),
        _ev(ts=datetime(2026, 4, 15, 9, 0), asset="ETH", side=SIDE_BUY,
            qty=2.0, price=200.0, fee=0.4),
        _ev(ts=datetime(2026, 4, 15, 10, 0), asset="ETH", side=SIDE_SELL,
            qty=2.0, price=190.0, fee=0.38),
    ]
    r = compute_ledger_kpi(events)
    assets = {b.asset: b for b in r.by_asset}
    assert set(assets) == {"BTC", "ETH"}
    assert assets["BTC"].matched_count == 1
    assert assets["BTC"].realized_pnl_krw == pytest.approx(110 - 0.11 - 100 - 0.1)
    days = {b.date for b in r.by_day}
    assert days == {datetime(2026, 4, 14).date(), datetime(2026, 4, 15).date()}


# ---------------------------------------------------------------------------
# Korean paste parser
# ---------------------------------------------------------------------------

def test_parse_korean_upbit_table_basic_paste():
    text = """
체결시간\t코인\t마켓\t종류\t거래수량\t거래단가\t거래금액\t수수료\t정산금액\t주문시간
2026-04-14 15:32:11\tDOGE\tKRW\t매수\t100\t100\t10,000\t5\t10,005\t2026-04-14 15:32:00
2026-04-14 16:45:30\tDOGE\tKRW\t매도\t100\t110\t11,000\t5.5\t10,994.5\t2026-04-14 16:45:00
"""
    events = parse_korean_upbit_table(text)
    assert len(events) == 2
    e_buy, e_sell = events
    assert e_buy.side == SIDE_BUY
    assert e_buy.asset == "DOGE"
    assert e_buy.market == "KRW"
    assert e_buy.quantity == 100.0
    assert e_buy.price == 100.0
    assert e_buy.gross_krw == 10_000.0
    assert e_buy.fee_krw == 5.0
    assert e_buy.net_krw == 10_005.0
    assert e_sell.side == SIDE_SELL
    assert e_sell.net_krw == pytest.approx(10_994.5)
    # 한글 raw가 보존된다
    assert e_buy.raw is not None
    assert "매수" in e_buy.raw["kind"]


def test_parse_korean_upbit_table_double_space_separator():
    """탭 대신 2칸 이상 공백으로 구분된 행도 파싱해야 한다."""
    text = """체결시간   코인   마켓   종류   거래수량   거래단가   거래금액   수수료   정산금액   주문시간
2026-04-14 15:32:11   BTC   KRW   매수   0.001   50,000,000   50,000   25   50,025   2026-04-14 15:32:00
"""
    events = parse_korean_upbit_table(text)
    assert len(events) == 1
    assert events[0].asset == "BTC"
    assert events[0].quantity == pytest.approx(0.001)
    assert events[0].price == 50_000_000.0


def test_parse_then_compute_full_pipeline():
    """파서 + FIFO를 합쳐서 한 사이클이 정상 동작."""
    text = """체결시간\t코인\t마켓\t종류\t거래수량\t거래단가\t거래금액\t수수료\t정산금액\t주문시간
2026-04-14 15:32:11\tDOGE\tKRW\t매수\t100\t100\t10,000\t5\t10,005\t2026-04-14 15:32:00
2026-04-14 16:45:30\tDOGE\tKRW\t매도\t100\t110\t11,000\t5.5\t10,994.5\t2026-04-14 16:45:00
"""
    events = parse_korean_upbit_table(text)
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    assert r.realized_pnl_krw == pytest.approx(10_994.5 - 10_005.0)


def test_parse_skips_invalid_rows_silently():
    text = """체결시간\t코인\t마켓\t종류\t거래수량\t거래단가\t거래금액\t수수료\t정산금액\t주문시간
2026-04-14 15:32:11\tDOGE\tKRW\t매수\t100\t100\t10,000\t5\t10,005\t2026-04-14 15:32:00
이건 깨진 행 \t 이상한 토큰
# 주석은 무시
2026-04-14 16:45:30\tDOGE\tKRW\t매도\t100\t110\t11,000\t5.5\t10,994.5\t2026-04-14 16:45:00
"""
    events = parse_korean_upbit_table(text)
    assert len(events) == 2


def test_parse_handles_no_space_currency_suffix():
    """Upbit 웹 카피는 숫자와 통화 코드가 붙어 있다 — `12.70119121XRP`, `2,074.0KRW`."""
    text = (
        "체결시간\t코인\t마켓\t종류\t거래수량\t거래단가\t거래금액\t수수료\t정산금액\t주문시간\n"
        "2026-05-03 21:07:00\tXRP\tKRW\t매수\t12.70119121XRP\t2,074.0KRW\t26,343KRW\t13.17KRW\t26,356KRW\t2026-05-03 21:07:00\n"
    )
    events = parse_korean_upbit_table(text)
    assert len(events) == 1
    e = events[0]
    assert e.quantity == pytest.approx(12.70119121)
    assert e.price == pytest.approx(2074.0)
    assert e.gross_krw == pytest.approx(26_343.0)
    assert e.fee_krw == pytest.approx(13.17)
    assert e.net_krw == pytest.approx(26_356.0)


def test_equal_timestamp_buy_processed_before_sell():
    """동일 timestamp 의 BUY/SELL은 BUY 먼저 처리해야 unmatched SELL이 안 생긴다.

    Upbit 웹 카피는 newest-first 순으로 SELL이 먼저 등장하지만, 인과상 BUY 가
    같은 분(minute)에 먼저 발생했음 — 보유 없이 SELL은 불가능.
    """
    events = [
        _ev(ts=datetime(2026, 4, 18, 18, 31), asset="XRP", side=SIDE_SELL,
            qty=23.31, price=2144.0, fee=24.98),
        _ev(ts=datetime(2026, 4, 18, 18, 31), asset="XRP", side=SIDE_BUY,
            qty=23.31, price=2145.0, fee=24.99),
    ]
    r = compute_ledger_kpi(events)
    assert r.matched_trade_count == 1
    assert r.unmatched_buy_count == 0
    assert r.unmatched_sell_count == 0


# ---------------------------------------------------------------------------
# CLI script
# ---------------------------------------------------------------------------

def test_cli_script_writes_json(tmp_path):
    """`scripts/upbit_ledger_kpi_from_export.py` 가 paste → JSON 파일을 만들어준다."""
    import importlib.util

    script_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "scripts" / "upbit_ledger_kpi_from_export.py"
    )
    spec = importlib.util.spec_from_file_location("upbit_ledger_kpi_cli", script_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)

    paste = tmp_path / "in.txt"
    paste.write_text(
        "체결시간\t코인\t마켓\t종류\t거래수량\t거래단가\t거래금액\t수수료\t정산금액\t주문시간\n"
        "2026-04-14 15:32:11\tDOGE\tKRW\t매수\t100\t100\t10,000\t5\t10,005\t2026-04-14 15:32:00\n"
        "2026-04-14 16:45:30\tDOGE\tKRW\t매도\t100\t110\t11,000\t5.5\t10,994.5\t2026-04-14 16:45:00\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    rc = module.main(["--input", str(paste), "--out", str(out)])
    assert rc == 0
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["matched_trade_count"] == 1
    assert payload["realized_pnl_krw"] == pytest.approx(989.5)


def test_cli_csv_path(tmp_path):
    import importlib.util

    script_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "scripts" / "upbit_ledger_kpi_from_export.py"
    )
    spec = importlib.util.spec_from_file_location("upbit_ledger_kpi_cli2", script_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)

    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "fill_time,asset,market,side,quantity,price,gross_krw,fee_krw,net_krw\n"
        "2026-04-14 15:32:11,DOGE,KRW,buy,100,100,10000,5,10005\n"
        "2026-04-14 16:45:30,DOGE,KRW,sell,100,110,11000,5.5,10994.5\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    rc = module.main(["--csv", str(csv_path), "--out", str(out)])
    assert rc == 0
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["matched_trade_count"] == 1
    assert payload["realized_pnl_krw"] == pytest.approx(989.5)
