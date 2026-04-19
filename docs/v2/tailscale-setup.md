# Tailscale로 폰에서 auto_coin 웹 접속

외출 중 폰(iOS/Android)에서 맥에서 돌고 있는 auto_coin 웹 UI에 접속하는 방법.
추가 도메인·포트포워딩·SSL 구매 없이, **Tailscale 네트워크 내부에서 HTTPS 아닌 평문 HTTP**로
접근한다 (VPN 레이어가 암호화를 담당).

---

## 1. Tailscale 설치

### macOS (서버 역할 — 봇 돌아가는 맥)

```bash
brew install --cask tailscale
open /Applications/Tailscale.app
# 메뉴바 아이콘 → Log in → Google/GitHub 계정으로 로그인
# "Accept" 하면 이 머신이 Tailscale 네트워크에 참여
```

### iPhone / Android (클라이언트)

App Store / Play Store에서 **Tailscale** 설치 → 위와 **같은 계정**으로 로그인.
기본값으로 VPN 프로파일을 승인.

### 연결 확인

```bash
# 맥에서
tailscale status
# 나의 iPhone / MacBook 둘 다 online 보여야 함

# iPhone Safari에서 맥의 IP로 curl이 가능한지 간단 테스트
# http://<맥 Tailscale IP>:8080 접속
```

Tailscale IP는 `100.x.y.z` 형태. 또는 **MagicDNS**가 켜져 있으면
`http://<맥 호스트명>.<tailnet>.ts.net:8080`으로도 접근 가능.

---

## 2. auto_coin 바인딩 조정

기본값은 보안 위해 `127.0.0.1:8080`. Tailscale 내부에서 접근하려면 `0.0.0.0:8080`으로:

### 수동 실행 시
```bash
.venv/bin/python -m auto_coin.web --host 0.0.0.0 --port 8080
```

### launchd로 상시 실행 (권장)
`deploy/install_launchd.sh`가 `--host 0.0.0.0`을 포함해 실행하게 되어 있다.
재부팅 후 자동 기동 + 프로세스가 죽어도 자동 재시작.

```bash
./deploy/install_launchd.sh
# 검증
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
```

---

## 3. 보안 점검 ⚠️

`0.0.0.0` 바인딩은 잠재적으로 LAN 전체에 열릴 수 있다. 아래 전제를 확인:

### ✅ 켜져 있어야 하는 것
- **macOS 방화벽** ON (시스템 설정 → 네트워크 → 방화벽).
  Tailscale 인터페이스(`utun*`)는 기본 허용, 일반 Wi-Fi는 auto_coin Python 프로세스 차단 권장.
- **auto_coin 자체 인증** (V2.1 패스워드 + TOTP) — 네트워크 뚫려도 앱 레이어에서 한 번 더.
- **Tailscale ACL**에서 이 머신에 대한 접근을 **본인 소유 기기만** 허용.
  기본 개인 계정은 이미 그렇게 설정되어 있음 (team plan 아닌 이상).

### ❌ 피해야 할 것
- 공인 IP 노출 (cloudflared tunnel이나 reverse proxy 없이 `--host 0.0.0.0` + 포트포워딩 → **절대 금지**).
- `KILL_SWITCH=0` + live mode + 공개 접근 — 토큰 유출 시 자금 유출 위험.

### Tailscale만 통하게 강제하려면 (선택)

```bash
# Tailscale 인터페이스로만 바인딩
TAIL_IP=$(tailscale ip -4 | head -1)
.venv/bin/python -m auto_coin.web --host "$TAIL_IP" --port 8080
```

launchd plist의 `--host 0.0.0.0` 부분을 `--host 100.x.y.z`(본인 Tailscale IP)로 바꿔도 됨.
단, Tailscale IP는 가끔 변할 수 있어 동적으로 잡는 게 낫다.

---

## 4. 폰에서 접속

### URL 북마크
```
http://<맥 호스트명>.<tailnet>.ts.net:8080
```

예: `http://seungjuns-macbook-pro.tail-abcd1234.ts.net:8080`

### iOS Safari 팁
- 주소창 공유 버튼 → "홈 화면에 추가"로 아이콘화 (V2.8에서 PWA 지원 전에도 가능)
- 설정 → Safari → 자동 완성에 주소 추가

---

## 5. 트러블슈팅

### `/health`는 되는데 `/setup` 이 안 열린다
- 첫 접속이면 `/setup`에서 password + TOTP 등록 필요. "시스템 오류"면 launchd 로그 확인:
  ```bash
  tail -n 200 logs/launchd.err.log
  ```

### 접속이 너무 느림
- Tailscale 릴레이 노드(DERP)를 거치는 경우. 두 기기가 같은 네트워크 안에 있으면 직접 연결로 빨라짐.
- `tailscale ping <peer>` 로 경로 확인.

### 폰에서 전혀 접속 안 됨
1. `tailscale status`에서 상대 기기 online 확인
2. `curl -v http://<macbook ts.net name>:8080/health` (폰 대신 맥→맥 테스트)
3. macOS 방화벽에서 Python 프로세스 허용 확인
4. `launchctl list | grep auto_coin` — PID가 있어야 함. 없으면 `launchctl load ~/Library/LaunchAgents/auto_coin.plist`

### 맥이 잠자기 모드에 들어가면 연결 끊김
- `sudo pmset -a sleep 0`으로 자동 잠자기 끄거나,
- `caffeinate -i &` 같은 방법으로 화면 끈 채로 슬립 방지
- 가장 깔끔하려면 **라즈베리파이/VPS 같은 24/7 장치**에 auto_coin을 옮기는 것이 장기적으로 옳음

---

## 6. 다음 단계

Tailscale 기반 접근이 안정되면:
- **도메인 + HTTPS** — Tailscale Funnel 또는 Cloudflare Tunnel로 외부 공개 (주의 필요)
- **다중 사용자** — V2.x 확장 시 multi-user 인증 추가
- **VPS 이전** — 맥 slept/잠자기와 무관한 안정 운영

관련 문서:
- [Tailscale · MagicDNS](https://tailscale.com/kb/1081/magicdns)
- [Tailscale · ACL](https://tailscale.com/kb/1018/acls)
- [Tailscale · Funnel](https://tailscale.com/kb/1223/tailscale-funnel)
