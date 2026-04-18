"""SQLite 엔진 / 세션 관리.

전역 엔진 1개. sqlite는 스레드 안전성을 위해 `connect_args`에 `check_same_thread=False`.
APScheduler worker 스레드와 FastAPI 요청 스레드가 동시에 접근해도 안전하도록 함.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from auto_coin.web.models import default_db_path

_engine = None
_db_path: Path | None = None


def init_engine(db_path: Path | None = None) -> None:
    """프로세스 시작 시 한 번 호출. 테이블 생성 포함."""
    global _engine, _db_path
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = path
    _engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    SQLModel.metadata.create_all(_engine)
    _ensure_schema(_engine)


def reset_engine() -> None:
    """테스트용 — engine을 초기화하지 않은 상태로 되돌림."""
    global _engine, _db_path
    _engine = None
    _db_path = None


def engine():
    if _engine is None:
        raise RuntimeError("db engine not initialized — call init_engine() first")
    return _engine


def session() -> Iterator[Session]:
    """FastAPI Depends 호환 제너레이터."""
    with Session(engine()) as s:
        yield s


def db_path() -> Path:
    if _db_path is None:
        raise RuntimeError("db not initialized")
    return _db_path


def _ensure_schema(engine) -> None:
    """가벼운 in-place schema 보정.

    SQLModel의 create_all()은 기존 테이블에 새 컬럼을 추가하지 않으므로, 로컬 SQLite
    사용 환경에서 필요한 컬럼만 최소한으로 보정한다.
    """
    inspector = inspect(engine)
    if "user" not in inspector.get_table_names():
        return

    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "recovery_codes_enc" not in user_columns:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE user "
                    "ADD COLUMN recovery_codes_enc TEXT NOT NULL DEFAULT ''",
                ),
            )

    # TradeLog: decision_exit_price (live slippage 관측용, P2-3 패치)
    if "tradelog" in inspector.get_table_names():
        tradelog_columns = {c["name"] for c in inspector.get_columns("tradelog")}
        if "decision_exit_price" not in tradelog_columns:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE tradelog ADD COLUMN decision_exit_price REAL"),
                )

    # AppSettings: strategy_name / strategy_params_json (multi-strategy support)
    if "appsettings" in inspector.get_table_names():
        app_columns = {c["name"] for c in inspector.get_columns("appsettings")}
        with engine.begin() as conn:
            if "strategy_name" not in app_columns:
                conn.execute(
                    text(
                        "ALTER TABLE appsettings "
                        "ADD COLUMN strategy_name TEXT DEFAULT 'volatility_breakout'",
                    ),
                )
            if "strategy_params_json" not in app_columns:
                conn.execute(
                    text(
                        "ALTER TABLE appsettings "
                        "ADD COLUMN strategy_params_json TEXT DEFAULT ''",
                    ),
                )
            # WebSocket 실시간 가격 피드 설정
            if "use_websocket" not in app_columns:
                conn.execute(
                    text(
                        "ALTER TABLE appsettings "
                        "ADD COLUMN use_websocket BOOLEAN DEFAULT 0",
                    ),
                )
            # tick 주기 floor 보정: 5s 등 너무 짧은 값은 max_instances skip을 유발하므로
            # 30s 이상으로 강제 (P2-5). 30s 이상은 사용자 설정을 보존.
            if "check_interval_seconds" in app_columns:
                conn.execute(
                    text(
                        "UPDATE appsettings "
                        "SET check_interval_seconds = 30 "
                        "WHERE check_interval_seconds < 30",
                    ),
                )
