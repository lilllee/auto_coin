from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.bot import TradingBot
from auto_coin.config import Settings
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.risk.manager import RiskManager
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _settings(**overrides) -> Settings:
    base = {"ticker": "KRW-BTC", "strategy_k": 0.5, "ma_filter_window": 1}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _enriched(*, target: float, ma: float | None, ma_window: int = 1) -> pd.DataFrame:
    """마지막 행에 지정한 target·maN이 채워진 합성 DataFrame."""
    n = 3
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "open":   np.full(n, 100.0),
            "high":   np.full(n, 110.0),
            "low":    np.full(n, 90.0),
            "close":  np.full(n, 105.0),
            "volume": np.ones(n),
            "range":  np.full(n, 20.0),
            "target": np.full(n, target),
        },
        index=idx,
    )
    if ma is not None:
        df[f"ma{ma_window}"] = np.full(n, ma)
    return df


@pytest.fixture
def store(tmp_path):
    return OrderStore(tmp_path / "state.json")


def _make_bot(store, settings, notifier):
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                        min_request_interval=0.0)
    ticker = settings.ticker or "KRW-BTC"
    executor = OrderExecutor(client, store, ticker, live=False)
    return TradingBot(
        settings=settings, client=client,
        strategy=VolatilityBreakout(k=settings.strategy_k, ma_window=settings.ma_filter_window),
        risk_manager=RiskManager(settings),
        stores={ticker: store}, executors={ticker: executor},
        notifier=notifier,
    ), client


def test_watch_noop_when_empty_list(store, mocker):
    s = _settings(ticker="", watch_tickers="")  # 빈 메인 + 빈 watch → 목록 비어있음
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, _ = _make_bot(store, s, notifier)
    bot.watch()
    send.assert_not_called()


def test_watch_single_ticker_sends_one_message(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="")
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    bot.watch()
    send.assert_called_once()
    msg = send.call_args.args[0]
    assert msg.startswith("👀 watch")
    assert "KRW-BTC" in msg


def test_watch_rocket_marker_when_price_above_target(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="")
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    bot.watch()
    msg = send.call_args.args[0]
    assert "🚀" in msg  # 돌파
    assert "↑MA" in msg  # 현재가 > ma


def test_watch_dot_marker_when_below_target(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="")
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=105.0)
    mocker.patch.object(client, "get_current_prices", return_value={"KRW-BTC": 105.0})
    bot.watch()
    msg = send.call_args.args[0]
    assert "🚀" not in msg
    assert "↑MA" in msg  # 105 > ma(100)


def test_watch_down_ma_when_below_ma(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="")
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=200.0, ma=150.0))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    mocker.patch.object(client, "get_current_prices", return_value={"KRW-BTC": 120.0})
    bot.watch()
    msg = send.call_args.args[0]
    assert "↓MA" in msg


def test_watch_target_na_when_target_nan(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="")
    df = _enriched(target=np.nan, ma=100.0)
    mocker.patch("auto_coin.bot.fetch_daily", return_value=df)
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    bot.watch()
    msg = send.call_args.args[0]
    assert "target N/A" in msg


def test_watch_fetch_failure_row_rendered_and_others_continue(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="KRW-ETH")
    # BTC는 성공, ETH는 실패
    good_df = _enriched(target=110.0, ma=100.0)

    def _fetch_side(client, ticker, **kw):
        if ticker == "KRW-ETH":
            raise UpbitError("boom")
        return good_df

    mocker.patch("auto_coin.bot.fetch_daily", side_effect=_fetch_side)
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    mocker.patch.object(client, "get_current_prices",
                        return_value={"KRW-BTC": 120.0, "KRW-ETH": 120.0})
    bot.watch()
    msg = send.call_args.args[0]
    assert "KRW-BTC" in msg and "🚀" in msg
    assert "KRW-ETH" in msg and "fetch 실패" in msg


def test_watch_multiple_tickers_all_in_single_message(store, mocker):
    s = _settings(ticker="KRW-BTC", watch_tickers="KRW-ETH,KRW-XRP")
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    mocker.patch.object(client, "get_current_prices",
                        return_value={"KRW-BTC": 120.0, "KRW-ETH": 120.0, "KRW-XRP": 120.0})
    bot.watch()
    send.assert_called_once()
    msg = send.call_args.args[0]
    for t in ("KRW-BTC", "KRW-ETH", "KRW-XRP"):
        assert t in msg


def test_watch_ma_column_absent_omits_ma_mark(store, mocker):
    """ma_filter_window에 해당하는 컬럼이 없으면 ↑MA/↓MA 표기 생략."""
    s = _settings(ticker="KRW-BTC", watch_tickers="", ma_filter_window=999)  # ma999 컬럼 없음
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=None, ma_window=999))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send")
    bot, client = _make_bot(store, s, notifier)
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    mocker.patch.object(client, "get_current_prices", return_value={"KRW-BTC": 120.0})
    bot.watch()
    msg = send.call_args.args[0]
    assert "↑MA" not in msg
    assert "↓MA" not in msg
    assert "🚀" in msg  # target은 유효
