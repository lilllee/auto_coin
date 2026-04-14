from __future__ import annotations

import requests

from auto_coin.notifier.telegram import TelegramNotifier


def test_disabled_when_token_missing(mocker):
    n = TelegramNotifier(bot_token="", chat_id="123")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post")
    assert n.enabled is False
    assert n.send("hello") is False
    post.assert_not_called()


def test_disabled_when_chat_id_missing(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post")
    assert n.send("hello") is False
    post.assert_not_called()


def test_send_success(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c")  # 기본 parse_mode=None
    resp = mocker.Mock(ok=True, status_code=200, text="{}")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post", return_value=resp)
    assert n.send("hello") is True
    post.assert_called_once()
    args, kwargs = post.call_args
    assert kwargs["json"] == {"chat_id": "c", "text": "hello"}
    assert "timeout" in kwargs


def test_send_defaults_to_no_parse_mode(mocker):
    """기본은 plain text — Markdown 자동 해석으로 인한 400 노이즈 방지."""
    n = TelegramNotifier(bot_token="t", chat_id="c")
    resp = mocker.Mock(ok=True, status_code=200, text="{}")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post", return_value=resp)
    n.send("has _underscores_ and *stars*")
    assert "parse_mode" not in post.call_args.kwargs["json"]


def test_send_swallows_network_error(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c")
    mocker.patch("auto_coin.notifier.telegram.requests.post",
                 side_effect=requests.ConnectionError("nope"))
    assert n.send("hello") is False


def test_send_handles_non_2xx(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c")
    resp = mocker.Mock(ok=False, status_code=403, text="forbidden")
    mocker.patch("auto_coin.notifier.telegram.requests.post", return_value=resp)
    assert n.send("hello") is False


def test_send_with_explicit_parse_mode(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c", parse_mode="Markdown")
    resp = mocker.Mock(ok=True, status_code=200, text="{}")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post", return_value=resp)
    n.send("*hi*")
    assert post.call_args.kwargs["json"]["parse_mode"] == "Markdown"


def test_send_falls_back_to_plain_on_400(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c", parse_mode="Markdown")
    first = mocker.Mock(ok=False, status_code=400, text="bad markdown")
    second = mocker.Mock(ok=True, status_code=200, text="{}")
    post = mocker.patch("auto_coin.notifier.telegram.requests.post", side_effect=[first, second])
    assert n.send("*broken") is True
    # 두 번째 호출은 parse_mode 없음
    assert "parse_mode" not in post.call_args_list[1].kwargs["json"]


def test_check_returns_bot_info(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="c")
    resp = mocker.Mock(ok=True, status_code=200)
    resp.json.return_value = {"ok": True, "result": {"id": 42, "username": "mybot",
                                                     "first_name": "MyBot"}}
    mocker.patch("auto_coin.notifier.telegram.requests.get", return_value=resp)
    info = n.check()
    assert info is not None
    assert info.id == 42
    assert info.username == "mybot"


def test_check_returns_none_when_no_token():
    n = TelegramNotifier(bot_token="", chat_id="c")
    assert n.check() is None


def test_check_returns_none_on_network_error(mocker):
    import requests as rq
    n = TelegramNotifier(bot_token="t", chat_id="c")
    mocker.patch("auto_coin.notifier.telegram.requests.get",
                 side_effect=rq.ConnectionError("no network"))
    assert n.check() is None


def test_check_returns_none_on_invalid_token(mocker):
    n = TelegramNotifier(bot_token="bad", chat_id="c")
    resp = mocker.Mock(ok=False, status_code=401, text="Unauthorized")
    mocker.patch("auto_coin.notifier.telegram.requests.get", return_value=resp)
    assert n.check() is None


def test_find_chat_ids_extracts_unique_chats(mocker):
    n = TelegramNotifier(bot_token="t", chat_id="")
    resp = mocker.Mock(ok=True, status_code=200)
    resp.json.return_value = {
        "ok": True,
        "result": [
            {"message": {"chat": {"id": 111, "username": "alice"}, "text": "hi"}},
            {"message": {"chat": {"id": 111, "username": "alice"}, "text": "again"}},
            {"message": {"chat": {"id": 222, "first_name": "Bob", "last_name": "K"},
                         "text": "yo"}},
            {"channel_post": {"chat": {"id": -333, "title": "news"}, "text": "post"}},
        ],
    }
    mocker.patch("auto_coin.notifier.telegram.requests.get", return_value=resp)
    hits = n.find_chat_ids()
    ids = {h.chat_id for h in hits}
    assert ids == {111, 222, -333}
    alice = next(h for h in hits if h.chat_id == 111)
    assert alice.title == "alice"
    bob = next(h for h in hits if h.chat_id == 222)
    assert "Bob" in bob.title


def test_find_chat_ids_empty_when_no_token():
    n = TelegramNotifier(bot_token="", chat_id="")
    assert n.find_chat_ids() == []
