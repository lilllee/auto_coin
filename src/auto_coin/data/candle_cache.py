"""일봉 DataFrame 캐시.

같은 거래일(KST 09:00~다음날 08:59) 동안은 종목별 enriched DataFrame을
캐시해서 재사용한다. 09:00 KST 경계를 넘으면 자동 무효화.

API 호출 실패 시 stale cache를 fallback으로 사용할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from auto_coin.data.candles import fetch_daily
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError

_KST = ZoneInfo("Asia/Seoul")


def _trading_day_key(now: datetime | None = None) -> str:
    """현재 시각 기준 거래일 키를 반환.

    업비트 일봉 기준: 09:00 KST 이전이면 전일, 이후면 당일.
    반환 형식: "2026-04-16"
    """
    if now is None:
        now = datetime.now(_KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_KST)
    else:
        now = now.astimezone(_KST)

    if now.hour < 9:
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


@dataclass
class _CacheEntry:
    df: pd.DataFrame
    trading_day: str
    fetched_at: datetime
    stale: bool = False


class DailyCandleCache:
    """종목별 일봉 DataFrame 캐시.

    사용법:
        cache = DailyCandleCache()
        df = cache.get(client, ticker, count=250, ...)

    동일 거래일 내 두 번째 호출부터는 캐시된 df를 반환한다.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}

    def get(
        self,
        client: UpbitClient,
        ticker: str,
        *,
        count: int = 200,
        ma_window: int = 5,
        k: float = 0.5,
        strategy_name: str = "volatility_breakout",
        strategy_params: dict | None = None,
    ) -> pd.DataFrame:
        """캐시된 일봉 DataFrame을 반환. 필요 시 갱신."""
        current_day = _trading_day_key()
        entry = self._entries.get(ticker)

        # 캐시 유효: 같은 거래일이고 stale이 아니면 재사용
        if entry is not None and entry.trading_day == current_day and not entry.stale:
            return entry.df

        # 캐시 무효 또는 없음: 새로 fetch
        try:
            df = fetch_daily(
                client,
                ticker,
                count=count,
                ma_window=ma_window,
                k=k,
                strategy_name=strategy_name,
                strategy_params=strategy_params,
            )
            self._entries[ticker] = _CacheEntry(
                df=df,
                trading_day=current_day,
                fetched_at=datetime.now(_KST),
            )
            logger.debug("candle cache: {} refreshed for trading day {}", ticker, current_day)
            return df
        except UpbitError as exc:
            # stale cache fallback
            if entry is not None:
                logger.warning(
                    "candle cache: {} fetch failed, using stale cache "
                    "(day={}, fetched_at={}): {}",
                    ticker, entry.trading_day, entry.fetched_at, exc,
                )
                entry.stale = True
                return entry.df
            # 캐시도 없으면 예외를 그대로 전파
            raise

    def invalidate(self, ticker: str | None = None) -> None:
        """캐시 무효화. ticker 지정 시 해당 종목만, 없으면 전체."""
        if ticker is None:
            self._entries.clear()
        else:
            self._entries.pop(ticker, None)

    def is_cached(self, ticker: str) -> bool:
        """해당 종목의 유효한 캐시가 있는지 확인."""
        entry = self._entries.get(ticker)
        if entry is None:
            return False
        return entry.trading_day == _trading_day_key()

    @property
    def cached_tickers(self) -> list[str]:
        """현재 캐시된 종목 목록."""
        return list(self._entries.keys())
