"""세션 쿠키 서명용 비밀키.

최초 기동 시 `~/.auto_coin_session.key`에 32바이트 랜덤 키 생성. 이후 재사용.
재생성하면 기존 세션이 전부 무효화되므로 파일을 삭제하지 말 것.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


def default_session_secret_path() -> Path:
    return Path.home() / ".auto_coin_session.key"


def load_or_create_session_secret(path: Path | None = None) -> str:
    p = path or default_session_secret_path()
    if p.exists():
        data = p.read_text(encoding="ascii").strip()
        if not data:
            raise RuntimeError(f"session secret file {p} is empty")
        return data
    p.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
    except Exception:
        if p.exists():
            p.unlink()
        raise
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    return token
