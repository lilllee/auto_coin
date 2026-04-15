"""DailyCandleCache 단위 테스트."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from auto_coin.data.candle_cache import DailyCandleCache, _trading_day_key
from auto_coin.exchange.upbit_client import UpbitError

_KST = ZoneInfo("Asia/Seoul")


def _sample_df() -> pd.DataFrame:
    idx = pd.date_range("2026-04-10", periods=5, freq="D")
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 103, 104],
            "volume": [1, 1, 1, 1, 1],
        },
        index=idx,
    )


class TestTradingDayKey:
    def test_after_0900_returns_today(self):
        now = datetime(2026, 4, 16, 10, 0, tzinfo=_KST)
        assert _trading_day_key(now) == "2026-04-16"

    def test_before_0900_returns_yesterday(self):
        now = datetime(2026, 4, 16, 8, 59, tzinfo=_KST)
        assert _trading_day_key(now) == "2026-04-15"

    def test_exactly_0900_returns_today(self):
        now = datetime(2026, 4, 16, 9, 0, tzinfo=_KST)
        assert _trading_day_key(now) == "2026-04-16"

    def test_midnight_returns_yesterday(self):
        now = datetime(2026, 4, 16, 0, 0, tzinfo=_KST)
        assert _trading_day_key(now) == "2026-04-15"


class TestDailyCandleCache:
    def test_first_call_fetches(self, mocker):
        """첫 호출은 fetch_daily를 호출해야 한다."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        result = cache.get(
            client=object(),  # type: ignore[arg-type]
            ticker="KRW-BTC",
            count=200,
        )
        assert result is df
        fetch.assert_called_once()

    def test_second_call_uses_cache(self, mocker):
        """같은 거래일 내 두 번째 호출은 캐시를 사용해야 한다."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        result1 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        result2 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert result1 is result2
        assert fetch.call_count == 1  # 1회만 호출

    def test_different_tickers_fetch_separately(self, mocker):
        """다른 종목은 각각 fetch해야 한다."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        cache.get(client=object(), ticker="KRW-ETH", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 2

    def test_new_trading_day_refreshes(self, mocker):
        """거래일이 바뀌면 새로 fetch해야 한다."""
        df1 = _sample_df()
        df2 = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", side_effect=[df1, df2])

        # day1 캐시
        mocker.patch("auto_coin.data.candle_cache._trading_day_key", return_value="2026-04-16")
        cache = DailyCandleCache()
        result1 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert result1 is df1

        # day2로 변경
        mocker.patch("auto_coin.data.candle_cache._trading_day_key", return_value="2026-04-17")
        result2 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert result2 is df2
        assert fetch.call_count == 2

    def test_fetch_failure_uses_stale_cache(self, mocker):
        """fetch 실패 시 stale 캐시를 fallback으로 사용해야 한다."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()

        # 정상 캐시
        result1 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert result1 is df

        # 다음 거래일 — fetch 실패
        mocker.patch("auto_coin.data.candle_cache._trading_day_key", return_value="2026-04-17")
        fetch.side_effect = UpbitError("timeout")
        result2 = cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert result2 is df  # stale cache 반환

    def test_no_cache_and_fetch_failure_raises(self, mocker):
        """캐시도 없고 fetch도 실패하면 예외를 전파해야 한다."""
        mocker.patch("auto_coin.data.candle_cache.fetch_daily", side_effect=UpbitError("timeout"))
        cache = DailyCandleCache()
        with pytest.raises(UpbitError, match="timeout"):
            cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]

    def test_invalidate_single_ticker(self, mocker):
        """특정 종목만 무효화할 수 있어야 한다."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        cache.get(client=object(), ticker="KRW-ETH", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 2

        cache.invalidate("KRW-BTC")
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 3
        # ETH는 여전히 캐시됨
        cache.get(client=object(), ticker="KRW-ETH", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 3

    def test_invalidate_all(self, mocker):
        """전체 무효화."""
        df = _sample_df()
        fetch = mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        cache.get(client=object(), ticker="KRW-ETH", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 2

        cache.invalidate()
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        cache.get(client=object(), ticker="KRW-ETH", count=200)  # type: ignore[arg-type]
        assert fetch.call_count == 4

    def test_is_cached(self, mocker):
        """is_cached 확인."""
        df = _sample_df()
        mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=df)
        cache = DailyCandleCache()
        assert not cache.is_cached("KRW-BTC")
        cache.get(client=object(), ticker="KRW-BTC", count=200)  # type: ignore[arg-type]
        assert cache.is_cached("KRW-BTC")
        assert not cache.is_cached("KRW-ETH")
