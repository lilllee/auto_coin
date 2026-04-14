import pytest

from auto_coin.config import Mode, Settings


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(_env_file=None)
    assert s.mode is Mode.PAPER
    assert s.live_trading is False
    assert s.kill_switch is False
    assert s.is_live is False
    assert s.ticker == "KRW-BTC"
    assert s.strategy_k == 0.5
    assert s.min_order_krw == 5000


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "1")
    monkeypatch.setenv("KILL_SWITCH", "0")
    monkeypatch.setenv("STRATEGY_K", "0.7")
    monkeypatch.setenv("TICKER", "KRW-ETH")
    s = Settings(_env_file=None)
    assert s.mode is Mode.LIVE
    assert s.live_trading is True
    assert s.is_live is True
    assert s.strategy_k == 0.7
    assert s.ticker == "KRW-ETH"


def test_kill_switch_blocks_live(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "1")
    monkeypatch.setenv("KILL_SWITCH", "1")
    s = Settings(_env_file=None)
    assert s.is_live is False


def test_invalid_k_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATEGY_K", "2.0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_min_order_krw_floor(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MIN_ORDER_KRW", "1000")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


# ---- watch_ticker_list ----

def test_watch_ticker_list_defaults_to_main_only():
    s = Settings(_env_file=None)
    assert s.watch_ticker_list == ["KRW-BTC"]


def test_watch_ticker_list_merges_main_and_watch():
    s = Settings(_env_file=None, ticker="KRW-BTC", watch_tickers="KRW-ETH,KRW-XRP")
    assert s.watch_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-XRP"]


def test_watch_ticker_list_dedupes_main_if_present_in_watch():
    s = Settings(_env_file=None, ticker="KRW-BTC", watch_tickers="KRW-ETH,KRW-BTC,KRW-SOL")
    assert s.watch_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-SOL"]


def test_watch_ticker_list_uppercases_and_trims_whitespace():
    s = Settings(_env_file=None, ticker="KRW-BTC",
                 watch_tickers="  krw-eth , KRW-xrp  ,krw-sol")
    assert s.watch_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]


def test_watch_ticker_list_skips_empty_tokens():
    s = Settings(_env_file=None, ticker="KRW-BTC", watch_tickers=",,KRW-ETH,,,")
    assert s.watch_ticker_list == ["KRW-BTC", "KRW-ETH"]


def test_watch_interval_validation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, watch_interval_minutes=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, watch_interval_minutes=1441)


# ---- portfolio_ticker_list ----

def test_portfolio_falls_back_to_ticker_when_tickers_empty():
    s = Settings(_env_file=None, ticker="KRW-BTC", tickers="")
    assert s.portfolio_ticker_list == ["KRW-BTC"]


def test_portfolio_uses_tickers_when_set():
    s = Settings(_env_file=None, ticker="KRW-BTC",
                 tickers="KRW-ETH,KRW-XRP,KRW-SOL")
    # tickers가 있으면 ticker는 무시 — 명시 목록이 우선
    assert s.portfolio_ticker_list == ["KRW-ETH", "KRW-XRP", "KRW-SOL"]


def test_portfolio_preserves_order():
    """진입 우선순위는 나열 순서대로 결정되므로 순서 보존이 핵심."""
    s = Settings(_env_file=None, tickers="KRW-DOGE,KRW-BTC,KRW-ETH")
    assert s.portfolio_ticker_list == ["KRW-DOGE", "KRW-BTC", "KRW-ETH"]


def test_portfolio_dedupes_and_normalizes_case():
    s = Settings(_env_file=None, tickers="krw-btc, KRW-ETH , krw-btc,  KRW-XRP")
    assert s.portfolio_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-XRP"]


def test_portfolio_empty_when_both_blank():
    s = Settings(_env_file=None, ticker="", tickers="")
    assert s.portfolio_ticker_list == []


def test_watch_ticker_list_includes_full_portfolio():
    """watch는 매매 대상 전체 + 관측 전용."""
    s = Settings(_env_file=None, tickers="KRW-BTC,KRW-ETH",
                 watch_tickers="KRW-SOL,KRW-DOGE")
    assert s.watch_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-DOGE"]


def test_cooldown_minutes_default():
    s = Settings(_env_file=None)
    assert s.cooldown_minutes == 30


def test_cooldown_minutes_zero_disabled():
    """cooldown_minutes=0은 비활성을 의미하며 유효한 값이다."""
    s = Settings(_env_file=None, cooldown_minutes=0)
    assert s.cooldown_minutes == 0


def test_cooldown_minutes_validation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, cooldown_minutes=-1)
    with pytest.raises(ValueError):
        Settings(_env_file=None, cooldown_minutes=1441)


def test_max_concurrent_positions_validation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_concurrent_positions=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_concurrent_positions=21)
