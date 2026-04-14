"""텔레그램 설정 검증 CLI.

사용법:
    python -m auto_coin.notifier --check           # 토큰 유효성
    python -m auto_coin.notifier --find-chat-id    # 최근 대화의 chat_id 출력
    python -m auto_coin.notifier --send "hello"    # 현재 설정으로 전송
"""

from __future__ import annotations

import argparse
import sys

from auto_coin.config import load_settings
from auto_coin.notifier.telegram import TelegramNotifier


def _notifier() -> TelegramNotifier:
    s = load_settings()
    return TelegramNotifier(
        bot_token=s.telegram_bot_token.get_secret_value(),
        chat_id=s.telegram_chat_id,
    )


def cmd_check() -> int:
    n = _notifier()
    if not n.token_set:
        print("❌ TELEGRAM_BOT_TOKEN is empty — set it in .env")
        return 2
    info = n.check()
    if info is None:
        print("❌ getMe failed — token invalid or network error (see logs)")
        return 1
    print(f"✅ bot ok: id={info.id} username=@{info.username} name={info.first_name!r}")
    if not n.enabled:
        print("⚠️  TELEGRAM_CHAT_ID is empty — run with --find-chat-id to discover it")
    return 0


def cmd_find_chat_id() -> int:
    n = _notifier()
    if not n.token_set:
        print("❌ TELEGRAM_BOT_TOKEN is empty")
        return 2
    hits = n.find_chat_ids()
    if not hits:
        print("⚠️  no recent updates. Send any message to the bot from your Telegram "
              "account, then rerun. (Bots only see messages after they're added to a chat.)")
        return 1
    print(f"found {len(hits)} chat(s):")
    for h in hits:
        last = h.last_text.replace("\n", " ")
        print(f"  chat_id={h.chat_id:>14}  title={h.title!r}  last_text={last!r}")
    print("\nCopy the chat_id you want and set TELEGRAM_CHAT_ID in .env.")
    return 0


def cmd_send(text: str) -> int:
    n = _notifier()
    if not n.enabled:
        print("❌ notifier disabled (token or chat_id missing)")
        return 2
    ok = n.send(text)
    print("✅ sent" if ok else "❌ send failed (see logs)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auto_coin.notifier",
                                description="Telegram notifier configuration helper")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="validate bot token via getMe")
    g.add_argument("--find-chat-id", action="store_true",
                   help="list chat_ids from recent bot updates")
    g.add_argument("--send", metavar="TEXT", help="send a test message using current .env")
    args = p.parse_args(argv)

    if args.check:
        return cmd_check()
    if args.find_chat_id:
        return cmd_find_chat_id()
    return cmd_send(args.send)


if __name__ == "__main__":
    sys.exit(main())
