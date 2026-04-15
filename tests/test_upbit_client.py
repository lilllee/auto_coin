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


def test_get_order_success(mocker, client):
    order_data = {
        "uuid": "order-uuid-1",
        "side": "bid",
        "state": "done",
        "executed_volume": "0.005",
        "avg_price": "95000000",
    }
    mocker.patch.object(client._upbit, "get_order", return_value=order_data)
    result = client.get_order("order-uuid-1")
    assert result == order_data
    client._upbit.get_order.assert_called_once_with("order-uuid-1")


def test_get_order_unexpected_response_raises(mocker, client):
    mocker.patch.object(client._upbit, "get_order", return_value="not-a-dict")
    with pytest.raises(UpbitError):
        client.get_order("bad-uuid")


# ----- get_current_prices (batch) -----

@pytest.fixture
def batch_client(mocker):
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", return_value=0.0)
    return UpbitClient("", "", max_retries=1, min_request_interval=0)


def test_get_current_prices_returns_dict(batch_client, mocker):
    mocker.patch(
        "auto_coin.exchange.upbit_client.pyupbit.get_current_price",
        return_value={"KRW-BTC": 100000000.0, "KRW-ETH": 3000000.0},
    )
    result = batch_client.get_current_prices(["KRW-BTC", "KRW-ETH"])
    assert result == {"KRW-BTC": 100000000.0, "KRW-ETH": 3000000.0}


def test_get_current_prices_filters_none_values(batch_client, mocker):
    mocker.patch(
        "auto_coin.exchange.upbit_client.pyupbit.get_current_price",
        return_value={"KRW-BTC": 100000000.0, "KRW-ETH": None},
    )
    result = batch_client.get_current_prices(["KRW-BTC", "KRW-ETH"])
    assert result == {"KRW-BTC": 100000000.0}
    assert "KRW-ETH" not in result


def test_get_current_prices_empty_list(batch_client):
    result = batch_client.get_current_prices([])
    assert result == {}


def test_get_current_prices_single_ticker_float_fallback(batch_client, mocker):
    """pyupbit이 단건일 때 float을 반환하는 경우 처리."""
    mocker.patch(
        "auto_coin.exchange.upbit_client.pyupbit.get_current_price",
        return_value=50000000.0,
    )
    result = batch_client.get_current_prices(["KRW-BTC"])
    assert result == {"KRW-BTC": 50000000.0}


def test_get_current_prices_none_raises(batch_client, mocker):
    mocker.patch(
        "auto_coin.exchange.upbit_client.pyupbit.get_current_price",
        return_value=None,
    )
    with pytest.raises(UpbitError, match="no prices returned"):
        batch_client.get_current_prices(["KRW-BTC"])


def test_get_current_prices_retries_on_failure(batch_client, mocker):
    """API 실패 시 재시도 후 최종 실패."""
    mocker.patch(
        "auto_coin.exchange.upbit_client.pyupbit.get_current_price",
        side_effect=ConnectionError("timeout"),
    )
    with pytest.raises(UpbitError, match="failed after"):
        batch_client.get_current_prices(["KRW-BTC"])
