"""운영 리스크 대시보드 라우터.

- GET /risk : 리스크 현황 HTML
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.executor.store import OrderStore
from auto_coin.strategy import STRATEGY_LABELS
from auto_coin.web.auth import get_box, get_session_db, require_auth
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/risk", response_class=HTMLResponse)
def risk_dashboard(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    settings = load_runtime_settings(db, box)
    state_dir = Path(settings.state_dir)

    # 포지션 정보 수집
    positions = []
    for ticker in settings.portfolio_ticker_list:
        safe = ticker.replace("/", "_")
        try:
            store = OrderStore(state_dir / f"{safe}.json")
            state = store.load()
            pos = state.position
            positions.append({
                "ticker": ticker,
                "has_position": pos is not None,
                "entry_price": pos.avg_entry_price if pos else None,
                "volume": pos.volume if pos else None,
            })
        except Exception:
            positions.append({
                "ticker": ticker,
                "has_position": False,
                "entry_price": None,
                "volume": None,
            })

    slot_used = sum(1 for p in positions if p["has_position"])

    return templates.TemplateResponse(
        request=request,
        name="risk_dashboard.html",
        context={
            "settings": settings,
            "strategy_label": STRATEGY_LABELS.get(settings.strategy_name, settings.strategy_name),
            "positions": positions,
            "slot_used": slot_used,
            "slot_max": settings.max_concurrent_positions,
        },
    )
