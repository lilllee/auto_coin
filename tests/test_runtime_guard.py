from __future__ import annotations

import json

import pytest

from auto_coin.runtime_guard import (
    RuntimeGuardError,
    acquire_runtime_guard,
    default_runtime_lock_path,
)


def test_default_runtime_lock_path_uses_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_runtime_lock_path() == tmp_path / ".auto_coin.runtime.lock"


def test_acquire_runtime_guard_writes_and_clears_metadata(tmp_path):
    lock_path = tmp_path / "runtime.lock"
    guard = acquire_runtime_guard("cli", lock_path=lock_path)
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["mode"] == "cli"
        assert isinstance(payload["pid"], int)
    finally:
        guard.release()

    assert lock_path.read_text(encoding="utf-8") == ""


def test_acquire_runtime_guard_raises_when_lock_unavailable(tmp_path, monkeypatch):
    lock_path = tmp_path / "runtime.lock"

    monkeypatch.setattr("auto_coin.runtime_guard._try_lock_file", lambda _handle: False)
    monkeypatch.setattr(
        "auto_coin.runtime_guard._read_lock_owner",
        lambda _handle: {"mode": "web", "pid": 4242},
    )

    with pytest.raises(RuntimeGuardError) as exc:
        acquire_runtime_guard("cli", lock_path=lock_path)

    assert "mode=web" in str(exc.value)
    assert "pid=4242" in str(exc.value)
