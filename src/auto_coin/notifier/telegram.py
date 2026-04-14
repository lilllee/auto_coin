"""텔레그램 봇 알림.

`bot_token` 또는 `chat_id`가 비어 있으면 no-op으로 동작한다 (로그만 남김).
네트워크 실패도 raise하지 않고 로그로 흘려보낸다 — 알림 실패가 매매를 막아선 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from loguru import logger

DEFAULT_API = "https://api.telegram.org"


@dataclass(frozen=True)
class BotInfo:
    id: int
    username: str
    first_name: str


@dataclass(frozen=True)
class ChatHit:
    chat_id: int
    title: str  # username or full name or chat title
    last_text: str


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        timeout: float = 5.0,
        parse_mode: str | None = None,
        api_base: str = DEFAULT_API,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout
        self._parse_mode = parse_mode
        self._api = api_base.rstrip("/")

    # ----- state -----

    @property
    def enabled(self) -> bool:
        return bool(self._token) and bool(self._chat_id)

    @property
    def token_set(self) -> bool:
        return bool(self._token)

    def _url(self, method: str) -> str:
        return f"{self._api}/bot{self._token}/{method}"

    # ----- send -----

    def send(self, text: str) -> bool:
        """일반 메시지 전송. 실패 시 False 반환 (예외 raise 안 함)."""
        if not self.enabled:
            logger.debug("[telegram disabled] {}", text)
            return False
        payload: dict[str, str | int] = {"chat_id": self._chat_id, "text": text}
        if self._parse_mode:
            payload["parse_mode"] = self._parse_mode
        try:
            resp = requests.post(self._url("sendMessage"), json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("telegram send failed: {}", exc)
            return False
        if not resp.ok:
            logger.warning("telegram non-2xx: {} {}", resp.status_code, resp.text[:200])
            # parse_mode 문제면 plain text로 한 번 더 시도
            if self._parse_mode and resp.status_code == 400:
                return self._send_plain(text)
            return False
        return True

    def _send_plain(self, text: str) -> bool:
        try:
            resp = requests.post(
                self._url("sendMessage"),
                json={"chat_id": self._chat_id, "text": text},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("telegram plain fallback failed: {}", exc)
            return False
        return bool(resp.ok)

    # ----- diagnostics -----

    def check(self) -> BotInfo | None:
        """`getMe`로 토큰 유효성 확인. 성공 시 BotInfo, 실패 시 None."""
        if not self.token_set:
            logger.warning("telegram token not set")
            return None
        try:
            resp = requests.get(self._url("getMe"), timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("telegram getMe failed: {}", exc)
            return None
        if not resp.ok:
            logger.warning("telegram getMe non-2xx: {} {}", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        if not data.get("ok"):
            logger.warning("telegram getMe not ok: {}", data)
            return None
        r = data["result"]
        return BotInfo(id=r["id"], username=r.get("username", ""),
                       first_name=r.get("first_name", ""))

    def find_chat_ids(self, *, limit: int = 20) -> list[ChatHit]:
        """`getUpdates`로 최근 대화의 chat_id 추출.

        사용법:
            1) @BotFather로 봇 생성 → 토큰 복사
            2) 본인 텔레그램에서 해당 봇과 대화창 열고 아무 메시지나 전송
            3) 이 함수 호출 → 대화의 chat_id 확인
        """
        if not self.token_set:
            return []
        try:
            resp = requests.get(
                self._url("getUpdates"),
                params={"limit": limit},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("telegram getUpdates failed: {}", exc)
            return []
        if not resp.ok:
            logger.warning("telegram getUpdates non-2xx: {}", resp.status_code)
            return []
        data = resp.json()
        if not data.get("ok"):
            return []

        hits: dict[int, ChatHit] = {}
        for upd in data.get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat") or {}
            cid = chat.get("id")
            if cid is None:
                continue
            title = (
                chat.get("title")
                or chat.get("username")
                or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x).strip()
                or f"chat:{cid}"
            )
            hits[cid] = ChatHit(chat_id=int(cid), title=title, last_text=msg.get("text", "")[:80])
        return list(hits.values())
