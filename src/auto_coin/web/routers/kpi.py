"""/kpi — 2주 paper 검증용 KPI 요약 라우터.

- GET /kpi               : HTML 페이지 (봇 로컬 로그 KPI + 업비트 원장 KPI 섹션)
- GET /kpi/data          : JSON (봇 로컬 TradeLog/DailySnapshot 기반)
- GET /kpi/ledger/data   : JSON (업비트 원장 paste/csv export 기반 — 별도 의미)
- POST /kpi/ledger/upload: paste 텍스트/CSV 업로드 (state/upbit_ledger_export.* 에 저장)

`/kpi/data` 와 `/kpi/ledger/data` 는 의미가 다르다:

- `/kpi/data` 는 봇이 직접 실행해서 ``TradeLog`` 에 적은 거래만 본다. 외부에서 업비트 앱
  으로 수동 매매하거나 DB가 비어 있던 시기의 거래는 보이지 않는다.
- `/kpi/ledger/data` 는 사용자가 업비트에서 받은 체결내역 (paste/CSV) 을 FIFO로 매칭한
  실제 계좌 기준 KPI 다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auto_coin.web import db as web_db
from auto_coin.web.auth import require_auth
from auto_coin.web.models import DailySnapshot, TradeLog
from auto_coin.web.services.kpi import compute_summary
from auto_coin.web.services.upbit_ledger_kpi import (
    compute_ledger_kpi,
    parse_korean_upbit_table,
)

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_ALLOWED_PERIODS = ("7d", "14d", "30d", "all")
_LEDGER_EXPORT_FILE = "upbit_ledger_export.txt"
_LEDGER_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB — 한 번에 paste 하기에 충분히 큼


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


# ---------------------------------------------------------------------------
# Upbit ledger KPI — 별도 엔드포인트 (의미 분리)
# ---------------------------------------------------------------------------

def _ledger_export_path() -> Path:
    """업로드된 paste 텍스트가 보관되는 경로.

    ``state/`` 아래에 두는 이유: 봇 데이터 디렉토리와 백업 정책을 공유하면서도
    DB 마이그레이션이 필요 없기 때문. 파일 자체는 재계산 캐시 — 손실돼도 사용자가
    다시 paste 해서 복구 가능. CWD 기준으로 ``state/upbit_ledger_export.txt``
    경로를 사용 (V1·V2 공통 관례).
    """
    return Path("state") / _LEDGER_EXPORT_FILE


def _empty_ledger_payload() -> dict:
    return {
        "available": False,
        "message": "아직 업비트 원장 데이터가 동기화/업로드되지 않았습니다.",
        "parsed_event_count": 0,
        "matched_trade_count": 0,
        "unmatched_buy_count": 0,
        "unmatched_sell_count": 0,
        "realized_pnl_krw": 0.0,
        "total_fee_krw": 0.0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": 0.0,
        "avg_pnl_ratio": 0.0,
        "cash_flow_krw": 0.0,
        "period_start": None,
        "period_end": None,
        "open_lots": [],
        "unmatched_sells": [],
        "matched_trades": [],
        "by_asset": [],
        "by_day": [],
        "notes": [],
    }


@router.get("/kpi/ledger/data")
def kpi_ledger_data(_uid=Depends(require_auth)):
    """업비트 원장 (사용자가 업로드한 paste/CSV) 기반 KPI 를 반환.

    파일이 없으면 ``available=false`` 의 명시적 빈 페이로드를 돌려준다 — 로컬
    TradeLog KPI 와 절대 섞이지 않도록 의미를 명확히 분리.
    """
    path = _ledger_export_path()
    if not path.exists():
        return JSONResponse(_empty_ledger_payload())

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return JSONResponse(
            {**_empty_ledger_payload(), "message": f"원장 파일 읽기 실패: {exc}"},
            status_code=500,
        )

    events = parse_korean_upbit_table(text, source=str(path))
    result = compute_ledger_kpi(events)
    payload = result.to_dict()
    payload["available"] = True
    payload["source_path"] = str(path)
    payload["uploaded_bytes"] = len(text.encode("utf-8"))
    return JSONResponse(payload)


@router.post("/kpi/ledger/upload")
def kpi_ledger_upload(
    paste: str = Form(...),
    _uid=Depends(require_auth),
):
    """업비트 한글 체결내역 paste 텍스트를 ``state/upbit_ledger_export.txt`` 에 저장.

    저장 후 곧바로 KPI 를 계산해서 반환 — UI 가 즉시 갱신할 수 있도록.
    크기 한도를 넘으면 413, 인식된 row가 0이면 422.
    """
    raw = paste.encode("utf-8")
    if len(raw) > _LEDGER_MAX_BYTES:
        raise HTTPException(status_code=413, detail="paste 가 너무 큽니다 (5 MiB 한도)")

    events = parse_korean_upbit_table(paste, source="upload")
    if not events:
        raise HTTPException(
            status_code=422,
            detail=(
                "인식된 거래 행이 없습니다. 업비트 한글 체결내역 (탭 또는 2칸 공백 "
                "구분, 헤더: 체결시간/코인/마켓/종류/거래수량/거래단가/거래금액/"
                "수수료/정산금액/주문시간) 을 그대로 붙여넣어 주세요."
            ),
        )

    path = _ledger_export_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(paste, encoding="utf-8")

    result = compute_ledger_kpi(events)
    payload = result.to_dict()
    payload["available"] = True
    payload["source_path"] = str(path)
    payload["uploaded_bytes"] = len(raw)
    return JSONResponse(payload)


@router.post("/kpi/ledger/clear")
def kpi_ledger_clear(_uid=Depends(require_auth)):
    """업로드된 paste 파일 삭제 (UI 에서 ‘초기화’ 버튼)."""
    path = _ledger_export_path()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"파일 삭제 실패: {exc}") from exc
    return JSONResponse(_empty_ledger_payload())
