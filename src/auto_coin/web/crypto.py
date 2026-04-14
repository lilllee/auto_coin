"""대칭키 암호화 래퍼 — DB에 저장되는 API 키 보호용.

마스터 키는 `~/.auto_coin_master.key` 파일에 저장 (600 권한).
파일이 없으면 자동 생성한다. 한 번 생성된 키는 절대 갱신되지 않아야 한다
(갱신하면 기존 암호문 복호화 불가).

DB에 저장되는 필드는 `<Fernet token>` 문자열. 빈 값은 평문 빈 문자열로 두어
구분 가능하게 한다.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger


def default_key_path() -> Path:
    """lazy 평가 — HOME 변경(테스트)을 반영하기 위해 매 호출 시 재계산."""
    return Path.home() / ".auto_coin_master.key"


class CryptoError(RuntimeError):
    pass


class SecretBox:
    """Fernet 래퍼.

    Use `.encrypt(str)` / `.decrypt(str)`. 빈 문자열은 그대로 통과(평문) —
    "저장된 적 없음"과 "빈 값으로 저장"을 구분할 수 있게.
    """

    def __init__(self, key_path: Path | None = None) -> None:
        self._path = Path(key_path) if key_path else default_key_path()
        self._fernet = Fernet(self._load_or_create_key())

    @property
    def key_path(self) -> Path:
        return self._path

    def _load_or_create_key(self) -> bytes:
        if self._path.exists():
            key = self._path.read_bytes().strip()
            if not key:
                raise CryptoError(f"master key file {self._path} is empty — delete it and restart to regenerate")
            return key
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        # 생성 시 600 권한으로 저장
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        except Exception:
            if self._path.exists():
                self._path.unlink()
            raise
        # 혹시 umask로 권한이 풀렸으면 강제 고정
        os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("generated new master key at {}", self._path)
        return key

    def encrypt(self, plaintext: str) -> str:
        if plaintext == "":
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        if ciphertext == "":
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise CryptoError(
                "failed to decrypt — master key mismatch or corrupted ciphertext"
            ) from exc

    @staticmethod
    def mask(value: str, *, tail: int = 4) -> str:
        """UI 표시용. 끝 4자리만 노출."""
        if not value:
            return ""
        if len(value) <= tail:
            return "•" * len(value)
        return "•" * (len(value) - tail) + value[-tail:]
