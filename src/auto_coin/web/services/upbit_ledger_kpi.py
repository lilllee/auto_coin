"""업비트 원장(체결/입출금) 기반 KPI — 순수 함수 모듈.

`web/services/kpi.py` (로컬 TradeLog/DailySnapshot 기반 KPI)와 의도적으로 분리한다.
이 모듈은 DB·네트워크에 의존하지 않는 순수 dataclass + 함수 묶음이며,
업비트 체결/입출금을 정규화한 ``LedgerEvent`` 시퀀스를 입력으로 받아
FIFO 매칭으로 실현손익/승률/수수료/미체결 보유분을 계산한다.

명명 규약 (의도적):

- "원장(ledger)"이라는 용어를 일관되게 사용 — 로컬 봇 ``TradeLog`` 기반 KPI와
  혼동하지 않도록 한다.
- BUY 비용 = ``gross + buy_fee`` (지불한 KRW). SELL 수익 = ``gross - sell_fee``
  (수령 KRW). 수수료는 양 다리에 모두 반영.
- KRW 입출금은 cash flow에만 영향, 거래 PnL에는 포함되지 않는다.
- 부분 매도는 매수 lot을 비율로 분할(FIFO) — 수수료도 비율 분할.
- 매칭되지 않은 buy = 미체결 보유분(open lot). 매칭되지 않은 sell = 경고 후
  realized KPI에서 제외.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

SIDE_BUY: Literal["buy"] = "buy"
SIDE_SELL: Literal["sell"] = "sell"
SIDE_DEPOSIT: Literal["deposit"] = "deposit"
SIDE_WITHDRAW: Literal["withdraw"] = "withdraw"

LedgerSide = Literal["buy", "sell", "deposit", "withdraw"]


@dataclass(frozen=True)
class LedgerEvent:
    """정규화된 업비트 원장 1행.

    - ``gross_krw``: 거래대금 (수량 × 단가). 입금/출금이면 KRW 금액 그대로.
    - ``fee_krw``: 거래 수수료 (KRW).
    - ``net_krw``: 정산금액. BUY=지불(gross+fee), SELL=수령(gross-fee),
      DEPOSIT=입금액, WITHDRAW=출금액(부호는 음수가 아닌 절댓값으로 보관).
    - ``source``: ``"upbit_api"`` / ``"manual_text"`` / ``"csv"`` 등.
    - ``raw``: 원본 페이로드(파서가 복원/디버깅에 쓰도록 보관). 기본 None.
    """

    timestamp: datetime
    asset: str
    market: str | None
    side: LedgerSide
    quantity: float
    price: float
    gross_krw: float
    fee_krw: float
    net_krw: float
    source: str
    raw: dict | None = None


@dataclass(frozen=True)
class MatchedTrade:
    """FIFO로 닫힌 1 lot."""

    asset: str
    buy_time: datetime
    sell_time: datetime
    quantity: float
    buy_net_krw: float
    sell_net_krw: float
    fee_krw: float
    pnl_krw: float
    pnl_ratio: float


@dataclass(frozen=True)
class OpenLot:
    """매칭되지 않은 매수 잔량."""

    asset: str
    buy_time: datetime
    quantity: float
    buy_net_krw: float       # 잔량 기준 비례 분할된 BUY 비용 (gross+fee 비율 분할)


@dataclass(frozen=True)
class UnmatchedSell:
    """대응하는 매수 lot이 없는 매도."""

    asset: str
    sell_time: datetime
    quantity: float
    sell_net_krw: float


@dataclass(frozen=True)
class AssetBreakdown:
    asset: str
    matched_count: int
    realized_pnl_krw: float
    fee_krw: float
    win_count: int
    loss_count: int


@dataclass(frozen=True)
class DailyBreakdown:
    date: date
    matched_count: int
    realized_pnl_krw: float
    fee_krw: float


@dataclass(frozen=True)
class LedgerKpiResult:
    """업비트 원장 기준 KPI 결과.

    - ``realized_pnl_krw``: FIFO로 닫힌 lot들의 실현 PnL 합 (수수료 반영).
    - ``win_rate``: 0~100 (정수가 아닌 float).
    - ``avg_pnl_ratio``: 닫힌 lot의 ratio 평균 (소수, 0.01 = 1%).
    - ``cash_flow_krw``: deposit - withdraw (양수=순입금).
    - ``period_start`` / ``period_end``: 가장 빠른/늦은 ``timestamp`` (이벤트 없으면 None).
    """

    parsed_event_count: int
    matched_trade_count: int
    unmatched_buy_count: int
    unmatched_sell_count: int
    realized_pnl_krw: float
    total_fee_krw: float
    win_count: int
    loss_count: int
    win_rate: float
    avg_pnl_ratio: float
    cash_flow_krw: float
    period_start: datetime | None
    period_end: datetime | None
    open_lots: list[OpenLot] = field(default_factory=list)
    unmatched_sells: list[UnmatchedSell] = field(default_factory=list)
    matched_trades: list[MatchedTrade] = field(default_factory=list)
    by_asset: list[AssetBreakdown] = field(default_factory=list)
    by_day: list[DailyBreakdown] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parsed_event_count": self.parsed_event_count,
            "matched_trade_count": self.matched_trade_count,
            "unmatched_buy_count": self.unmatched_buy_count,
            "unmatched_sell_count": self.unmatched_sell_count,
            "realized_pnl_krw": self.realized_pnl_krw,
            "total_fee_krw": self.total_fee_krw,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": self.win_rate,
            "avg_pnl_ratio": self.avg_pnl_ratio,
            "cash_flow_krw": self.cash_flow_krw,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "open_lots": [
                {
                    "asset": o.asset,
                    "buy_time": o.buy_time.isoformat(),
                    "quantity": o.quantity,
                    "buy_net_krw": o.buy_net_krw,
                }
                for o in self.open_lots
            ],
            "unmatched_sells": [
                {
                    "asset": u.asset,
                    "sell_time": u.sell_time.isoformat(),
                    "quantity": u.quantity,
                    "sell_net_krw": u.sell_net_krw,
                }
                for u in self.unmatched_sells
            ],
            "matched_trades": [
                {
                    "asset": m.asset,
                    "buy_time": m.buy_time.isoformat(),
                    "sell_time": m.sell_time.isoformat(),
                    "quantity": m.quantity,
                    "buy_net_krw": m.buy_net_krw,
                    "sell_net_krw": m.sell_net_krw,
                    "fee_krw": m.fee_krw,
                    "pnl_krw": m.pnl_krw,
                    "pnl_ratio": m.pnl_ratio,
                }
                for m in self.matched_trades
            ],
            "by_asset": [asdict(b) for b in self.by_asset],
            "by_day": [
                {
                    "date": b.date.isoformat(),
                    "matched_count": b.matched_count,
                    "realized_pnl_krw": b.realized_pnl_krw,
                    "fee_krw": b.fee_krw,
                }
                for b in self.by_day
            ],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# FIFO core
# ---------------------------------------------------------------------------

@dataclass
class _Lot:
    """내부 매칭용 가변 lot — quantity 와 net_krw(=gross+fee)를 함께 갉아낸다."""

    asset: str
    buy_time: datetime
    quantity: float
    net_krw: float


def _empty_result() -> LedgerKpiResult:
    return LedgerKpiResult(
        parsed_event_count=0,
        matched_trade_count=0,
        unmatched_buy_count=0,
        unmatched_sell_count=0,
        realized_pnl_krw=0.0,
        total_fee_krw=0.0,
        win_count=0,
        loss_count=0,
        win_rate=0.0,
        avg_pnl_ratio=0.0,
        cash_flow_krw=0.0,
        period_start=None,
        period_end=None,
    )


def compute_ledger_kpi(events: Iterable[LedgerEvent]) -> LedgerKpiResult:
    """``LedgerEvent`` 시퀀스로부터 FIFO 기반 KPI를 계산.

    매칭 규칙:

    - 자산별 시간순(timestamp 오름차순) 처리.
    - BUY → ``_Lot`` 큐에 enqueue. 비용 = ``gross_krw + fee_krw`` (= net_krw).
    - SELL → 큐 head부터 차례로 매칭. 부분 매도면 lot을 비율 분할.
    - 매칭 시 사용된 BUY 비용 = lot 비용을 (matched_qty / lot_qty) 비율로 분할.
    - SELL 수익 = ``gross_krw - fee_krw`` (= net_krw).
    - PnL = sell_proceeds_for_matched - buy_cost_for_matched.
    - 매도가 큐를 비우고 남으면 ``UnmatchedSell``으로 기록 후 realized 계산에서 제외.
    - 잔여 lot은 ``OpenLot``으로 보고.
    - DEPOSIT/WITHDRAW는 cash flow에만 반영.
    """

    events_sorted = sorted(events, key=lambda e: e.timestamp)
    if not events_sorted:
        return _empty_result()

    queues: dict[str, deque[_Lot]] = defaultdict(deque)
    matched: list[MatchedTrade] = []
    unmatched_sells: list[UnmatchedSell] = []
    cash_flow = 0.0
    notes: list[str] = []
    realized_pnl = 0.0
    total_fee = 0.0

    for ev in events_sorted:
        if ev.side == SIDE_BUY:
            if ev.quantity <= 0:
                notes.append(f"skip BUY with non-positive quantity at {ev.timestamp.isoformat()} ({ev.asset})")
                continue
            queues[ev.asset].append(_Lot(
                asset=ev.asset,
                buy_time=ev.timestamp,
                quantity=ev.quantity,
                net_krw=ev.net_krw,
            ))
            total_fee += ev.fee_krw

        elif ev.side == SIDE_SELL:
            if ev.quantity <= 0:
                notes.append(f"skip SELL with non-positive quantity at {ev.timestamp.isoformat()} ({ev.asset})")
                continue
            remaining = ev.quantity
            sell_net = ev.net_krw
            sell_fee = ev.fee_krw
            total_fee += sell_fee
            queue = queues[ev.asset]
            # SELL은 자산별 BUY queue에 대해 FIFO로 소진.
            while remaining > 1e-12 and queue:
                lot = queue[0]
                take = min(remaining, lot.quantity)
                lot_cost_take = lot.net_krw * (take / lot.quantity) if lot.quantity > 0 else 0.0
                # SELL 측은 잔량 비율로 분할.
                sell_proceeds_take = sell_net * (take / ev.quantity) if ev.quantity > 0 else 0.0
                sell_fee_take = sell_fee * (take / ev.quantity) if ev.quantity > 0 else 0.0
                # 이 매칭 row의 fee는 (이번 매수 lot이 처음 만들어질 때 이미 net_krw에 포함된
                # buy_fee 분 비례) + 이번 SELL fee 비례.
                # buy_fee 비례는 buy_cost(=net) 안에 이미 포함돼 있어 PnL 계산에서는 자동
                # 반영된다. fee_krw는 reporting 용도로 sell side fee + 비례 buy fee 추정치를 합산.
                # 단, buy 측 fee는 LedgerEvent 시점에 net_krw로 합쳐 들어왔으므로 raw에 따로
                # 보관하지 않은 한 분리 추정이 어렵다 → fee_krw 컬럼은 sell_fee_take만 보고.
                fee_for_match = sell_fee_take

                pnl = sell_proceeds_take - lot_cost_take
                ratio = (pnl / lot_cost_take) if lot_cost_take > 0 else 0.0
                matched.append(MatchedTrade(
                    asset=ev.asset,
                    buy_time=lot.buy_time,
                    sell_time=ev.timestamp,
                    quantity=take,
                    buy_net_krw=lot_cost_take,
                    sell_net_krw=sell_proceeds_take,
                    fee_krw=fee_for_match,
                    pnl_krw=pnl,
                    pnl_ratio=ratio,
                ))
                realized_pnl += pnl

                lot.quantity -= take
                lot.net_krw -= lot_cost_take
                remaining -= take
                if lot.quantity <= 1e-12:
                    queue.popleft()

            if remaining > 1e-12:
                # 매칭되지 않은 잔량 SELL. realized에서 제외.
                proceeds_unmatched = sell_net * (remaining / ev.quantity) if ev.quantity > 0 else 0.0
                unmatched_sells.append(UnmatchedSell(
                    asset=ev.asset,
                    sell_time=ev.timestamp,
                    quantity=remaining,
                    sell_net_krw=proceeds_unmatched,
                ))
                notes.append(
                    f"unmatched SELL leftover {remaining:.8f} {ev.asset} at {ev.timestamp.isoformat()} "
                    f"(no prior BUY in this dataset)"
                )

        elif ev.side == SIDE_DEPOSIT:
            cash_flow += ev.net_krw
        elif ev.side == SIDE_WITHDRAW:
            cash_flow -= ev.net_krw
        else:  # pragma: no cover - typing guard
            notes.append(f"unknown side at {ev.timestamp.isoformat()}: {ev.side!r}")

    # open lots
    open_lots: list[OpenLot] = []
    for asset, queue in queues.items():
        for lot in queue:
            if lot.quantity > 1e-12:
                open_lots.append(OpenLot(
                    asset=asset,
                    buy_time=lot.buy_time,
                    quantity=lot.quantity,
                    buy_net_krw=lot.net_krw,
                ))

    win_count = sum(1 for m in matched if m.pnl_krw > 0)
    loss_count = sum(1 for m in matched if m.pnl_krw <= 0)
    matched_count = len(matched)
    win_rate = (win_count / matched_count * 100.0) if matched_count else 0.0
    avg_pnl_ratio = (
        statistics.fmean(m.pnl_ratio for m in matched) if matched_count else 0.0
    )

    by_asset_bucket: dict[str, list[MatchedTrade]] = defaultdict(list)
    for m in matched:
        by_asset_bucket[m.asset].append(m)
    by_asset = sorted(
        (
            AssetBreakdown(
                asset=a,
                matched_count=len(rows),
                realized_pnl_krw=sum(r.pnl_krw for r in rows),
                fee_krw=sum(r.fee_krw for r in rows),
                win_count=sum(1 for r in rows if r.pnl_krw > 0),
                loss_count=sum(1 for r in rows if r.pnl_krw <= 0),
            )
            for a, rows in by_asset_bucket.items()
        ),
        key=lambda b: b.realized_pnl_krw,
        reverse=True,
    )

    by_day_bucket: dict[date, list[MatchedTrade]] = defaultdict(list)
    for m in matched:
        by_day_bucket[m.sell_time.date()].append(m)
    by_day = [
        DailyBreakdown(
            date=d,
            matched_count=len(rows),
            realized_pnl_krw=sum(r.pnl_krw for r in rows),
            fee_krw=sum(r.fee_krw for r in rows),
        )
        for d, rows in sorted(by_day_bucket.items())
    ]

    return LedgerKpiResult(
        parsed_event_count=len(events_sorted),
        matched_trade_count=matched_count,
        unmatched_buy_count=len(open_lots),
        unmatched_sell_count=len(unmatched_sells),
        realized_pnl_krw=realized_pnl,
        total_fee_krw=total_fee,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        avg_pnl_ratio=avg_pnl_ratio,
        cash_flow_krw=cash_flow,
        period_start=events_sorted[0].timestamp,
        period_end=events_sorted[-1].timestamp,
        open_lots=open_lots,
        unmatched_sells=unmatched_sells,
        matched_trades=matched,
        by_asset=by_asset,
        by_day=by_day,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Korean Upbit table parser
# ---------------------------------------------------------------------------

_KOREAN_HEADER_TOKENS = (
    "체결시간", "코인", "마켓", "종류", "거래수량", "거래단가",
    "거래금액", "수수료", "정산금액", "주문시간",
)

_BUY_TOKENS = ("매수", "buy", "BUY")
_SELL_TOKENS = ("매도", "sell", "SELL")


def _parse_korean_number(token: str) -> float:
    """``"1,234.567"`` / ``"-1,234"`` / ``"0.5 KRW"`` 같은 표기를 float로."""
    s = token.strip()
    # 통화/단위 접미사 제거
    for suffix in (" KRW", "KRW", " BTC", " ETH", " XRP", " DOGE", " SOL"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = s.replace(",", "")
    if not s or s in ("-", "—"):
        return 0.0
    return float(s)


def _parse_korean_datetime(token: str) -> datetime:
    """``"2026-04-14 15:32:11"`` / ``"2026-04-14T15:32:11"`` / 일자 only."""
    s = token.strip()
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    last_err: Exception | None = None
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError as exc:
            last_err = exc
            continue
    raise ValueError(f"unrecognized timestamp: {token!r} ({last_err})")


def _split_row(line: str) -> list[str]:
    """탭 우선, 없으면 2칸 이상 공백으로 split. 단일 공백은 보존."""
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    # 2칸 이상 공백으로 분리
    import re
    return [c.strip() for c in re.split(r"\s{2,}|\|", line) if c.strip()]


def parse_korean_upbit_table(text: str, *, source: str = "manual_text") -> list[LedgerEvent]:
    """업비트 한글 체결내역 table text를 ``LedgerEvent`` 목록으로 정규화.

    헤더 컬럼:

    ``체결시간 / 코인 / 마켓 / 종류 / 거래수량 / 거래단가 / 거래금액 / 수수료 / 정산금액 / 주문시간``

    탭/2칸 공백/파이프(``|``)를 허용한다. 헤더 행은 자동 식별 후 스킵.
    공란/주석(``#``)/빈 줄은 무시. 인식 불가 행은 silent skip 후 ``raw`` 보존된 row만 반환.
    """
    events: list[LedgerEvent] = []
    header_seen = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        cells = _split_row(line)
        if not cells:
            continue
        if not header_seen and any(tok in line for tok in _KOREAN_HEADER_TOKENS):
            header_seen = True
            continue
        if len(cells) < 8:
            continue
        # 표준 10컬럼 가정. 일부 export는 주문시간을 생략하기도 → 8/9/10 모두 허용.
        fill_time_s = cells[0]
        asset = cells[1].strip()
        market = cells[2].strip() or None
        kind = cells[3].strip()
        qty_s = cells[4]
        price_s = cells[5]
        gross_s = cells[6]
        fee_s = cells[7]
        net_s = cells[8] if len(cells) > 8 else cells[7]
        order_time_s = cells[9] if len(cells) > 9 else fill_time_s

        try:
            ts = _parse_korean_datetime(fill_time_s)
            quantity = _parse_korean_number(qty_s)
            price = _parse_korean_number(price_s)
            gross = _parse_korean_number(gross_s)
            fee = _parse_korean_number(fee_s)
            net = _parse_korean_number(net_s)
        except ValueError:
            # 해석 실패 row 는 skip
            continue

        if any(tok in kind for tok in _BUY_TOKENS):
            side: LedgerSide = SIDE_BUY
        elif any(tok in kind for tok in _SELL_TOKENS):
            side = SIDE_SELL
        else:
            continue

        events.append(LedgerEvent(
            timestamp=ts,
            asset=asset,
            market=market,
            side=side,
            quantity=quantity,
            price=price,
            gross_krw=gross,
            fee_krw=fee,
            net_krw=net,
            source=source,
            raw={
                "fill_time": fill_time_s,
                "order_time": order_time_s,
                "kind": kind,
                "raw_line": line,
            },
        ))
    return events


# ---------------------------------------------------------------------------
# Constructors for KRW deposit/withdraw (used by tests / scripts)
# ---------------------------------------------------------------------------

def krw_deposit(timestamp: datetime, amount: float, *, source: str = "manual_text") -> LedgerEvent:
    return LedgerEvent(
        timestamp=timestamp, asset="KRW", market=None, side=SIDE_DEPOSIT,
        quantity=amount, price=1.0, gross_krw=amount, fee_krw=0.0, net_krw=amount,
        source=source,
    )


def krw_withdraw(timestamp: datetime, amount: float, *, source: str = "manual_text") -> LedgerEvent:
    return LedgerEvent(
        timestamp=timestamp, asset="KRW", market=None, side=SIDE_WITHDRAW,
        quantity=amount, price=1.0, gross_krw=amount, fee_krw=0.0, net_krw=amount,
        source=source,
    )
