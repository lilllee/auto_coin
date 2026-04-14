"""웹 콘솔 엔트리포인트.

    python -m auto_coin.web                    # 기본: 127.0.0.1:8080
    python -m auto_coin.web --host 0.0.0.0     # 주의: Tailscale 없이 외부 노출 금지
    python -m auto_coin.web --port 9090

Tailscale 환경에서는 바인딩을 `0.0.0.0`으로 두어도 Tailscale 인터페이스 외에는
기본 차단되지만, 안전하게 로컬 바인딩(127.0.0.1)을 기본값으로 한다. 외부 접근 시엔
`--host 0.0.0.0` 명시 필요.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from auto_coin.runtime_guard import RuntimeGuardError, acquire_runtime_guard


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auto_coin.web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--reload", action="store_true", help="dev용 auto-reload")
    args = p.parse_args(argv)

    try:
        guard = acquire_runtime_guard("web")
    except RuntimeGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        uvicorn.run(
            "auto_coin.web.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
