"""/kpi — 2주 paper 검증용 KPI 요약 라우터.

- GET /kpi        : HTML 페이지 (요약 카드 + 전략/종목/청산사유 테이블 + 일별 차트)
- GET /kpi/data   : JSON (HTMX/JS 갱신용)

period 프리셋: 7d / 14d / 30d / all. 라우터에서 기간 필터링 후 순수 서비스 함수에 전달.

DailySnapshot 기반 cumulative/MDD는 근사치이므로 `estimated_*` 명명을 사용하고, 화면에도
"추정치" 문구를 노출한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auto_coin.web import db as web_db
from auto_coin.web.auth import require_auth
from auto_coin.web.models import DailySnapshot, TradeLog
from auto_coin.web.services.kpi import compute_summary

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_ALLOWED_PERIODS = ("7d", "14d", "30d", "all")


def _period_window(period: str) -> tuple[date | None, date]:
    """period → (start_date_inclusive, end_date_inclusive). start=None이면 전체."""
    today = datetime.now(UTC).date()
    if period == "7d":
        return today - timedelta(days=6), today
    if period == "14d":
        return today - timedelta(days=13), today
    if period == "30d":
        return today - timedelta(days=29), today
    return None, today


def _load_trades(db: Session, start: date | None, end: date) -> list[TradeLog]:
    stmt = select(TradeLog)
    if start is not None:
        stmt = stmt.where(TradeLog.exit_at >= datetime.combine(start, datetime.min.time()))
    stmt = stmt.where(
        TradeLog.exit_at < datetime.combine(end + timedelta(days=1), datetime.min.time())
    )
    return list(db.exec(stmt).all())


def _load_snapshots(db: Session, start: date | None, end: date) -> list[DailySnapshot]:
    stmt = select(DailySnapshot)
    if start is not None:
        stmt = stmt.where(DailySnapshot.snapshot_date >= start)
    stmt = stmt.where(DailySnapshot.snapshot_date <= end)
    return list(db.exec(stmt).all())


def _normalize_period(period: str) -> str:
    return period if period in _ALLOWED_PERIODS else "14d"


@router.get("/kpi", response_class=HTMLResponse)
def kpi_page(
    request: Request,
    period: str = Query(default="14d"),
    _uid=Depends(require_auth),
):
    period = _normalize_period(period)
    return templates.TemplateResponse(
        request=request,
        name="kpi.html",
        context={"period": period, "periods": _ALLOWED_PERIODS},
    )


@router.get("/kpi/data")
def kpi_data(
    period: str = Query(default="14d"),
    _uid=Depends(require_auth),
):
    period = _normalize_period(period)
    start, end = _period_window(period)

    with Session(web_db.engine()) as db:
        trades = _load_trades(db, start, end)
        snapshots = _load_snapshots(db, start, end)

    label_map = {"7d": "최근 7일", "14d": "최근 14일", "30d": "최근 30일", "all": "전체 기간"}
    summary = compute_summary(trades, snapshots, label_map[period])

    payload = summary.to_dict()
    payload["period"] = period
    payload["window"] = {
        "start": start.isoformat() if start else None,
        "end": end.isoformat(),
    }
    return JSONResponse(payload)
