"""업비트 KRW 마켓 스캔 — 거래대금 상위 / 상장 검증.

Settings UI에서 종목을 추가할 때 ① 실존 검증 ② 거래대금 top 20 추천에 사용.
응답은 60초 TTL in-memory 캐시로 API 부담을 줄인다 (폼 여러 번 제출해도 안전).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyupbit
import requests

UPBIT_API = "https://api.upbit.com"
_CACHE_TTL = 60.0


@dataclass(frozen=True)
class TickerInfo:
    market: str           # "KRW-BTC"
    price: float
    volume_24h_krw: float
    change_rate: float    # signed, 0.012 == +1.2%


_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str) -> object | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    expires_at, value = hit
    if time.monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: object, ttl: float = _CACHE_TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def clear_cache() -> None:
    _cache.clear()


def list_krw_tickers() -> list[str]:
    cached = _cache_get("krw_markets")
    if isinstance(cached, list):
        return cached
    markets = pyupbit.get_tickers(fiat="KRW")
    tickers = [m for m in markets if isinstance(m, str) and m.startswith("KRW-")]
    _cache_set("krw_markets", tickers)
    return tickers


def is_listed(ticker: str) -> bool:
    if not ticker:
        return False
    return ticker.upper() in list_krw_tickers()


def validate_tickers(candidates: list[str]) -> tuple[list[str], list[str]]:
    """(존재, 미상장) 쌍 반환. 대문자 정규화."""
    listed = set(list_krw_tickers())
    ok, bad = [], []
    for t in candidates:
        normalized = t.strip().upper()
        if not normalized:
            continue
        (ok if normalized in listed else bad).append(normalized)
    return ok, bad


def top_by_volume(n: int = 20, *, exclude: set[str] | None = None) -> list[TickerInfo]:
    """24h 거래대금 상위 N종목 (KRW 마켓).

    외부 사용 빈도가 낮아 캐시는 60초만.
    """
    cached = _cache_get(f"top_{n}")
    if isinstance(cached, list):
        if exclude:
            return [t for t in cached if t.market not in exclude][:n]
        return cached[:n]

    markets = list_krw_tickers()
    rows: list[dict] = []
    for i in range(0, len(markets), 100):
        chunk = markets[i:i + 100]
        resp = requests.get(
            f"{UPBIT_API}/v1/ticker",
            params={"markets": ",".join(chunk)},
            timeout=10,
        )
        resp.raise_for_status()
        rows.extend(resp.json())
    rows.sort(key=lambda r: r.get("acc_trade_price_24h", 0), reverse=True)
    infos = [
        TickerInfo(
            market=r["market"],
            price=float(r.get("trade_price", 0)),
            volume_24h_krw=float(r.get("acc_trade_price_24h", 0)),
            change_rate=float(r.get("signed_change_rate", 0)),
        )
        for r in rows
    ]
    # 캐시는 전체 목록을 저장 (exclude는 호출마다 다를 수 있으니 후처리)
    _cache_set(f"top_{n}", infos[:max(n * 3, 60)])  # 여유분
    if exclude:
        infos = [t for t in infos if t.market not in exclude]
    return infos[:n]
