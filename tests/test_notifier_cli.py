from __future__ import annotations

from auto_coin.notifier.__main__ import main as notifier_main
from auto_coin.notifier.telegram import BotInfo, ChatHit


def _patch_settings(mocker, token: str = "t", chat_id: str = "c"):
    from pydantic import SecretStr

    from auto_coin.config import Settings
    s = Settings(_env_file=None)
    s = s.model_copy(update={
        "telegram_bot_token": SecretStr(token),
        "telegram_chat_id": chat_id,
    })
    mocker.patch("auto_coin.notifier.__main__.load_settings", return_value=s)


def test_check_success(mocker, capsys):
    _patch_settings(mocker)
    mocker.patch(
        "auto_coin.notifier.__main__.TelegramNotifier.check",
        return_value=BotInfo(id=1, username="mybot", first_name="MyBot"),
    )
    assert notifier_main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "bot ok" in out
    assert "@mybot" in out


def test_check_no_token(mocker, capsys):
    _patch_settings(mocker, token="")
    assert notifier_main(["--check"]) == 2
    assert "empty" in capsys.readouterr().out


def test_check_invalid(mocker, capsys):
    _patch_settings(mocker)
    mocker.patch("auto_coin.notifier.__main__.TelegramNotifier.check", return_value=None)
    assert notifier_main(["--check"]) == 1


def test_find_chat_id_lists_hits(mocker, capsys):
    _patch_settings(mocker)
    mocker.patch(
        "auto_coin.notifier.__main__.TelegramNotifier.find_chat_ids",
        return_value=[ChatHit(chat_id=111, title="alice", last_text="hi")],
    )
    assert notifier_main(["--find-chat-id"]) == 0
    out = capsys.readouterr().out
    assert "chat_id=" in out
    assert "alice" in out


def test_find_chat_id_empty(mocker, capsys):
    _patch_settings(mocker)
    mocker.patch("auto_coin.notifier.__main__.TelegramNotifier.find_chat_ids", return_value=[])
    assert notifier_main(["--find-chat-id"]) == 1
    assert "no recent updates" in capsys.readouterr().out


def test_send_success(mocker, capsys):
    _patch_settings(mocker)
    mocker.patch("auto_coin.notifier.__main__.TelegramNotifier.send", return_value=True)
    assert notifier_main(["--send", "hello"]) == 0
    assert "sent" in capsys.readouterr().out


def test_send_disabled(mocker, capsys):
    _patch_settings(mocker, chat_id="")
    assert notifier_main(["--send", "hello"]) == 2
