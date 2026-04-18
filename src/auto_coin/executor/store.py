"""주문/포지션 상태 영속화.

JSON 파일 1개에 현재 보유 포지션과 최근 주문 기록을 저장한다.
재시작 시 `OrderStore.load()`로 복원한다.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Position:
    ticker: str
    volume: float
    avg_entry_price: float
    entry_uuid: str
    entry_at: str  # ISO8601


@dataclass(frozen=True)
class OrderRecord:
    uuid: str
    side: str  # "buy" / "sell"
    market: str
    krw_amount: float | None
    volume: float | None
    price: float | None
    placed_at: str  # ISO8601
    status: str  # "paper" / "placed" / "filled" / "failed"
    note: str = ""


@dataclass
class State:
    position: Position | None = None
    orders: list[OrderRecord] = field(default_factory=list)
    daily_pnl_ratio: float = 0.0
    daily_pnl_date: str = ""  # YYYY-MM-DD (UTC)
    last_exit_at: str = ""  # ISO8601 — 마지막 청산 시각 (쿨다운 기준)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


class OrderStore:
    """JSON 파일 기반 상태 저장소.

    원자적 저장(임시파일 + os.replace)으로 부분 쓰기를 방지한다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> State:
        if not self._path.exists():
            return State()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return State()
        pos_raw = raw.get("position")
        position = Position(**pos_raw) if pos_raw else None
        orders = [OrderRecord(**o) for o in raw.get("orders", [])]
        return State(
            position=position,
            orders=orders,
            daily_pnl_ratio=float(raw.get("daily_pnl_ratio", 0.0)),
            daily_pnl_date=raw.get("daily_pnl_date", ""),
            last_exit_at=raw.get("last_exit_at", ""),
        )

    def save(self, state: State) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "position": asdict(state.position) if state.position else None,
            "orders": [asdict(o) for o in state.orders],
            "daily_pnl_ratio": state.daily_pnl_ratio,
            "daily_pnl_date": state.daily_pnl_date,
            "last_exit_at": state.last_exit_at,
        }
        # 같은 디렉토리에 임시파일을 만들어 atomic replace
        fd, tmp_path = tempfile.mkstemp(prefix=".state-", dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def atomic_update(self, fn: Callable[[State], State]) -> State:
        """lock 하에서 load → fn(state) → save를 원자적으로 수행한다.

        같은 프로세스 내 동시 접근에 의한 lost-update를 방지한다.
        """
        with self._lock:
            state = self.load()
            new_state = fn(state)
            self.save(new_state)
            return new_state
