# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 리포지토리 현황

V1 (CLI 봇) + V2 (웹 콘솔)이 **모두 `main` 브랜치에 병합된 상태**. 현재 287/287 pytest 통과.

- V1 — `python -m auto_coin.main` (BlockingScheduler + 나눔 방식, nohup 배포)
- V2 — `python -m auto_coin.web` (FastAPI + BackgroundScheduler + HTMX UI, launchd 배포)
- 둘은 `.env` + `state/*.json` (종목별 포지션 파일) 을 **공유**. 동시 실행 금지.

코드 역사와 마일스톤은 [CHANGELOG.md](CHANGELOG.md) · [docs/v1/PLAN.md](docs/v1/PLAN.md) · [docs/v2/PLAN.md](docs/v2/PLAN.md)에 있다.

## 프로젝트 목적

업비트 Open API + `pyupbit` 기반 KRW 마켓 자동매매 봇. **변동성 돌파(Larry Williams)** 전략을 멀티 종목 포트폴리오에 적용.
검증 순서는 엄격히 **백테스트 → 페이퍼 → 소액 실거래**.

## 아키텍처 — 핵심 불변

```
Scheduler → Strategy(generate_signal) → RiskManager(Decision) → OrderExecutor → pyupbit
                 ↑                                                    ↓
             Market Data                                    Notifier/Logger/Store
```

### 모듈 경계 (깨지 말 것)

- **`strategy/`** — 순수 함수. 주문/네트워크/로깅을 직접 호출하지 않는다. 동일 입력 = 동일 출력 (백테스트/실거래 동일 코드).
- **`risk/manager.py`** — Executor **앞단 게이트**. 시그널이 여기를 통과해야 주문 가능. 손절은 BUY 시그널보다 최우선.
- **`exchange/upbit_client.py`** — `pyupbit` 유일한 import 지점. 다른 모듈은 래퍼만 사용 (거래소 교체/모킹 용이성).
- **`executor/store.py`** — JSON 원자적 저장. 재시작 시 자동 복구. DB 이관 안 함.
- **`backtest/runner.py`** — Executor 대체재. 같은 Strategy 객체를 과거 캔들에 적용.
- **`web/`** — V2 전용 패키지. V1 코드를 **수정하지 않고** 감싸는 구조. `web/bot_manager.py`가 `TradingBot`을 감싸 스케줄/재구성 담당.

## 실행 · 테스트 명령

```bash
# 의존성 설치 (venv 활성화 후)
pip install -e ".[dev]"

# V2 웹 콘솔 (권장)
python -m auto_coin.web --port 8080
python -m auto_coin.web --host 0.0.0.0 --port 8080   # Tailscale 포함 외부 바인딩

# V1 CLI
python -m auto_coin.main             # 무한 스케줄링
python -m auto_coin.main --once      # 1 tick 디버그
python -m auto_coin.main --live      # 실거래 강제 (주의)

# 백테스트
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --k 0.5
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --sweep 0.3 0.7 0.1

# 테스트
pytest                                    # 전체 (287건)
pytest tests/test_web_dashboard.py -v     # 단일 파일
pytest -k "test_kill_switch" -v           # 이름 필터

# 린트
ruff check src tests
```

### 주의: 테스트가 사용자 HOME에 파일을 남기지 않아야 함

V2 테스트는 `SecretBox` / `session_secret` 가 기본 경로에 파일을 생성할 수 있으므로,
fixture에서 반드시 `monkeypatch.setenv("HOME", str(tmp_path))` 처리 후 **lazy 경로 평가**(`default_key_path()`)가 동작해야 한다. 새 테스트 추가 시 이 관례 지킬 것. (기존 `app_env` fixture 모방하면 안전.)

## V2 작업 시 유의점

1. **`BotManager.reload()`는 lock-protected**. 테스트에서 상태 변경 확인 시 `with Session(web_db.engine())` 별도 세션으로 재조회.
2. **`TemplateResponse`는 starlette 1.0 시그니처** — `TemplateResponse(request=request, name="x.html", context={...})`. 옛 `("x.html", {"request": request, ...})`는 unhashable-dict 에러.
3. **Jinja2 macro는 keyword-only `*` 구문 미지원** — `{% macro f(a, b, c, type="x") %}` 이렇게만 쓸 것.
4. **FastAPI `Depends()`를 기본 인자로 쓰는 B008 경고는 무시** — pyproject.toml에서 ignore 처리됨.
5. **SSE 엔드포인트는 TestClient(sync)로 body 반복 읽기 어려움**. 헤더만 검증하고 실제 스트리밍은 수동 E2E로.

## 업비트/리스크 주의사항 (V1/V2 공통)

- JWT(HS256), 주문 시 `query_hash` + `query_hash_alg="SHA512"`. `secret_key`는 **Base64 디코드 없이** 원문 그대로 서명 키로 사용.
- API 키는 **출금 권한 반드시 비활성**, IP 화이트리스트 설정.
- V2는 키를 Fernet 암호화 후 DB 저장 (`~/.auto_coin_master.key`, 0600).
- 모든 주문에 UUID 멱등 식별자.
- 실거래 기본값 금지: `--live` 플래그 또는 V2 UI에서 `mode=live + live_trading + kill_switch OFF` 3중 조건.
- 체결/오류는 텔레그램 즉시 알림 필수. 조용히 실패하는 경로를 만들지 않는다.

## 문서 구조

```
README.md              # V2 기준 통합 사용자 가이드
CHANGELOG.md           # 버전별 구현 이력
CLAUDE.md              # (이 파일)
deploy/                # launchd plist + install script
docs/v1/               # V1 설계서 · CLI 운영 매뉴얼
docs/v2/               # V2 설계서 · Tailscale 가이드
reports/               # 운영 분석 (markdown, web에서 렌더됨)
```

## 기억할 운영 상수

| 항목 | 기본값 | 비고 |
|---|---|---|
| 1슬롯 투입 | 총자본 × 20% | `max_position_ratio` |
| 동시 보유 상한 | 3종목 | `max_concurrent_positions` |
| 일일 손실 한도 | −3% | 포트폴리오 합산 기준 |
| 개별 손절 | −2% | 종목별 진입가 기준 |
| 최소 주문 | 5,000 KRW | 업비트 floor |
| Kill-switch | `False` | True면 신규 진입 전면 차단, 청산은 허용 |
| tick 주기 | 60s | `check_interval_seconds` |
| 청산 시각 | 08:55 KST | `exit_hour_kst` + `exit_minute_kst` |
| 일일 리포트 | 08:58 KST | force_exit 이후, reset 이전 |
| 일일 리셋 | 09:00 KST | `daily_reset_hour_kst` |
| heartbeat | 6h | 0이면 비활성 |

## 작업 시 기본 자세

- PR 생성 전 `pytest` + `ruff check` 둘 다 green 확인.
- 새 기능 추가 시 **테스트 먼저/동시 작성**. 특히 V2 라우터는 TestClient로 설정 저장→DB 확인→reload 호출 여부까지 검증.
- 실거래 영향을 줄 수 있는 변경(riskmanager, executor)은 기존 페이퍼 테스트가 모두 green인 상태에서 소액 실거래 smoke 전에 절대 머지하지 말 것.
- CHANGELOG.md는 마일스톤 단위로 갱신. 누적 테스트 카운트 표도.
- **`docs/v2/PLAN.md`의 체크박스는 실제 구현 상태와 동기화**. 사용자 액션 대기 / TODO / 향후 강화는 구분해서 표기.
