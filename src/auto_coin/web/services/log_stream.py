"""loguru → in-memory ring buffer + SSE fan-out.

설계:
- 마지막 N개 라인을 deque에 보관 (재접속 시 재생용).
- 활성 asyncio.Queue 구독자가 있으면 각 라인을 fan-out.
- `install_sink(logger)`를 프로세스 시작 시 1회 호출.

loguru 워커 스레드(웹 요청 스레드 아님)가 sink를 호출하므로, asyncio.Queue에는
`put_nowait`만 쓰고 실패 시 조용히 drop (SSE 클라이언트가 따라오지 못하면 무시).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

BUFFER_SIZE = 500

_buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER_SIZE)
_subscribers: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True)
class LogLine:
    ts: str          # ISO8601 UTC
    level: str       # "INFO" / "WARNING" / ...
    name: str        # logger name (module)
    message: str


def install_sink(logger_instance) -> int:
    """loguru에 sink 추가. 반환값은 handler id (제거 시 logger.remove(id))."""
    def sink(record):
        r = record.record
        line = LogLine(
            ts=r["time"].astimezone(UTC).isoformat(timespec="seconds"),
            level=r["level"].name,
            name=r["name"],
            message=r["message"],
        )
        _push(asdict(line))

    return logger_instance.add(sink, level="DEBUG", format="{message}",
                               backtrace=False, diagnose=False, enqueue=False)


def _push(line: dict[str, Any]) -> None:
    _buffer.append(line)
    # active loop이 있으면 각 queue에 put_nowait (다른 스레드에서 호출되어도 안전하게)
    if _loop is None:
        return
    for q in list(_subscribers):
        # queue가 닫혔거나 가득찬 경우 — SSE 클라이언트가 못 따라오면 drop
        with contextlib.suppress(Exception):
            _loop.call_soon_threadsafe(q.put_nowait, line)


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """FastAPI lifespan에서 현재 event loop 등록."""
    global _loop
    _loop = loop


def current_buffer() -> list[dict[str, Any]]:
    return list(_buffer)


def subscribe() -> asyncio.Queue:
    """새 SSE 구독자. `unsubscribe()` 필수."""
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def format_sse(line: dict[str, Any]) -> str:
    return f"data: {json.dumps(line, ensure_ascii=False)}\n\n"


# ---- 테스트 편의용 -------------------------------------------------------


def reset_for_test() -> None:
    global _loop
    _buffer.clear()
    _subscribers.clear()
    _loop = None


def inject_line(level: str, name: str, message: str) -> None:
    """테스트/디버그용: sink를 거치지 않고 직접 버퍼에 라인 추가."""
    line = asdict(LogLine(
        ts=datetime.now(UTC).isoformat(timespec="seconds"),
        level=level, name=name, message=message,
    ))
    _push(line)
