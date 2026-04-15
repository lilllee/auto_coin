"""FastAPI 앱 생성.

`create_app()`이 유일한 진입점. uvicorn이 이 팩토리를 호출한다.

V2.1 범위: DB/bootstrap/BotManager + SessionMiddleware + /setup · /login · /logout +
보호된 홈 라우트.
"""

from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from auto_coin import __version__
from auto_coin.logging_setup import setup_logging
from auto_coin.web import db as web_db
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.csrf import CSRFMiddleware
from auto_coin.web.routers import auth as auth_router
from auto_coin.web.routers import charts as charts_router
from auto_coin.web.routers import control as control_router
from auto_coin.web.routers import dashboard as dashboard_router
from auto_coin.web.routers import logs as logs_router
from auto_coin.web.routers import reports as reports_router
from auto_coin.web.routers import review as review_router
from auto_coin.web.routers import settings as settings_router
from auto_coin.web.routers import signal_board as signal_board_router
from auto_coin.web.services import log_stream
from auto_coin.web.session_secret import load_or_create_session_secret
from auto_coin.web.settings_service import bootstrap_from_env, load_runtime_settings
from auto_coin.web.user_service import user_exists

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    log_stream.set_event_loop(_asyncio.get_running_loop())
    box = SecretBox()
    web_db.init_engine()
    with Session(web_db.engine()) as s:
        _, seeded = bootstrap_from_env(s, box)
        if seeded:
            logger.info("bootstrap: .env → SQLite migration done")
        settings = load_runtime_settings(s, box)
    setup_logging(level=settings.log_level, log_dir=Path(str(settings.log_dir)))
    log_sink_id = log_stream.install_sink(logger)
    logger.info(
        "auto_coin web v{} starting (mode={}, live={}, tickers={})",
        __version__, settings.mode.value, settings.is_live,
        ",".join(settings.portfolio_ticker_list),
    )

    manager = BotManager(box)
    app.state.box = box
    app.state.bot_manager = manager
    manager.start()
    try:
        yield
    finally:
        manager.stop()
        with contextlib.suppress(ValueError):
            logger.remove(log_sink_id)


def create_app() -> FastAPI:
    app = FastAPI(title="auto_coin", version=__version__, lifespan=lifespan)

    # 세션 쿠키 서명 키 — 파일 기반으로 프로세스 간 일관성 유지
    session_secret = load_or_create_session_secret()

    # CSRF 미들웨어 (inner — Session 안에서 동작)
    app.add_middleware(CSRFMiddleware)

    # SessionMiddleware (outer — CSRF보다 먼저 세션을 세팅)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="auto_coin_session",
        https_only=False,          # Tailscale 내부 HTTP 용도. 외부 노출 시 True로.
        same_site="lax",
        max_age=60 * 60 * 24 * 7,  # 7일
    )

    # 라우터
    app.include_router(auth_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(control_router.router)
    app.include_router(settings_router.router)
    app.include_router(charts_router.router)
    app.include_router(review_router.router)
    app.include_router(reports_router.router)
    app.include_router(logs_router.router)
    app.include_router(signal_board_router.router)

    # /health — 인증 없이 헬스체크
    @app.get("/health")
    def health():
        manager: BotManager = app.state.bot_manager
        s = manager.settings
        return {
            "status": "ok" if manager.running else "stopped",
            "version": __version__,
            "running": manager.running,
            "started_at": manager.started_at.isoformat() if manager.started_at else None,
            "mode": s.mode.value if s else None,
            "tickers": s.portfolio_ticker_list if s else [],
            "max_concurrent": s.max_concurrent_positions if s else None,
        }

    # 홈("/")은 dashboard 라우터에서 처리 (V2.4)

    # 전역 예외 처리
    from fastapi import HTTPException
    from fastapi import Request as _Req
    from fastapi.responses import JSONResponse

    def _wants_html(request: _Req) -> bool:
        accept = request.headers.get("accept", "")
        return ("text/html" in accept or "*/*" in accept) and not request.url.path.startswith("/health")

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: _Req, exc: HTTPException):
        # require_auth가 raise하는 303 예외를 실제 리다이렉트로 변환
        if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        # HTML 요청은 에러 페이지, 그 외는 JSON
        if _wants_html(request):
            return templates.TemplateResponse(
                request=request, name="error.html",
                context={"status_code": exc.status_code, "message": exc.detail or "오류가 발생했습니다"},
                status_code=exc.status_code,
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(404)
    async def not_found_handler(request: _Req, _exc):
        if _wants_html(request):
            return templates.TemplateResponse(
                request=request, name="error.html",
                context={"status_code": 404, "message": "페이지를 찾을 수 없습니다"},
                status_code=404,
            )
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 최초 기동 가이드: /로 오되 setup 필요하면 /setup
    @app.middleware("http")
    async def setup_first(request: Request, call_next):
        # /setup, /login, /logout, /health, /static 및 /setup/* 은 통과
        path = request.url.path
        if path.startswith(("/setup", "/login", "/logout", "/health", "/static", "/favicon")):
            return await call_next(request)
        # DB 보고 user 없으면 /setup으로
        with Session(web_db.engine()) as s:
            if not user_exists(s):
                return RedirectResponse("/setup", status_code=303)
        return await call_next(request)

    return app
