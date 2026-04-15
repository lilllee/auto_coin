"""전략 검토(review) 라우터.

- GET /review                : 최소 placeholder HTML
- GET /review/data/{ticker}  : review simulator JSON
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.review.reasons import (
    ALWAYS_SELL_REVIEW_STRATEGIES,
    ENTRY_ONLY_REVIEW_STRATEGIES,
    REVIEW_SELL_OVERRIDABLE,
)
from auto_coin.review.simulator import ReviewValidationError, run_review_simulation
from auto_coin.strategy import STRATEGY_LABELS
from auto_coin.web.auth import get_box, get_session_db, require_auth
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_KST = ZoneInfo("Asia/Seoul")


@router.get("/review", response_class=HTMLResponse)
def review_index(
    request: Request,
    ticker: str | None = Query(default=None),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    strategy_params = _load_strategy_params(settings)
    choices = _ticker_choices(settings)
    selected = (ticker or (choices[0] if choices else "")).upper()
    start_date, end_date = _default_review_dates()
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "choices": choices,
            "selected": selected,
            "strategy_name": settings.strategy_name,
            "strategy_label": STRATEGY_LABELS.get(settings.strategy_name, settings.strategy_name),
            "strategy_params": strategy_params,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "has_sell_override": settings.strategy_name in REVIEW_SELL_OVERRIDABLE,
            "is_entry_only": settings.strategy_name in ENTRY_ONLY_REVIEW_STRATEGIES,
            "is_always_sell": settings.strategy_name in ALWAYS_SELL_REVIEW_STRATEGIES,
        },
    )


@router.get("/review/data/{ticker}")
def review_data(
    ticker: str,
    start_date: str = Query(...),
    end_date: str = Query(...),
    include_sell: bool = Query(default=False),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    choices = _ticker_choices(settings)
    normalized_ticker = ticker.upper()
    if normalized_ticker not in choices:
        raise HTTPException(status_code=400, detail=f"unsupported ticker: {normalized_ticker}")

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD") from exc

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if (end - start).days + 1 > 90:
        raise HTTPException(status_code=400, detail="review range must be <= 90 days")

    yesterday = _today_kst() - timedelta(days=1)
    if end > yesterday:
        raise HTTPException(status_code=400, detail=f"end_date must be <= {yesterday.isoformat()}")

    strategy_params = _load_strategy_params(settings)
    client = UpbitClient(
        access_key=settings.upbit_access_key.get_secret_value(),
        secret_key=settings.upbit_secret_key.get_secret_value(),
        max_retries=settings.api_max_retries,
    )

    try:
        result = run_review_simulation(
            client,
            ticker=normalized_ticker,
            start_date=start,
            end_date=end,
            strategy_name=settings.strategy_name,
            strategy_params=strategy_params,
            ma_window=settings.ma_filter_window,
            k=settings.strategy_k,
            include_strategy_sell=include_sell,
        )
    except ReviewValidationError as exc:
        status_code = 404 if "no candles available" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except UpbitError as exc:
        raise HTTPException(status_code=502, detail=f"업비트 시세 조회 실패: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise HTTPException(status_code=500, detail=f"review simulation failed: {exc}") from exc

    return JSONResponse(result.to_dict())


def _ticker_choices(settings) -> list[str]:
    return list(dict.fromkeys(settings.portfolio_ticker_list + settings.watch_ticker_list))


def _default_review_dates() -> tuple[date, date]:
    end = _today_kst() - timedelta(days=1)
    start = end - timedelta(days=4)
    return start, end


def _today_kst() -> date:
    return datetime.now(_KST).date()


def _load_strategy_params(settings) -> dict:
    if settings.strategy_params_json:
        try:
            return json.loads(settings.strategy_params_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid strategy_params_json in settings") from exc
    if settings.strategy_name == "volatility_breakout":
        return {
            "k": settings.strategy_k,
            "ma_window": settings.ma_filter_window,
        }
    return {}
