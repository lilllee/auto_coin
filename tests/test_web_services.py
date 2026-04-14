from __future__ import annotations

import pytest

from auto_coin.exchange.upbit_client import AssetBalance, UpbitError
from auto_coin.web.services import upbit_scan
from auto_coin.web.services.credentials_check import (
    check_telegram,
    check_upbit,
    fetch_upbit_holdings,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    upbit_scan.clear_cache()
    yield
    upbit_scan.clear_cache()


# ----- upbit_scan ---------------------------------------------------------


def test_list_krw_tickers_uses_pyupbit(mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH", "USDT-BTC", "BTC-ETH"])
    tickers = upbit_scan.list_krw_tickers()
    assert tickers == ["KRW-BTC", "KRW-ETH"]


def test_list_krw_tickers_cached(mocker):
    call = mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                        return_value=["KRW-BTC"])
    upbit_scan.list_krw_tickers()
    upbit_scan.list_krw_tickers()
    upbit_scan.list_krw_tickers()
    assert call.call_count == 1


def test_is_listed(mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH"])
    assert upbit_scan.is_listed("KRW-BTC") is True
    assert upbit_scan.is_listed("krw-eth") is True   # 대소문자 무관
    assert upbit_scan.is_listed("KRW-NOPE") is False
    assert upbit_scan.is_listed("") is False


def test_validate_tickers_splits_ok_and_bad(mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    ok, bad = upbit_scan.validate_tickers(["krw-btc", "KRW-FAKE", " KRW-ETH ", ""])
    assert ok == ["KRW-BTC", "KRW-ETH"]
    assert bad == ["KRW-FAKE"]


def test_top_by_volume_sorts_and_maps(mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-A", "KRW-B", "KRW-C"])
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = [
        {"market": "KRW-A", "trade_price": 100, "acc_trade_price_24h": 5_000_000_000, "signed_change_rate": 0.01},
        {"market": "KRW-B", "trade_price": 200, "acc_trade_price_24h": 10_000_000_000, "signed_change_rate": -0.02},
        {"market": "KRW-C", "trade_price": 300, "acc_trade_price_24h": 1_000_000_000, "signed_change_rate": 0.05},
    ]
    mock_resp.raise_for_status = mocker.Mock()
    mocker.patch("auto_coin.web.services.upbit_scan.requests.get", return_value=mock_resp)

    top = upbit_scan.top_by_volume(n=3)
    assert [t.market for t in top] == ["KRW-B", "KRW-A", "KRW-C"]
    assert top[0].volume_24h_krw == 10_000_000_000
    assert top[0].change_rate == -0.02


def test_top_by_volume_applies_exclude(mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-A", "KRW-B"])
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = [
        {"market": "KRW-A", "trade_price": 1, "acc_trade_price_24h": 100, "signed_change_rate": 0},
        {"market": "KRW-B", "trade_price": 2, "acc_trade_price_24h": 200, "signed_change_rate": 0},
    ]
    mock_resp.raise_for_status = mocker.Mock()
    mocker.patch("auto_coin.web.services.upbit_scan.requests.get", return_value=mock_resp)
    top = upbit_scan.top_by_volume(n=5, exclude={"KRW-B"})
    assert [t.market for t in top] == ["KRW-A"]


# ----- credentials_check --------------------------------------------------


def test_check_upbit_empty_keys():
    r = check_upbit("", "")
    assert r.ok is False
    assert "비어" in r.detail


def test_check_upbit_auth_failure(mocker):
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_krw_balance",
        side_effect=__import__("auto_coin.exchange.upbit_client", fromlist=["UpbitError"]).UpbitError("bad key"),
    )
    r = check_upbit("ak", "sk")
    assert r.ok is False
    assert "인증 실패" in r.detail


def test_check_upbit_success(mocker):
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_krw_balance",
        return_value=1_234_000.0,
    )
    r = check_upbit("ak", "sk")
    assert r.ok is True
    assert "1,234,000" in r.detail


def test_fetch_upbit_holdings_success(mocker):
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_current_price",
        side_effect=[100000000.0],
    )
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_holdings",
        return_value=[
            AssetBalance(
                currency="KRW",
                unit_currency="KRW",
                balance=50000.0,
                locked=0.0,
                avg_buy_price=0.0,
            ),
            AssetBalance(
                currency="BTC",
                unit_currency="KRW",
                balance=0.01,
                locked=0.0,
                avg_buy_price=100000000.0,
            )
        ],
    )
    r = fetch_upbit_holdings("ak", "sk")
    assert r.ok is True
    assert r.holdings[0].market == "KRW"
    assert r.holdings[0].avg_buy_price_text == "-"
    assert r.holdings[0].krw_value_text == "50,000"
    assert r.holdings[1].market == "KRW-BTC"
    assert r.holdings[1].quantity_text == "0.01"
    assert r.holdings[1].krw_value_text == "1,000,000"


def test_fetch_upbit_holdings_failure(mocker):
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_holdings",
        side_effect=UpbitError("bad key"),
    )
    r = fetch_upbit_holdings("ak", "sk")
    assert r.ok is False
    assert "조회 실패" in r.detail


def test_fetch_upbit_holdings_falls_back_to_avg_buy_price_when_price_lookup_fails(mocker):
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_current_price",
        side_effect=UpbitError("ticker fail"),
    )
    mocker.patch(
        "auto_coin.web.services.credentials_check.UpbitClient.get_holdings",
        return_value=[
            AssetBalance(
                currency="ETH",
                unit_currency="KRW",
                balance=1.5,
                locked=0.0,
                avg_buy_price=3_000_000.0,
            )
        ],
    )
    r = fetch_upbit_holdings("ak", "sk")
    assert r.ok is True
    assert r.holdings[0].krw_value_text == "4,500,000"


def test_check_telegram_empty_token():
    r = check_telegram("", "123")
    assert r.ok is False


def test_check_telegram_getme_fail(mocker):
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.check",
                 return_value=None)
    r = check_telegram("t", "123")
    assert r.ok is False


def test_check_telegram_getme_ok_no_chat_id(mocker):
    from auto_coin.notifier.telegram import BotInfo
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.check",
                 return_value=BotInfo(id=1, username="b", first_name="B"))
    r = check_telegram("t", "")
    assert r.ok is True
    assert "미설정" in r.detail


def test_check_telegram_probe_send_success(mocker):
    from auto_coin.notifier.telegram import BotInfo
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.check",
                 return_value=BotInfo(id=1, username="b", first_name="B"))
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.send",
                 return_value=True)
    r = check_telegram("t", "123", send_probe=True)
    assert r.ok is True
    assert "전송 완료" in r.detail


def test_check_telegram_probe_send_fail(mocker):
    from auto_coin.notifier.telegram import BotInfo
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.check",
                 return_value=BotInfo(id=1, username="b", first_name="B"))
    mocker.patch("auto_coin.web.services.credentials_check.TelegramNotifier.send",
                 return_value=False)
    r = check_telegram("t", "123", send_probe=True)
    assert r.ok is False
    assert "전송 실패" in r.detail
