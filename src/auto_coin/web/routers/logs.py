"""/logs — 실시간 로그 뷰어.

GET /logs          → 초기 버퍼 + SSE 구독 UI
GET /logs/stream   → text/event-stream으로 새 로그 라인 push
GET /logs/recent   → JSON, 초기 렌더 / 모바일에서 새로고침 시 사용
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from auto_coin.web.auth import require_auth
from auto_coin.web.services import log_stream

router = APIRouter(prefix="/logs")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
def logs_page(request: Request, _uid=Depends(require_auth)):
    recent = log_stream.current_buffer()[-200:]
    return templates.TemplateResponse(
        request=request, name="logs.html",
        context={"initial_lines": recent},
    )


@router.get("/recent")
def logs_recent(limit: int = 200, _uid=Depends(require_auth)):
    limit = max(1, min(limit, log_stream.BUFFER_SIZE))
    return JSONResponse(log_stream.current_buffer()[-limit:])


@router.get("/stream")
async def logs_stream(request: Request, _uid=Depends(require_auth)):
    queue = log_stream.subscribe()

    async def event_source():
        try:
            # 연결 직후 즉시 flush (TestClient blocking + 프록시 버퍼링 방지)
            yield ": connected\n\n"
            # 초기 재생 (최근 50줄)
            for line in log_stream.current_buffer()[-50:]:
                yield log_stream.format_sse(line)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield log_stream.format_sse(line)
                except TimeoutError:
                    # keep-alive 코멘트 (SSE 표준)
                    yield ": keep-alive\n\n"
        finally:
            log_stream.unsubscribe(queue)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
