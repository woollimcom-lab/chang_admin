# Brain Layer Notes

`brain/`은 기존 `night_agent_v2` 위에 V3 방식의 요청 해석, queue 컴파일, 위험도 판단, 검수 preset을 얹기 위한 운영 레이어다.

## 현재 연결 상태

- 실제 실행기
  - `scripts/night_agent_v2.ps1`
- V3 요청 컴파일러
  - `scripts/compile_request_to_tasks.js`
- V3 실행 진입점
  - `scripts/night_agent_v3.ps1`
- 브라우저 검증
  - `scripts/run_task_verification.js`
- 기본 파일 검수
  - `scripts/run_edit_verification.ps1`
  - `scripts/verify_file_safety.py`
  - `scripts/verify_ui_strings.py`
- reviewer gate
  - `scripts/review_patch_against_contract.js`

## brain 파일 역할

- `CORE_STATE_MAP.yaml`
  - 위험 파일, 실행 guard, known legacy issue를 정의
- `DECISIONS.md`
  - 운영 결정과 실패 교훈 누적
- `REQUEST_PATTERNS.json`
  - 반복되는 요구를 canonical feature로 정의
- `VERIFICATION_PRESETS.json`
  - 반복되는 검증 단계를 preset으로 재사용
- `TASK_QUEUE/task.schema.json`
  - queue JSON 구조 검증용 schema
- `TASK_QUEUE/request.example.json`
  - V3 request 예시
- `TASK_QUEUE/example.v3.queue.json`
  - 컴파일된 queue 예시

## V3 1차 흐름

1. request JSON 작성
2. `compile_request_to_tasks.js`로 queue 생성
3. `validate_task_queue.js`로 schema 검증
4. `CORE_STATE_MAP.yaml`로 위험 hotspot 판정
5. 위험도를 확인한 뒤 `night_agent_v2.ps1`로 실행하고, blocking hotspot이면 rebatch된 phase queue를 순차 실행

## 기본 사용법

compile만 확인:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\night_agent_v3.ps1 -RequestFile .\brain\TASK_QUEUE\request.example.json -CompileOnly
```

실행까지 이어가기:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\night_agent_v3.ps1 -RequestFile .\brain\TASK_QUEUE\request.example.json
```

위험 hotspot을 무시하고 강제로 진행:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\night_agent_v3.ps1 -RequestFile .\brain\TASK_QUEUE\request.example.json -AllowRiskyHotspots
```

## request.json에서 바로 쓸 수 있는 필드

```json
{
  "request_id": "req-2026-03-22-001",
  "goal": "설명",
  "features": [
    "feature_id",
    {
      "id": "feature_id",
      "priority": "critical",
      "batch": "view-phase-1"
    }
  ],
  "defaultUrl": "http://43.202.209.122/view/6075",
  "useAuth": true,
  "priority": "high",
  "defaults": {
    "model": "gpt-5.4",
    "modelReasoningEffort": "high",
    "maxAttempts": 3,
    "maxChangedFiles": 2,
    "allowNewFiles": false,
    "requirePlanJson": true
  },
  "feature_overrides": {
    "feature_id": {
      "instruction": "이 요청에만 쓰는 추가 제한",
      "maxChangedFiles": 1
    }
  }
}
```

지원되는 override:

- `priority`
- `name`
- `instruction`
- `maxChangedFiles`
- `batch`
- `depends_on`
- `verification`
- `target_files`
- `reuse_symbols`
- `do_not_touch`
- `acceptance`

`verification` override는 `url`, `useAuth`, `forbidDialogs`, `steps`만 덮는 것이 아니라 preset에 들어 있는 추가 runner 옵션도 같이 유지한다.

예를 들어 modal 안의 입력을 검증해야 하는 preset은 처음부터 hidden selector를 기다리지 말고, 수정 버튼 클릭처럼 실제 UI 진입 순서를 `steps`에 넣어야 한다.

## 산출물

`output/night_agent_v3/<timestamp>/`

- `compiled.queue.json`
  - 실제 V2가 실행할 queue
- `compile_report.json`
  - feature, batch, hotspot 파일 요약
- `risk_report.json`
  - 위험 파일 정책과 queue 비교 결과
- `rebatch_plan.json`
  - blocking hotspot이 있을 때 자동 재분할 계획
- `rebatched/batch-01.json`
  - 자동 재분할된 실행용 queue
- `summary.txt`
  - 한 번에 읽는 요약

## risk_report.json 의미

- 어떤 위험 파일이 queue에 포함됐는지
- 허용된 task 수를 초과했는지
- batch가 섞였는지
- 실행을 막아야 하는 blocking hotspot이 있는지

기본 정책은 `execution_guard.block_on_risky_hotspot: true` 이다.

## auto re-batching

blocking hotspot이 발견되면 V3는 실행 전에 queue를 자동으로 다시 쪼갠다.

이때 task는 `depends_on` 기준으로 먼저 정렬되고, phase는 선행 task보다 뒤에 배치된다.

예:

- `templates/view.html`을 건드리는 task가 2개이고 허용치가 1개
- `rebatch_plan.json` 생성
- `rebatched/batch-01.json`, `rebatched/batch-02.json` 생성
- 기본 정책에서는 여기서 멈추지 않고 rebatch된 queue를 phase 순서대로 실행
- `-AllowRiskyHotspots`를 주면 원본 queue 실행을 강행할 수 있음

즉 V3는 이제 `막기만` 하는 것이 아니라 `실행 가능한 대안 queue`를 만들고 바로 이어서 실행한다.

보고서에는 `execution mode`, `execution_plan`, `task_execution_order`가 함께 기록된다.

## 현재 위험 파일 예시

- `templates/view.html`
- `templates/stats.html`
- `static/js/view_ui.js`
- `static/js/view_api.js`
- `templates/includes/marketing_modal.html`
- `routers/marketing.py`
- `templates/includes/item_master.html`
- `services/photo_service.py`

## Quick Check

1. Run `-CompileOnly` first and confirm queue generation and validator pass.
2. Run the same request without `-CompileOnly` only after that.
3. Check the latest V3 `summary.txt` and latest V2 `summary.txt` first.

```powershell
Get-ChildItem .\output\night_agent_v3 | Sort-Object LastWriteTime -Descending | Select-Object -First 1 FullName
Get-ChildItem .\output\night_agent_v2 | Sort-Object LastWriteTime -Descending | Select-Object -First 1 FullName
```

- V3 summary should contain `execution mode`.
- V2 summary should contain `SUCCESS | ...` for a successful run.
- If validator fails, fix the request or queue contract before retrying execution.

## 다음 단계 후보

- 실패 원인별 retry playbook
- morning report 자동 요약

## 현재 한계

- 아직 memory-driven planner는 아니다.
- state map은 실행 guard 중심이고, request 의미 해석까지 깊게 반영하진 않는다.
- 실제 운영 안정성은 여전히 task를 작게 쪼개는 품질에 크게 의존한다.
