"""실시간 전략 상태판(Signal Board) 라우터.

- GET /signal-board           : 상태판 HTML 페이지
- GET /signal-board/data      : JSON 데이터 (HTMX/JS 갱신용)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.strategy import STRATEGY_LABELS
from auto_coin.web.auth import get_box, get_session_db, require_auth
from auto_coin.web.crypto import SecretBox
from auto_coin.web.services.signal_board import compute_signal_board
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _load_position_tickers(settings) -> set[str]:
    """state/*.json에서 현재 보유 중인 종목 set를 반환."""
    from auto_coin.executor.store import OrderStore
    position_tickers: set[str] = set()
    for ticker in settings.portfolio_ticker_list:
        try:
            store = OrderStore(ticker, state_dir=settings.state_dir)
            if store.state.has_position:
                position_tickers.add(ticker)
        except Exception:
            pass
    return position_tickers


def _load_strategy_params(settings) -> dict:
    if settings.strategy_params_json:
        try:
            return json.loads(settings.strategy_params_json)
        except json.JSONDecodeError:
            return {}
    if settings.strategy_name == "volatility_breakout":
        return {"k": settings.strategy_k, "ma_window": settings.ma_filter_window}
    return {}


@router.get("/signal-board", response_class=HTMLResponse)
def signal_board_page(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    return templates.TemplateResponse(
        request=request,
        name="signal_board.html",
        context={
            "strategy_name": settings.strategy_name,
            "strategy_label": STRATEGY_LABELS.get(settings.strategy_name, settings.strategy_name),
            "tickers": settings.portfolio_ticker_list + settings.watch_ticker_list,
        },
    )


@router.get("/signal-board/data")
def signal_board_data(
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    strategy_params = _load_strategy_params(settings)
    all_tickers = list(dict.fromkeys(settings.portfolio_ticker_list + settings.watch_ticker_list))
    position_tickers = _load_position_tickers(settings)

    client = UpbitClient(
        access_key=settings.upbit_access_key.get_secret_value(),
        secret_key=settings.upbit_secret_key.get_secret_value(),
        max_retries=settings.api_max_retries,
    )

    # 보유 종목 수 계산
    slot_used = len(position_tickers)

    try:
        result = compute_signal_board(
            client,
            strategy_name=settings.strategy_name,
            strategy_params=strategy_params,
            tickers=all_tickers,
            position_tickers=position_tickers,
            ma_window=settings.ma_filter_window,
            k=settings.strategy_k,
            slot_used=slot_used,
            slot_max=settings.max_concurrent_positions,
            kill_switch=settings.kill_switch,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"상태판 계산 실패: {exc}") from exc

    return JSONResponse(result.to_dict())
