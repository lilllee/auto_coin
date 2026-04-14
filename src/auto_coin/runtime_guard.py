"""V1 CLI / V2 web 동시 실행 방지 가드."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from loguru import logger

RuntimeMode = Literal["cli", "web"]


class RuntimeGuardError(RuntimeError):
    """다른 런타임이 이미 실행 중일 때 발생."""


@dataclass
class RuntimeGuard:
    mode: RuntimeMode
    lock_path: Path
    handle: TextIO

    def release(self) -> None:
        _unlock_file(self.handle)


def default_runtime_lock_path() -> Path:
    return Path.home() / ".auto_coin.runtime.lock"


def acquire_runtime_guard(mode: RuntimeMode, *, lock_path: Path | None = None) -> RuntimeGuard:
    path = lock_path or default_runtime_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")

    if not _try_lock_file(handle):
        owner = _read_lock_owner(handle)
        _unlock_file(handle, close_only=True)
        detail = f"mode={owner.get('mode', 'unknown')}, pid={owner.get('pid', 'unknown')}"
        raise RuntimeGuardError(
            f"another auto_coin runtime is already active ({detail}) — "
            "stop the other CLI/web process before starting this one",
        )

    handle.seek(0)
    handle.truncate()
    json.dump({"mode": mode, "pid": os.getpid()}, handle)
    handle.flush()
    os.fsync(handle.fileno())
    logger.info("runtime guard acquired ({}) at {}", mode, path)
    return RuntimeGuard(mode=mode, lock_path=path, handle=handle)


def _read_lock_owner(handle: TextIO) -> dict[str, object]:
    try:
        handle.seek(0)
        raw = handle.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _try_lock_file(handle: TextIO) -> bool:
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock_file(handle: TextIO, *, close_only: bool = False) -> None:
    import fcntl

    try:
        if not close_only:
            handle.seek(0)
            handle.truncate()
            handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
