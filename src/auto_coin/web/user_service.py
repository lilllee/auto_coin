"""인증 관련 비즈니스 로직.

단일 사용자 가정 (`username="admin"` 고정). 다중 사용자가 필요하면 나중에 확장.

함수 3가지 레이어:
1. 순수 유틸 (bcrypt / pyotp 래퍼) — 외부 의존 없이 테스트 가능
2. DB 헬퍼 (`create_user`, `verify_credentials`, `confirm_totp`) — Session 주입
3. 상수 (`LOCKOUT_THRESHOLD`, `LOCKOUT_DURATION`)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import pyotp
from sqlmodel import Session, select

from auto_coin.web.crypto import SecretBox
from auto_coin.web.models import User, _now

LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=10)


@dataclass(frozen=True)
class LoginFailure:
    reason: str  # "no_user" | "bad_password" | "bad_totp" | "locked" | "not_confirmed"
    locked_until: datetime | None = None  # "locked" 경우만


@dataclass(frozen=True)
class LoginSuccess:
    user_id: int


LoginResult = LoginSuccess | LoginFailure


# ----- 순수 유틸 -----------------------------------------------------------


def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("password must not be empty")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    if not plain or not password_hash:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def generate_totp_secret() -> str:
    """base32 seed 16자 이상."""
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def totp_provisioning_uri(secret: str, *, username: str, issuer: str = "auto_coin") -> str:
    """QR 코드로 인코딩할 otpauth:// URI."""
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


# ----- DB 헬퍼 -------------------------------------------------------------


def get_user(session: Session, username: str = "admin") -> User | None:
    return session.exec(select(User).where(User.username == username)).first()


def user_exists(session: Session, username: str = "admin") -> bool:
    return get_user(session, username) is not None


def create_user(
    session: Session, box: SecretBox, *,
    username: str = "admin", password: str,
) -> tuple[User, str]:
    """신규 사용자 생성. TOTP secret을 동시에 발급하지만 `totp_confirmed=False`로
    시작 — `confirm_totp()` 호출 후에야 로그인 가능.

    반환: (User, plaintext_totp_secret) — UI에서 QR 발급에 사용.
    """
    if user_exists(session, username):
        raise ValueError(f"user '{username}' already exists")
    totp_secret = generate_totp_secret()
    user = User(
        username=username,
        password_hash=hash_password(password),
        totp_secret_enc=box.encrypt(totp_secret),
        totp_confirmed=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user, totp_secret


def confirm_totp(session: Session, box: SecretBox, *, user: User, code: str) -> bool:
    """setup 마지막 단계 — 사용자가 QR 스캔 후 6자리 입력해 확인."""
    secret = box.decrypt(user.totp_secret_enc)
    if not verify_totp(secret, code):
        return False
    user.totp_confirmed = True
    session.add(user)
    session.commit()
    session.refresh(user)
    return True


def attempt_login(
    session: Session, box: SecretBox, *,
    username: str = "admin", password: str, totp_code: str,
) -> LoginResult:
    """로그인 시도. 실패 시 카운트 증가, lockout 도달 시 locked_until 설정."""
    user = get_user(session, username)
    if user is None:
        return LoginFailure("no_user")

    if user.locked_until is not None and user.locked_until > _now():
        return LoginFailure("locked", locked_until=user.locked_until)

    if not user.totp_confirmed:
        return LoginFailure("not_confirmed")

    # 자물쇠가 만료됐으면 풀고 시도
    if user.locked_until is not None and user.locked_until <= _now():
        user.locked_until = None
        user.failed_attempts = 0

    if not verify_password(password, user.password_hash):
        _record_failure(session, user)
        return LoginFailure("bad_password")

    secret = box.decrypt(user.totp_secret_enc)
    if not verify_totp(secret, totp_code):
        _record_failure(session, user)
        return LoginFailure("bad_totp")

    # 성공 — 카운터 리셋
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    session.add(user)
    session.commit()
    return LoginSuccess(user_id=user.id)


def _record_failure(session: Session, user: User) -> None:
    user.failed_attempts += 1
    if user.failed_attempts >= LOCKOUT_THRESHOLD:
        user.locked_until = (datetime.now(UTC) + LOCKOUT_DURATION).replace(tzinfo=None)
    session.add(user)
    session.commit()
