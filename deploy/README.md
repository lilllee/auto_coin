# deploy/

배포 스크립트·템플릿.

| 파일 | 용도 |
|---|---|
| `com.sj9608.auto_coin.plist` | macOS launchd 서비스 정의 (템플릿) |
| `install_launchd.sh` | 템플릿을 현재 프로젝트 경로로 치환해 `~/Library/LaunchAgents/`에 로드 |

## 한 줄 설치

```bash
./deploy/install_launchd.sh
```

## 검증

```bash
launchctl list | grep auto_coin
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
tail -f logs/launchd.out.log
```

## 정지 / 제거

```bash
launchctl unload ~/Library/LaunchAgents/com.sj9608.auto_coin.plist
rm ~/Library/LaunchAgents/com.sj9608.auto_coin.plist
```

## 외부(폰) 접근

Tailscale 설치 + 앱 측 `--host 0.0.0.0` 바인딩 필요. 자세한 내용은
[../docs/v2/tailscale-setup.md](../docs/v2/tailscale-setup.md).

## 주의

- `.venv` 가 없으면 launchd 로딩이 실패. 먼저 `python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
- `~/.auto_coin.db` / `~/.auto_coin_master.key` / `~/.auto_coin_session.key` 는 HOME에 저장.
  macOS 사용자 계정이 바뀌면 이 3개를 함께 이관해야 한다.
- `KEEP_ALIVE=true` 라 **비정상 종료 시 자동 재시작**. paper 모드에선 안전하지만 live
  모드에서 반복 크래시가 일어나면 텔레그램 알림으로 바로 인지하도록 주의.
