"""API 키 유효성 테스트 (저장 전 검증용).

Settings UI의 "테스트" 버튼이 호출한다. 성공/실패를 `CheckResult`로 래핑해
라우터가 UI 메시지로 포매팅.
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_coin.exchange.upbit_client import AssetBalance, UpbitClient, UpbitError
from auto_coin.formatting import format_price
from auto_coin.notifier.telegram import TelegramNotifier


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class HoldingRow:
    market: str
    quantity_text: str
    locked_text: str
    current_price_text: str
    avg_buy_price_text: str
    valuation_basis_text: str
    krw_value_text: str


@dataclass(frozen=True)
class HoldingsResult:
    ok: bool
    detail: str
    holdings: tuple[HoldingRow, ...] = ()


def _format_volume(value: float) -> str:
    return f"{value:,.8f}".rstrip("0").rstrip(".") or "0"


def _estimate_krw_value(asset: AssetBalance, current_price: float | None) -> float | None:
    if asset.currency == "KRW":
        return asset.total_volume
    if current_price is not None and current_price > 0:
        return asset.total_volume * current_price
    if asset.avg_buy_price > 0:
        return asset.total_volume * asset.avg_buy_price
    return None


def _valuation_basis(asset: AssetBalance, current_price: float | None) -> str:
    if asset.currency == "KRW":
        return "현금"
    if current_price is not None and current_price > 0:
        return "현재가"
    if asset.avg_buy_price > 0:
        return "평균매수가"
    return "미확인"


def _to_holding_row(asset: AssetBalance, current_price: float | None = None) -> HoldingRow:
    krw_value = _estimate_krw_value(asset, current_price)
    return HoldingRow(
        market=asset.market,
        quantity_text=_format_volume(asset.total_volume),
        locked_text=_format_volume(asset.locked) if asset.locked else "-",
        current_price_text=(
            "1"
            if asset.currency == "KRW"
            else (format_price(current_price) if current_price is not None and current_price > 0 else "-")
        ),
        avg_buy_price_text=format_price(asset.avg_buy_price) if asset.avg_buy_price > 0 else "-",
        valuation_basis_text=_valuation_basis(asset, current_price),
        krw_value_text=format_price(krw_value) if krw_value is not None else "-",
    )


def check_upbit(access_key: str, secret_key: str) -> CheckResult:
    if not access_key or not secret_key:
        return CheckResult(False, "키가 비어 있습니다")
    client = UpbitClient(
        access_key=access_key, secret_key=secret_key,
        max_retries=1, backoff_base=0.0, min_request_interval=0.0,
    )
    try:
        krw = client.get_krw_balance()
    except UpbitError as e:
        return CheckResult(False, f"인증 실패: {e}")
    return CheckResult(True, f"OK — KRW 잔고 {krw:,.0f}")


def fetch_upbit_holdings(access_key: str, secret_key: str) -> HoldingsResult:
    if not access_key or not secret_key:
        return HoldingsResult(False, "키가 비어 있습니다")
    client = UpbitClient(
        access_key=access_key, secret_key=secret_key,
        max_retries=1, backoff_base=0.0, min_request_interval=0.0,
    )
    try:
        holdings = client.get_holdings(include_krw=True)
    except UpbitError as e:
        return HoldingsResult(False, f"보유 코인 조회 실패: {e}")
    if not holdings:
        return HoldingsResult(True, "보유 중인 코인이 없습니다", ())

    markets = [asset.market for asset in holdings if asset.currency != "KRW"]
    current_prices: dict[str, float] = {}
    if markets:
        try:
            current_prices.update(client.get_current_prices(markets))
        except UpbitError:
            current_prices = {}

    total_krw_value = 0.0
    current_price_count = 0
    avg_buy_fallback_count = 0
    unresolved_count = 0
    rows_with_value: list[tuple[float, HoldingRow]] = []

    for asset in holdings:
        current_price = current_prices.get(asset.market) if asset.currency != "KRW" else None
        if asset.currency != "KRW" and current_price is None:
            try:
                current_price = client.get_current_price(asset.market)
            except UpbitError:
                current_price = None

        if asset.currency != "KRW":
            if current_price is not None and current_price > 0:
                current_price_count += 1
            elif asset.avg_buy_price > 0:
                avg_buy_fallback_count += 1
            else:
                unresolved_count += 1

        value = _estimate_krw_value(asset, current_price) or 0.0
        row = _to_holding_row(asset, current_price)
        total_krw_value += value
        rows_with_value.append((value, row))

    rows_with_value.sort(
        key=lambda item: (
            0 if item[1].market == "KRW" else 1,
            -item[0],
            item[1].market,
        )
    )
    rows = tuple(row for _, row in rows_with_value)

    detail = f"보유 자산 {len(rows)}개 · 총 평가 {format_price(total_krw_value)} KRW"
    if markets:
        detail += (
            f" · 현재가 {current_price_count}개"
            f" · 평균매수가 대체 {avg_buy_fallback_count}개"
        )
        if unresolved_count:
            detail += f" · 미확인 {unresolved_count}개"
    return HoldingsResult(True, detail, rows)


def check_telegram(bot_token: str, chat_id: str, *, send_probe: bool = False) -> CheckResult:
    if not bot_token:
        return CheckResult(False, "토큰이 비어 있습니다")
    n = TelegramNotifier(bot_token=bot_token, chat_id=chat_id or "0")
    info = n.check()
    if info is None:
        return CheckResult(False, "getMe 실패 — 토큰이 올바르지 않거나 네트워크 오류")
    if not chat_id:
        return CheckResult(True, f"@{info.username} (chat_id 미설정)")
    if send_probe:
        ok = n.send(f"[auto_coin] 연결 테스트 — @{info.username}")
        if ok:
            return CheckResult(True, f"@{info.username} — 테스트 메시지 전송 완료")
        return CheckResult(False, f"@{info.username} 인식, 메시지 전송 실패 (chat_id 확인 필요)")
    return CheckResult(True, f"@{info.username} 인식")
