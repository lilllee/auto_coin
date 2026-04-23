# Codex ↔ Claude 협업 프로토콜

이 폴더는 Codex(분석/설계/검토)와 Claude(구현/테스트/리포트)가 같은 작업 기억을 공유하기 위한 대화/인수인계 공간이다.

## 역할 분리

- **Codex**
  - 전략 가설 설계
  - 검증 기준/게이트 정의
  - Claude 구현 결과 리뷰
  - PASS / HOLD / REVISE / STOP 판정
  - 다음 구현 스펙 작성

- **Claude**
  - Codex 스펙 기반 구현
  - 테스트 작성/수정
  - 리포트 JSON 생성
  - 검증 명령 실행
  - 구현 결과를 이 폴더에 보고

## 대화 파일 규칙

- Codex → Claude 전달문: `codex-to-claude-NNNN-*.md`
- Claude → Codex 보고문: `claude-to-codex-NNNN-*.md`
- 현재 상태 요약: `state.md`

## 절대 규칙

1. live bot / paper trading / UI / KPI / settings 변경 금지 unless Codex가 명시적으로 허용.
2. walk-forward 금지 unless Stage 2가 PASS 후 Codex가 별도 승인.
3. 새 전략 실사용 금지 unless Stage 2 + walk-forward + paper/live readiness를 모두 통과.
4. reversion SMA 조기익절은 이번 계열에서 금지.
5. 결과는 항상 수수료/슬리피지 반영 기준으로 판단.
6. Claude는 구현 후 반드시 다음을 보고한다:
   - 변경 파일
   - 실행한 검증 명령과 결과
   - 생성 리포트 경로
   - 핵심 수치
   - PASS/HOLD/REVISE/STOP 자기판정
   - 알려진 한계
7. Codex는 Claude 결과를 그대로 믿지 않고 핵심 게이트/룩어헤드/집계를 재검토한다.

## 판정 기준

- **PASS**: 다음 단계로 진행 가능.
- **HOLD**: 아이디어는 보관하되 다음 단계 금지.
- **REVISE**: 제한된 범위에서 재설계/재검증.
- **STOP**: 해당 신호/전략 계열 중단.
