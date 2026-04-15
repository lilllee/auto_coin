from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import pyupbit
from loguru import logger

T = TypeVar("T")


class UpbitError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrderResult:
    uuid: str
    side: str
    market: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class AssetBalance:
    currency: str
    unit_currency: str
    balance: float
    locked: float
    avg_buy_price: float

    @property
    def market(self) -> str:
        if self.currency == self.unit_currency:
            return self.currency
        return f"{self.unit_currency}-{self.currency}"

    @property
    def total_volume(self) -> float:
        return self.balance + self.locked


class UpbitClient:
    """`pyupbit` 래퍼.

    다른 모듈은 절대 `pyupbit`를 직접 import하지 말 것.
    재시도/레이트리밋/예외 정규화를 여기서 일괄 처리한다.
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        min_request_interval: float = 0.12,  # 업비트 권장 ~10 req/s
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_request_interval = min_request_interval
        self._last_request_at: float = 0.0
        self._upbit: pyupbit.Upbit | None = (
            pyupbit.Upbit(access_key, secret_key) if access_key and secret_key else None
        )

    @property
    def authenticated(self) -> bool:
        return self._upbit is not None

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_request_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _call(self, label: str, fn: Callable[[], T]) -> T:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                result = fn()
            except Exception as exc:  # pyupbit는 다양한 예외를 던짐
                last_exc = exc
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning("{} failed (attempt {}/{}): {} — retrying in {:.2f}s",
                               label, attempt, self._max_retries, exc, wait)
                time.sleep(wait)
                continue
            if isinstance(result, dict) and "error" in result:
                # pyupbit는 에러를 dict로 반환하기도 함
                err = result["error"]
                last_exc = UpbitError(f"{label} error: {err}")
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning("{} returned error (attempt {}/{}): {} — retrying in {:.2f}s",
                               label, attempt, self._max_retries, err, wait)
                time.sleep(wait)
                continue
            return result
        raise UpbitError(f"{label} failed after {self._max_retries} attempts") from last_exc

    # ----- public market data (no auth required) -----

    def get_current_price(self, ticker: str) -> float:
        price = self._call(f"get_current_price({ticker})",
                           lambda: pyupbit.get_current_price(ticker))
        if price is None:
            raise UpbitError(f"no price returned for {ticker}")
        return float(price)

    def get_current_prices(self, tickers: list[str]) -> dict[str, float]:
        """여러 종목의 현재가를 한 번에 조회.

        pyupbit.get_current_price()에 리스트를 전달하면 {ticker: price} dict를 반환한다.
        일부 종목이 None이면 해당 종목은 결과에서 제외한다.
        """
        if not tickers:
            return {}
        raw = self._call(
            f"get_current_price({len(tickers)} tickers)",
            lambda: pyupbit.get_current_price(tickers),
        )
        if raw is None:
            raise UpbitError(f"no prices returned for {tickers}")
        if isinstance(raw, dict):
            # 정상 케이스: {ticker: price}
            return {k: float(v) for k, v in raw.items() if v is not None}
        # 단건 fallback (리스트가 1개일 때 float 반환 가능)
        if isinstance(raw, (int, float)) and len(tickers) == 1:
            return {tickers[0]: float(raw)}
        raise UpbitError(f"unexpected response type for batch price: {type(raw)}")

    # ----- private (auth required) -----

    def _require_auth(self) -> pyupbit.Upbit:
        if self._upbit is None:
            raise UpbitError("Upbit credentials not configured")
        return self._upbit

    def get_krw_balance(self) -> float:
        upbit = self._require_auth()
        return float(self._call("get_balance(KRW)",
                                lambda: upbit.get_balance("KRW")) or 0.0)

    def get_coin_balance(self, ticker: str) -> float:
        upbit = self._require_auth()
        return float(self._call(f"get_balance({ticker})",
                                lambda: upbit.get_balance(ticker)) or 0.0)

    def get_holdings(self, *, include_zero: bool = False,
                     include_krw: bool = False) -> list[AssetBalance]:
        upbit = self._require_auth()
        raw_balances = self._call("get_balances", lambda: upbit.get_balances())
        if not isinstance(raw_balances, list):
            raise UpbitError(f"unexpected balances response: {raw_balances!r}")

        holdings: list[AssetBalance] = []
        for raw in raw_balances:
            if not isinstance(raw, dict):
                raise UpbitError(f"unexpected balance entry: {raw!r}")
            currency = str(raw.get("currency") or "").upper()
            unit_currency = str(raw.get("unit_currency") or "KRW").upper()
            balance = float(raw.get("balance") or 0.0)
            locked = float(raw.get("locked") or 0.0)
            avg_buy_price = float(raw.get("avg_buy_price") or 0.0)
            if not currency:
                continue
            asset = AssetBalance(
                currency=currency,
                unit_currency=unit_currency,
                balance=balance,
                locked=locked,
                avg_buy_price=avg_buy_price,
            )
            if not include_krw and asset.currency == "KRW":
                continue
            if not include_zero and asset.total_volume <= 0:
                continue
            holdings.append(asset)
        return sorted(holdings, key=lambda asset: asset.market)

    def buy_market(self, ticker: str, krw_amount: float) -> OrderResult:
        upbit = self._require_auth()
        raw = self._call(
            f"buy_market_order({ticker}, {krw_amount})",
            lambda: upbit.buy_market_order(ticker, krw_amount),
        )
        if not isinstance(raw, dict) or "uuid" not in raw:
            raise UpbitError(f"unexpected buy response: {raw!r}")
        return OrderResult(uuid=raw["uuid"], side="buy", market=ticker, raw=raw)

    def sell_market(self, ticker: str, volume: float) -> OrderResult:
        upbit = self._require_auth()
        raw = self._call(
            f"sell_market_order({ticker}, {volume})",
            lambda: upbit.sell_market_order(ticker, volume),
        )
        if not isinstance(raw, dict) or "uuid" not in raw:
            raise UpbitError(f"unexpected sell response: {raw!r}")
        return OrderResult(uuid=raw["uuid"], side="sell", market=ticker, raw=raw)

    def get_order(self, uuid: str) -> dict:
        """주문 UUID로 체결 상태 조회."""
        upbit = self._require_auth()
        raw = self._call(
            f"get_order({uuid})",
            lambda: upbit.get_order(uuid),
        )
        if not isinstance(raw, dict):
            raise UpbitError(f"unexpected order response: {raw!r}")
        return raw
