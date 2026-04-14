"""일일 리포트 생성.

`State.orders`와 `State.position`에서 지난 24시간 거래 요약 텍스트를 만든다.
텔레그램/로그 어느 쪽이든 문자열만 넘기면 되도록 포매팅만 담당한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from auto_coin.executor.store import OrderRecord, State
from auto_coin.formatting import format_price


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _recent_orders(orders: list[OrderRecord], *, hours: int, now: datetime) -> list[OrderRecord]:
    cutoff = now - timedelta(hours=hours)
    out: list[OrderRecord] = []
    for o in orders:
        ts = _parse_iso(o.placed_at)
        if ts is None:
            continue
        if ts >= cutoff:
            out.append(o)
    return out


def build_daily_report(state: State, *, hours: int = 24, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    recent = _recent_orders(state.orders, hours=hours, now=now)
    n_buy = sum(1 for o in recent if o.side == "buy")
    n_sell = sum(1 for o in recent if o.side == "sell")

    # 매수/매도 페어링으로 개별 사이클 손익 계산 (순서대로 매칭)
    buys = [o for o in recent if o.side == "buy" and o.price]
    sells = [o for o in recent if o.side == "sell" and o.price]
    cycle_rets: list[float] = []
    for b, s in zip(buys, sells, strict=False):
        if b.price and s.price and b.price > 0:
            cycle_rets.append((s.price - b.price) / b.price)

    wins = sum(1 for r in cycle_rets if r > 0)
    win_rate = (wins / len(cycle_rets)) if cycle_rets else 0.0

    lines = [
        f"📊 Daily report (last {hours}h)",
        f"- orders: {len(recent)} (buy={n_buy}, sell={n_sell})",
        f"- closed cycles: {len(cycle_rets)}  wins={wins}  win_rate={win_rate*100:.1f}%",
        f"- daily_pnl: {state.daily_pnl_ratio*100:+.2f}%  (date={state.daily_pnl_date or '-'})",
    ]
    if cycle_rets:
        best = max(cycle_rets)
        worst = min(cycle_rets)
        lines.append(f"- best cycle: {best*100:+.2f}%   worst cycle: {worst*100:+.2f}%")

    pos = state.position
    if pos is not None:
        lines.append(
            f"- position: {pos.ticker} vol={pos.volume:.8f} entry={format_price(pos.avg_entry_price)}"
        )
    else:
        lines.append("- position: flat")
    return "\n".join(lines)
