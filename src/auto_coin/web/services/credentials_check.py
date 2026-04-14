"""API 키 유효성 테스트 (저장 전 검증용).

Settings UI의 "테스트" 버튼이 호출한다. 성공/실패를 `CheckResult`로 래핑해
라우터가 UI 메시지로 포매팅.
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.notifier.telegram import TelegramNotifier


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


def check_upbit(access_key: str, secret_key: str) -> CheckResult:
    if not access_key or not secret_key:
        return CheckResult(False, "키가 비어 있습니다")
    client = UpbitClient(
        access_key=access_key, secret_key=secret_key,
        max_retries=1, backoff_base=0.0, min_request_interval=0.0,
    )
    try:
        krw = client.get_krw_balance()
    except UpbitError as e:
        return CheckResult(False, f"인증 실패: {e}")
    return CheckResult(True, f"OK — KRW 잔고 {krw:,.0f}")


def check_telegram(bot_token: str, chat_id: str, *, send_probe: bool = False) -> CheckResult:
    if not bot_token:
        return CheckResult(False, "토큰이 비어 있습니다")
    n = TelegramNotifier(bot_token=bot_token, chat_id=chat_id or "0")
    info = n.check()
    if info is None:
        return CheckResult(False, "getMe 실패 — 토큰이 올바르지 않거나 네트워크 오류")
    if not chat_id:
        return CheckResult(True, f"@{info.username} (chat_id 미설정)")
    if send_probe:
        ok = n.send(f"[auto_coin] 연결 테스트 — @{info.username}")
        if ok:
            return CheckResult(True, f"@{info.username} — 테스트 메시지 전송 완료")
        return CheckResult(False, f"@{info.username} 인식, 메시지 전송 실패 (chat_id 확인 필요)")
    return CheckResult(True, f"@{info.username} 인식")
