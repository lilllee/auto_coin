from __future__ import annotations

import pytest

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError


@pytest.fixture
def client():
    c = UpbitClient(
        access_key="ak",
        secret_key="sk",
        max_retries=3,
        backoff_base=0.0,
        min_request_interval=0.0,
    )
    return c


def test_get_current_price_success(mocker, client):
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", return_value=12345.0)
    assert client.get_current_price("KRW-BTC") == 12345.0


def test_get_current_price_none_raises(mocker, client):
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", return_value=None)
    with pytest.raises(UpbitError):
        client.get_current_price("KRW-BTC")


def test_call_retries_then_succeeds(mocker, client):
    fn = mocker.Mock(side_effect=[RuntimeError("boom"), RuntimeError("boom2"), 7.0])
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", fn)
    assert client.get_current_price("KRW-BTC") == 7.0
    assert fn.call_count == 3


def test_call_exhausts_retries(mocker, client):
    fn = mocker.Mock(side_effect=RuntimeError("nope"))
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", fn)
    with pytest.raises(UpbitError):
        client.get_current_price("KRW-BTC")
    assert fn.call_count == 3


def test_dict_error_response_retried(mocker, client):
    fn = mocker.Mock(side_effect=[{"error": {"name": "rate_limit"}}, 100.0])
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", fn)
    assert client.get_current_price("KRW-BTC") == 100.0


def test_buy_market_returns_order_result(mocker, client):
    raw = {"uuid": "abc-123", "side": "bid", "market": "KRW-BTC"}
    mocker.patch.object(client._upbit, "buy_market_order", return_value=raw)
    res = client.buy_market("KRW-BTC", 10000)
    assert res.uuid == "abc-123"
    assert res.side == "buy"
    assert res.market == "KRW-BTC"


def test_buy_market_unexpected_response_raises(mocker, client):
    mocker.patch.object(client._upbit, "buy_market_order", return_value="weird")
    with pytest.raises(UpbitError):
        client.buy_market("KRW-BTC", 10000)


def test_sell_market_returns_order_result(mocker, client):
    raw = {"uuid": "def-456", "side": "ask"}
    mocker.patch.object(client._upbit, "sell_market_order", return_value=raw)
    res = client.sell_market("KRW-BTC", 0.001)
    assert res.uuid == "def-456"
    assert res.side == "sell"


def test_unauthenticated_blocks_private_calls():
    c = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                    min_request_interval=0.0)
    assert c.authenticated is False
    with pytest.raises(UpbitError):
        c.get_krw_balance()


def test_get_krw_balance(mocker, client):
    mocker.patch.object(client._upbit, "get_balance", return_value=50000.0)
    assert client.get_krw_balance() == 50000.0


def test_get_holdings_filters_zero_and_krw(mocker, client):
    mocker.patch.object(
        client._upbit,
        "get_balances",
        return_value=[
            {"currency": "BTC", "unit_currency": "KRW", "balance": "0.01",
             "locked": "0.002", "avg_buy_price": "100000000"},
            {"currency": "KRW", "unit_currency": "KRW", "balance": "5000",
             "locked": "0", "avg_buy_price": "0"},
            {"currency": "XRP", "unit_currency": "KRW", "balance": "0",
             "locked": "0", "avg_buy_price": "1000"},
        ],
    )
    holdings = client.get_holdings()
    assert len(holdings) == 1
    assert holdings[0].market == "KRW-BTC"
    assert holdings[0].total_volume == pytest.approx(0.012)


def test_get_holdings_can_include_krw_and_zero_balances(mocker, client):
    mocker.patch.object(
        client._upbit,
        "get_balances",
        return_value=[
            {"currency": "KRW", "unit_currency": "KRW", "balance": "5000",
             "locked": "0", "avg_buy_price": "0"},
            {"currency": "XRP", "unit_currency": "KRW", "balance": "0",
             "locked": "0", "avg_buy_price": "1000"},
        ],
    )
    holdings = client.get_holdings(include_zero=True, include_krw=True)
    assert [holding.market for holding in holdings] == ["KRW", "KRW-XRP"]
