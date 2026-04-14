"""/charts — 포트폴리오 종목의 일봉 변동 추이.

UI: 셀렉터로 ticker 선택 → Chart.js가 `/charts/data/{ticker}` JSON을 fetch.

차트 구성:
    - 종가 라인
    - target 라인 (오늘 target 수평선 또는 과거 target 라인)
    - MA(N) 라인
    - 보유 중이면 진입가 수평선 (context만 전달, JS에서 그림)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.data.candles import fetch_daily
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.executor.store import OrderStore
from auto_coin.web.auth import get_box, get_session_db, require_auth
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/charts", response_class=HTMLResponse)
def charts_index(
    request: Request,
    ticker: str | None = Query(default=None),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    s = load_runtime_settings(db, box)
    choices = list(dict.fromkeys(s.portfolio_ticker_list + s.watch_ticker_list))
    selected = (ticker or (choices[0] if choices else "")).upper()
    return templates.TemplateResponse(
        request=request, name="charts.html",
        context={"choices": choices, "selected": selected, "s": s},
    )


@router.get("/charts/data/{ticker}")
def charts_data(
    ticker: str,
    days: int = Query(default=60, ge=5, le=365),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    s = load_runtime_settings(db, box)
    client = UpbitClient(
        access_key=s.upbit_access_key.get_secret_value(),
        secret_key=s.upbit_secret_key.get_secret_value(),
        max_retries=2, backoff_base=0.2,
    )
    try:
        df = fetch_daily(
            client, ticker.upper(),
            count=max(days, s.ma_filter_window + 5),
            ma_window=s.ma_filter_window, k=s.strategy_k,
        )
    except UpbitError as exc:
        raise HTTPException(status_code=502, detail=f"업비트 시세 조회 실패: {exc}") from exc

    df = df.tail(days)  # 사용자가 지정한 days만 그림

    # 보유 중이면 진입가
    store = OrderStore(Path(s.state_dir) / f"{ticker.upper().replace('/', '_')}.json")
    state = store.load()
    entry_price = state.position.avg_entry_price if state.position else None

    ma_col = f"ma{s.ma_filter_window}"
    payload = {
        "ticker": ticker.upper(),
        "k": s.strategy_k,
        "ma_window": s.ma_filter_window,
        "entry_price": entry_price,
        "has_position": state.position is not None,
        "labels": [idx.strftime("%m-%d") for idx in df.index],
        "close": [_float_or_none(v) for v in df["close"].tolist()],
        "target": [_float_or_none(v) for v in df["target"].tolist()],
        "ma": [_float_or_none(v) for v in df[ma_col].tolist()] if ma_col in df.columns else [],
    }
    return JSONResponse(payload)


def _float_or_none(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    import math
    if math.isnan(f) or math.isinf(f):
        return None
    return f
