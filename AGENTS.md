# Project rules

- 기본 응답은 한국어로 한다.
- 수정 전 어떤 파일을 왜 바꾸는지 먼저 설명한다.
- 한국어 UI 문자열은 사용자 승인 없이 수정하지 않는다.
- 관련 없는 파일은 수정하지 않는다.
- 전체 파일 재포맷 금지.
- 최소 수정만 한다.
- 저장 후 바로 반영되는 구조이므로 안전하게 수정한다.
- 수정 후 사용자가 확인할 체크 포인트를 알려준다.

## File change discipline
- 수정 전 반드시 **변경될 파일 목록을 먼저 제시한다.**
- 작업 범위 밖의 파일은 수정하지 않는다.
- 대형 파일(view.html, view_ui.js 등)은 필요한 부분만 최소 수정한다.

## Encoding safety
- 프로젝트는 UTF-8 기반이다.
- 깨진 한글 문자열이 보이면 임의 복구하지 않는다.
- 의심되는 문자열은 사용자에게 먼저 확인 요청한다.

## Execution discipline
- 명시적 태그가 있을 때만 모드를 강하게 해석한다:  
  [계획], [검토], [검수], [실행], [진행]

- 삭제, 대량 rename, DB drop, 강한 마이그레이션, force push 성격의 작업은 반드시 확인을 받는다.
- 승인된 범위를 벗어나는 변경이 필요하면 먼저 이유와 파급범위를 설명한다.

## Engineering style
- 관련 없는 파일은 건드리지 않는다.
- 변경 전 기존 구조와 의존 경로를 먼저 파악한다.
- 다중 파일 수정 시 어떤 파일이 왜 같이 바뀌는지 연결해서 설명한다.
- 임시 가정은 현재 작업에만 사용하고 확정 사실처럼 다루지 않는다.

## Review style
- 리뷰 요청이면 먼저 문제점/병목/리스크를 식별한다.
- 가능하면 바로 적용 가능한 수정안까지 제시하되, 범위를 넘는 리팩터링은 별도 제안으로 분리한다.
- 수정 후에는 **검수 포인트와 변경 파일을 함께 보고한다.**

## Backup safety
- 파일 수정 전에는 반드시 `backup/` 아래에 백업본을 먼저 만든다.
- 백업 생성은 `scripts/backup_before_edit.ps1 <relative-path>`를 기본으로 사용한다.
- `templates/stats.html`, `templates/view.html`, `templates/apt_manager.html`, `static/js/view_ui.js`는 항상 백업 후 수정한다.
- 같은 세션에서 같은 파일을 다시 수정하더라도 백업을 생략하지 않는다.
- 일반 백업은 30일 보관을 기본으로 한다.
- `templates/stats.html`, `templates/view.html`, `templates/apt_manager.html`, `static/js/view_ui.js` 백업은 자동 정리 대상에서 제외하고 계속 보관한다.
- 백업 정리는 `scripts/cleanup_backups.ps1`로 수행한다.

## Verification safety
- 수정 후에는 `scripts/run_edit_verification.ps1 <relative-path>`로 기본 검수를 먼저 수행한다.
- 이 검수에는 UTF-8 decode, BOM 여부, `??`/`�`/대표적인 깨짐 패턴 검사까지 포함한다.
- `npx`가 가능한 환경에서는 `scripts/run_edit_verification.ps1 <relative-path> -Url <page-url>` 형태로 브라우저 스모크 체크까지 수행한다.

## Auto-run discipline
- `night_agent_v2.ps1`를 쓸 때는 plan 단계와 apply 단계를 분리한다.
- plan 단계에서는 파일을 수정하지 않고, target `paths` 안에서 어떤 파일을 왜 건드릴지만 JSON으로 정리한다.
- apply 단계에서는 승인된 범위와 target `paths` 안에서만 최소 수정한다.
- auto-run에서는 관련 없는 helper file 생성, 대형 리팩터링, 전체 구조 교체를 기본 금지한다.
- 검수 실패 시 다음 task로 넘어가기 전에 원인 로그를 남기고 중단 또는 rollback을 우선한다.
- auto-run task는 가능하면 페이지/기능 단위로 작게 유지하고, `acceptance`와 `verification`을 함께 적는다.
