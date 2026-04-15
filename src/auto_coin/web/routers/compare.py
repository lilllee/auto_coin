"""전략 비교(Compare) 라우터.

- GET /compare            : 비교 HTML
- GET /compare/data       : 여러 전략 비교 결과 JSON
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.review.simulator import ReviewValidationError, run_review_simulation
from auto_coin.strategy import STRATEGY_LABELS, get_strategy_names
from auto_coin.web.auth import get_box, get_session_db, require_auth
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_KST = ZoneInfo("Asia/Seoul")


@router.get("/compare", response_class=HTMLResponse)
def compare_page(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    tickers = list(dict.fromkeys(settings.portfolio_ticker_list + settings.watch_ticker_list))
    end = datetime.now(_KST).date() - timedelta(days=1)
    start_30 = end - timedelta(days=29)
    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={
            "tickers": tickers,
            "selected_ticker": tickers[0] if tickers else "",
            "strategy_names": get_strategy_names(),
            "strategy_labels": STRATEGY_LABELS,
            "current_strategy": settings.strategy_name,
            "start_date": start_30.isoformat(),
            "end_date": end.isoformat(),
        },
    )


@router.get("/compare/data")
def compare_data(
    ticker: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    tickers = list(dict.fromkeys(settings.portfolio_ticker_list + settings.watch_ticker_list))
    normalized = ticker.upper()
    if normalized not in tickers:
        raise HTTPException(status_code=400, detail=f"unsupported ticker: {normalized}")

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date format") from exc

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if (end - start).days + 1 > 90:
        raise HTTPException(status_code=400, detail="max 90 days")

    yesterday = datetime.now(_KST).date() - timedelta(days=1)
    if end > yesterday:
        raise HTTPException(status_code=400, detail=f"end_date must be <= {yesterday}")

    client = UpbitClient(
        access_key=settings.upbit_access_key.get_secret_value(),
        secret_key=settings.upbit_secret_key.get_secret_value(),
        max_retries=settings.api_max_retries,
    )

    results = []
    for strategy_name in get_strategy_names():
        try:
            result = run_review_simulation(
                client,
                ticker=normalized,
                start_date=start,
                end_date=end,
                strategy_name=strategy_name,
                ma_window=settings.ma_filter_window,
                k=settings.strategy_k,
                include_strategy_sell=True,
            )
            results.append({
                "strategy_name": strategy_name,
                "strategy_label": STRATEGY_LABELS.get(strategy_name, strategy_name),
                "buy_count": result.summary.buy_count,
                "sell_count": result.summary.sell_count,
                "event_count": result.summary.event_count,
                "realized_pnl_ratio": result.summary.realized_pnl_ratio,
                "unrealized_pnl_ratio": result.summary.unrealized_pnl_ratio,
                "total_pnl_ratio": result.summary.total_pnl_ratio,
                "last_position": result.summary.last_position["state"],
                "is_current": strategy_name == settings.strategy_name,
            })
        except (ReviewValidationError, UpbitError, Exception) as exc:
            results.append({
                "strategy_name": strategy_name,
                "strategy_label": STRATEGY_LABELS.get(strategy_name, strategy_name),
                "error": str(exc),
                "is_current": strategy_name == settings.strategy_name,
            })

    return JSONResponse({
        "ticker": normalized,
        "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "strategies": results,
    })
