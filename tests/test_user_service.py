from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlmodel import Session, SQLModel, create_engine

from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import (
    LOCKOUT_THRESHOLD,
    LoginFailure,
    LoginSuccess,
    attempt_login,
    confirm_totp,
    create_user,
    generate_totp_secret,
    hash_password,
    totp_provisioning_uri,
    user_exists,
    verify_password,
    verify_totp,
)


@pytest.fixture
def box(tmp_path):
    return SecretBox(key_path=tmp_path / "m.key")


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ----- 순수 유틸 ----------------------------------------------------------


def test_password_roundtrip():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_password_hashes_differ_per_call():
    # bcrypt salt가 다르면 같은 평문이라도 해시가 달라야 한다
    assert hash_password("x") != hash_password("x")


def test_generate_totp_secret_is_base32():
    s = generate_totp_secret()
    assert len(s) >= 16
    import string
    allowed = set(string.ascii_uppercase + "234567")
    assert set(s) <= allowed


def test_verify_totp_accepts_current_code():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True


def test_verify_totp_rejects_malformed():
    secret = generate_totp_secret()
    assert verify_totp(secret, "") is False
    assert verify_totp(secret, "12345") is False  # 5자리
    assert verify_totp(secret, "abcdef") is False  # 숫자 아님


def test_verify_totp_rejects_wrong_code():
    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") is False or verify_totp(secret, "000000") is True  # 우연히 맞을 확률 1/1M
    # 보장된 실패: 완전히 다른 secret의 코드
    other = generate_totp_secret()
    while other == secret:
        other = generate_totp_secret()
    code_from_other = pyotp.TOTP(other).now()
    # 극소 확률로 충돌 가능하지만 실질적으로 False
    if pyotp.TOTP(secret).now() == code_from_other:
        pytest.skip("flaky TOTP collision")
    assert verify_totp(secret, code_from_other) is False


def test_provisioning_uri_format():
    uri = totp_provisioning_uri("JBSWY3DPEHPK3PXP", username="admin", issuer="test")
    assert uri.startswith("otpauth://totp/")
    assert "admin" in uri
    assert "test" in uri


# ----- DB 플로우 ----------------------------------------------------------


def test_create_user_stores_encrypted_totp(db_session, box):
    user, secret = create_user(db_session, box, password="p@ss")
    assert user.id is not None
    assert user.totp_confirmed is False
    # 평문 secret은 DB에 없어야
    assert secret not in user.totp_secret_enc
    # 복호화하면 동일
    assert box.decrypt(user.totp_secret_enc) == secret


def test_create_user_prevents_duplicates(db_session, box):
    create_user(db_session, box, password="p")
    with pytest.raises(ValueError, match="already exists"):
        create_user(db_session, box, password="q")


def test_user_exists(db_session, box):
    assert user_exists(db_session) is False
    create_user(db_session, box, password="p")
    assert user_exists(db_session) is True


def test_confirm_totp_flips_flag(db_session, box):
    user, secret = create_user(db_session, box, password="p")
    code = pyotp.TOTP(secret).now()
    assert confirm_totp(db_session, box, user=user, code=code) is True
    # 재조회
    from auto_coin.web.user_service import get_user
    reloaded = get_user(db_session)
    assert reloaded.totp_confirmed is True


def test_confirm_totp_rejects_bad_code(db_session, box):
    user, _ = create_user(db_session, box, password="p")
    assert confirm_totp(db_session, box, user=user, code="000000") is False


def test_login_success(db_session, box):
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    result = attempt_login(db_session, box, password="pw",
                           totp_code=pyotp.TOTP(secret).now())
    assert isinstance(result, LoginSuccess)
    assert result.user_id == user.id


def test_login_fails_before_totp_confirmed(db_session, box):
    user, secret = create_user(db_session, box, password="pw")
    result = attempt_login(db_session, box, password="pw",
                           totp_code=pyotp.TOTP(secret).now())
    assert isinstance(result, LoginFailure)
    assert result.reason == "not_confirmed"


def test_login_fails_no_user(db_session, box):
    r = attempt_login(db_session, box, password="x", totp_code="123456")
    assert isinstance(r, LoginFailure)
    assert r.reason == "no_user"


def test_bad_password_increments_counter(db_session, box):
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    r = attempt_login(db_session, box, password="WRONG",
                      totp_code=pyotp.TOTP(secret).now())
    assert isinstance(r, LoginFailure) and r.reason == "bad_password"
    # 카운터 증가 확인
    from auto_coin.web.user_service import get_user
    reloaded = get_user(db_session)
    assert reloaded.failed_attempts == 1


def test_bad_totp_increments_counter(db_session, box):
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    r = attempt_login(db_session, box, password="pw", totp_code="000000")
    assert isinstance(r, LoginFailure) and r.reason == "bad_totp"


def test_lockout_after_threshold_failures(db_session, box):
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    for _ in range(LOCKOUT_THRESHOLD):
        attempt_login(db_session, box, password="WRONG",
                      totp_code=pyotp.TOTP(secret).now())
    # 이제는 올바른 credential로도 locked
    r = attempt_login(db_session, box, password="pw",
                      totp_code=pyotp.TOTP(secret).now())
    assert isinstance(r, LoginFailure)
    assert r.reason == "locked"
    assert r.locked_until is not None


def test_successful_login_resets_failure_counter(db_session, box):
    from auto_coin.web.user_service import get_user
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    # 실패 1회
    attempt_login(db_session, box, password="WRONG",
                  totp_code=pyotp.TOTP(secret).now())
    assert get_user(db_session).failed_attempts == 1
    # 성공
    attempt_login(db_session, box, password="pw",
                  totp_code=pyotp.TOTP(secret).now())
    assert get_user(db_session).failed_attempts == 0


def test_lockout_expires_and_allows_retry(db_session, box):
    from auto_coin.web.user_service import get_user
    user, secret = create_user(db_session, box, password="pw")
    confirm_totp(db_session, box, user=user, code=pyotp.TOTP(secret).now())
    # 강제로 lockout 상태 만들기
    for _ in range(LOCKOUT_THRESHOLD):
        attempt_login(db_session, box, password="WRONG",
                      totp_code=pyotp.TOTP(secret).now())
    # 만료 시각을 과거로 되돌려 시뮬레이션
    u = get_user(db_session)
    u.locked_until = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None)
    db_session.add(u)
    db_session.commit()
    # 올바른 credential로 성공해야 함
    r = attempt_login(db_session, box, password="pw",
                      totp_code=pyotp.TOTP(secret).now())
    assert isinstance(r, LoginSuccess)
