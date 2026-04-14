from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from auto_coin.web.crypto import CryptoError, SecretBox


def test_generates_new_master_key_with_600_permissions(tmp_path):
    key_path = tmp_path / "master.key"
    box = SecretBox(key_path=key_path)
    assert key_path.exists()
    mode = stat.S_IMODE(os.stat(key_path).st_mode)
    assert mode == 0o600
    # 암/복호화 라운드트립
    assert box.decrypt(box.encrypt("hello")) == "hello"


def test_reuses_existing_key(tmp_path):
    key_path = tmp_path / "master.key"
    box1 = SecretBox(key_path=key_path)
    token = box1.encrypt("secret-api-key")
    # 새 SecretBox 인스턴스지만 같은 파일이면 같은 키 → 복호화 가능
    box2 = SecretBox(key_path=key_path)
    assert box2.decrypt(token) == "secret-api-key"


def test_empty_string_passthrough(tmp_path):
    box = SecretBox(key_path=tmp_path / "m.key")
    assert box.encrypt("") == ""
    assert box.decrypt("") == ""


def test_different_keys_fail_to_decrypt(tmp_path):
    a = SecretBox(key_path=tmp_path / "a.key")
    b = SecretBox(key_path=tmp_path / "b.key")
    token = a.encrypt("top-secret")
    with pytest.raises(CryptoError):
        b.decrypt(token)


def test_empty_master_key_file_raises(tmp_path):
    key_path = tmp_path / "empty.key"
    key_path.write_bytes(b"")
    with pytest.raises(CryptoError):
        SecretBox(key_path=key_path)


def test_mask_shows_only_last_four():
    assert SecretBox.mask("") == ""
    assert SecretBox.mask("abc") == "•••"
    assert SecretBox.mask("abcdefghijklmnop") == "••••••••••••mnop"
    assert SecretBox.mask("abcdefgh", tail=2) == "••••••gh"


def test_corrupted_ciphertext_raises(tmp_path):
    box = SecretBox(key_path=tmp_path / "m.key")
    with pytest.raises(CryptoError):
        box.decrypt("definitely-not-a-valid-token")


def test_large_value_roundtrip(tmp_path):
    box = SecretBox(key_path=tmp_path / "m.key")
    payload = "x" * 4096
    assert box.decrypt(box.encrypt(payload)) == payload


def test_master_key_path_is_accessible(tmp_path: Path):
    p = tmp_path / "m.key"
    box = SecretBox(key_path=p)
    assert box.key_path == p
