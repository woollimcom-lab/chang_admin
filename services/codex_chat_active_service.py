import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from services.mobile_control_service import (
    add_comment as _mc_add_comment,
    claim_upload_job_for_task as _mc_claim_upload_job_for_task,
    complete_task_plan_for_review as _mc_complete_task_plan_for_review,
    create_task as _mc_create_task,
    finish_post_upload_verify_failure_for_task as _mc_finish_post_upload_verify_failure_for_task,
    finish_post_upload_verify_for_task as _mc_finish_post_upload_verify_for_task,
    finish_upload_for_task as _mc_finish_upload_for_task,
    get_state_bundle as _mc_get_state_bundle,
    get_task as _mc_get_task,
    plan_task as _mc_plan_task,
    reflect_task_result_for_review as _mc_reflect_task_result_for_review,
    start_task as _mc_start_task,
    update_task_action as _mc_update_task_action,
)


CODEX_CHAT_ACTIVE_SERVICE_PROFILE = "mobile-control-adapter"
CODEX_CHAT_ACTIVE_SERVICE_MODULE = "services.codex_chat_active_service"
CODEX_CHAT_ACTIVE_SERVICE_BOUNDARY = "active-service-owns-mobile-control-adapter"
CODEX_CHAT_BRIDGE_MODE = "thin-bridge"
CODEX_CHAT_BRIDGE_GOAL = "mobile-one-line-command-to-local-codex-last-result"
CODEX_CHAT_CONTEXT_MARKER = "[Codex Chat Context]"
CODEX_CHAT_CONTEXT_ENTRY_LIMIT = 5
CODEX_CHAT_CONTEXT_ENTRY_TEXT_LIMIT = 260
CODEX_CHAT_CONTEXT_TOTAL_LIMIT = 2800
BASE_DIR = Path(__file__).resolve().parents[1]
CODEX_PROJECTS_FILE = BASE_DIR / "output" / "mobile_control" / "runtime" / "codex_chat_projects.json"


def _mc_text(value, fallback=""):
    text = str(value or "").strip()
    return text or fallback


def _mc_compact_text(value, max_length=140):
    rendered = " ".join(_mc_text(value).split())
    if len(rendered) <= max_length:
        return rendered
    return f"{rendered[:max_length].rstrip()}..."


def _mc_display_command_text(value):
    text = _mc_text(value)
    if not text:
        return ""
    if CODEX_CHAT_CONTEXT_MARKER in text:
        text = text.split(CODEX_CHAT_CONTEXT_MARKER, 1)[0]
    return _mc_text(text)


def _mc_role_label(role: str, message_type: str = ""):
    role_key = str(role or "").strip().lower()
    type_key = str(message_type or "").strip().lower()
    if role_key == "user":
        return "나"
    if role_key == "agent":
        return "Codex"
    if role_key == "system":
        return "시스템"
    if type_key == "comment":
        return "추가 지시"
    return "로그"


def _project_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_projects_payload():
    if not CODEX_PROJECTS_FILE.exists():
        return {"projects": []}
    try:
        payload = json.loads(CODEX_PROJECTS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"projects": []}
    projects = payload.get("projects") if isinstance(payload, dict) else []
    return {"projects": projects if isinstance(projects, list) else []}


def _save_projects_payload(payload):
    CODEX_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CODEX_PROJECTS_FILE.write_text(
        json.dumps(payload or {"projects": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _project_stage_label(status):
    return {
        "PLANNING": "기획",
        "APPROVAL": "승인 대기",
        "ACTIVE": "자동 실행 중",
        "DONE": "완료",
        "HOLD": "보류",
    }.get(_mc_text(status).upper(), "기획")


def _project_progress_percent(project, current_task):
    if current_task:
        return max(0, min(100, int(current_task.get("progress_percent") or 0)))
    status = _mc_text((project or {}).get("status")).upper()
    return {
        "PLANNING": 10,
        "APPROVAL": 32,
        "ACTIVE": 66,
        "DONE": 100,
        "HOLD": 48,
    }.get(status, 0)


def _project_workspace_copy(project, current_task, *, approved=False, progress_percent=0, active_title=""):
    status = _mc_text((current_task or {}).get("status")).upper()
    step_label = _mc_text((current_task or {}).get("current_step_label"))
    status_label = _mc_text((current_task or {}).get("status_label"))
    next_action = _mc_text((current_task or {}).get("next_action"))
    active_name = _mc_text(active_title, step_label or status_label)

    if status == "DONE":
        return {
            "status_hint": "결과 확인",
            "workspace_brief": "결과만 확인하면 됩니다.",
            "workspace_state_line": "결과 확인",
            "workspace_log_line": "자동 실행이 끝났습니다. 결과만 확인해 주세요.",
        }
    if status in {"FAILED", "HOLD", "UPLOAD_VERIFY_FAILED", "REVISION_REQUESTED"}:
        return {
            "status_hint": "재정리 필요",
            "workspace_brief": "멈춤 · 재정리 필요",
            "workspace_state_line": "재정리 필요",
            "workspace_log_line": next_action or "멈춘 지점을 다시 정리하면 이어서 진행할 수 있습니다.",
        }
    if not approved:
        if status == "PLANNING":
            return {
                "status_hint": "계획 정리 중",
                "workspace_brief": "계획을 정리하고 있습니다.",
                "workspace_state_line": "계획 정리 중",
                "workspace_log_line": next_action or "Codex가 계획과 체크리스트를 정리하고 있습니다.",
            }
        if status in {"WAITING_APPROVAL", "WAITING_USER_CHECK", "WAITING_REVIEW"}:
            return {
                "status_hint": "계획 승인",
                "workspace_brief": "계획 승인만 하면 됩니다.",
                "workspace_state_line": "승인 대기",
                "workspace_log_line": next_action or "계획을 정리했습니다. 승인만 남았습니다.",
            }
        return {
            "status_hint": "계획 승인",
            "workspace_brief": "계획 승인만 하면 됩니다.",
            "workspace_state_line": "승인 대기",
            "workspace_log_line": next_action or "계획을 정리했습니다. 승인만 남았습니다.",
        }
    if status in {"QUEUED", "CLAIMED", "PLANNING"}:
        return {
            "status_hint": "자동 실행 준비",
            "workspace_brief": "자동 실행 준비 중",
            "workspace_state_line": "자동 실행 준비",
            "workspace_log_line": next_action or "승인된 계획을 다음 단계로 넘기고 있습니다.",
        }
    if status in {"RUNNING", "REDEBUG_RUNNING"}:
        return {
            "status_hint": f"자동 실행 · {_mc_text(active_name, '작업 진행')}",
            "workspace_brief": f"'{_mc_text(active_name, '작업 진행')}' 진행 중 · {progress_percent}%",
            "workspace_state_line": f"자동 실행 · {_mc_text(active_name, '작업 진행')}",
            "workspace_log_line": next_action or f"'{_mc_text(active_name, '작업 진행')}' 단계를 진행하고 있습니다.",
        }
    if status in {"WAITING_USER_CHECK", "WAITING_REVIEW"}:
        return {
            "status_hint": "결과 검토",
            "workspace_brief": "결과와 체크리스트를 확인 중입니다.",
            "workspace_state_line": "결과 검토",
            "workspace_log_line": next_action or "결과와 체크리스트를 확인한 뒤 다음 반영 여부를 판단합니다.",
        }
    if status in {"READY_TO_UPLOAD", "UPLOAD_APPROVED", "UPLOADING", "POST_UPLOAD_VERIFY"}:
        return {
            "status_hint": "반영 진행",
            "workspace_brief": "업로드/검증을 진행 중입니다.",
            "workspace_state_line": "반영 진행",
            "workspace_log_line": next_action or "반영과 최종 검증을 이어서 진행하고 있습니다.",
        }
    return {
        "status_hint": "자동 실행 준비",
        "workspace_brief": "자동 실행 준비 중",
        "workspace_state_line": "자동 실행 준비",
        "workspace_log_line": next_action or "승인된 계획을 다음 단계로 넘기고 있습니다.",
    }


def _build_project_plan_preview(project, current_task):
    items = []
    raw_items = (project or {}).get("plan_items") or []
    for item in raw_items[:4]:
        title = _mc_text((item or {}).get("title"))
        if not title:
            continue
        items.append(
            {
                "title": title,
                "status": _mc_text((item or {}).get("status"), "TODO").upper(),
                "note": _mc_text((item or {}).get("note")),
            }
        )
    plan_summary = (current_task or {}).get("plan_summary") or {}
    if not items:
        goal = _mc_text(plan_summary.get("goal"), _mc_text((project or {}).get("goal")))
        if goal:
            items.append({"title": goal, "status": "IN_PROGRESS", "note": "현재 목표"})
        verification_rows = plan_summary.get("verification_plan") or []
        for row in verification_rows[:3]:
            title = _mc_text(row)
            if title:
                items.append({"title": title, "status": "TODO", "note": "검증 단계"})
    return items[:4]


def _project_plan_rows(project, current_task):
    raw_items = (project or {}).get("plan_items") or []
    rows = []
    for item in raw_items:
        title = _mc_text((item or {}).get("title"))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "status": _mc_text((item or {}).get("status"), "TODO").upper(),
                "note": _mc_text((item or {}).get("note")),
            }
        )
    if not rows:
        rows = _build_project_plan_preview(project, current_task)
    if not rows:
        return []

    rows = [dict(item) for item in rows[:4]]
    task_status = _mc_text((current_task or {}).get("status")).upper()
    approved = bool((project or {}).get("approved"))

    if len(rows) >= 1 and (current_task or approved):
        rows[0]["status"] = "DONE"
        rows[0]["note"] = _mc_text(rows[0].get("note"), "요구를 정리했습니다.")

    if len(rows) >= 2:
        if approved:
            rows[1]["status"] = "DONE"
            rows[1]["note"] = "승인 완료"
        elif current_task:
            rows[1]["status"] = "IN_PROGRESS"
            rows[1]["note"] = "승인 전 검토 중"

    if len(rows) >= 3 and approved:
        if task_status == "DONE":
            rows[2]["status"] = "DONE"
            rows[2]["note"] = "자동 실행 완료"
        else:
            rows[2]["status"] = "IN_PROGRESS"
            rows[2]["note"] = _mc_text((current_task or {}).get("current_step_label"), "자동 실행 진행 중")

    if len(rows) >= 4:
        if task_status == "DONE":
            rows[3]["status"] = "DONE"
            rows[3]["note"] = "결과 확인 완료"
        elif task_status in {
            "WAITING_USER_CHECK",
            "WAITING_REVIEW",
            "READY_TO_UPLOAD",
            "UPLOAD_APPROVED",
            "UPLOADING",
            "POST_UPLOAD_VERIFY",
            "UPLOAD_VERIFY_FAILED",
            "REVISION_REQUESTED",
            "HOLD",
            "FAILED",
        }:
            rows[3]["status"] = "IN_PROGRESS"
            rows[3]["note"] = _mc_text((current_task or {}).get("status_label"), "검증/반영 판단 진행 중")

    return rows


def _project_plan_stats(project, current_task):
    rows = _project_plan_rows(project, current_task)
    total_count = len(rows)
    done_count = len([item for item in rows if _mc_text(item.get("status")).upper() in {"DONE", "COMPLETE"}])
    remaining_count = max(0, total_count - done_count)
    active_item = next(
        (
            item
            for item in rows
            if _mc_text(item.get("status")).upper() in {"IN_PROGRESS", "ACTIVE", "RUNNING"}
        ),
        None,
    )
    active_title = _mc_text(
        (active_item or {}).get("title"),
        _mc_text((current_task or {}).get("current_step_label") or (current_task or {}).get("status_label")),
    )
    return {
        "rows": rows,
        "total_count": total_count,
        "done_count": done_count,
        "remaining_count": remaining_count,
        "active_title": active_title,
    }


def _project_status_from_task(project, current_task):
    if _mc_text((project or {}).get("status")).upper() == "HOLD":
        return "HOLD"
    if current_task:
        task_status = _mc_text(current_task.get("status")).upper()
        if task_status == "DONE":
            return "DONE"
        if task_status in {"WAITING_APPROVAL", "WAITING_USER_CHECK", "WAITING_REVIEW"} and not (project or {}).get("approved"):
            return "APPROVAL"
        if task_status in {"PLANNING", "QUEUED", "CLAIMED"} and not (project or {}).get("approved"):
            return "PLANNING"
        return "ACTIVE"
    return "APPROVAL" if (project or {}).get("approved") else "PLANNING"


def _build_projects_bundle(tasks, selected_project_id=""):
    payload = _load_projects_payload()
    task_map = {
        _mc_text(item.get("id")): item
        for item in (tasks or [])
        if _mc_text(item.get("id"))
    }
    projects = []
    for project in payload.get("projects") or []:
        task_ids = [task_id for task_id in (project.get("task_ids") or []) if task_id in task_map]
        current_task_id = _mc_text(project.get("current_task_id"))
        if current_task_id not in task_map and task_ids:
            current_task_id = task_ids[0]
        current_task = task_map.get(current_task_id)
        status = _project_status_from_task(project, current_task)
        plan_stats = _project_plan_stats(project, current_task)
        updated_at = _mc_text(
            (current_task or {}).get("updated_at"),
            _mc_text(project.get("updated_at"), _project_now()),
        )
        approved = bool(project.get("approved"))
        progress_percent = _project_progress_percent(project, current_task)
        workspace_copy = _project_workspace_copy(
            project,
            current_task,
            approved=approved,
            progress_percent=progress_percent,
            active_title=_mc_text(plan_stats.get("active_title")),
        )
        status_hint = _mc_text(workspace_copy.get("status_hint"))
        workspace_brief = _mc_text(workspace_copy.get("workspace_brief"))
        workspace_state_line = _mc_text(workspace_copy.get("workspace_state_line"))
        workspace_log_line = _mc_text(workspace_copy.get("workspace_log_line"))
        if plan_stats.get("total_count"):
            summary_line = f"계획 {plan_stats.get('done_count')}/{plan_stats.get('total_count')} · 남음 {plan_stats.get('remaining_count')}"
        else:
            summary_line = "계획 정리 중"
        card = {
            "id": _mc_text(project.get("id")),
            "title": _mc_text(project.get("title"), "이름 없는 프로젝트"),
            "goal": _mc_text(project.get("goal"), "목표를 입력해 주세요."),
            "status": status,
            "stage_label": _project_stage_label(status),
            "approved": approved,
            "approved_at": _mc_text(project.get("approved_at")),
            "task_count": len(task_ids),
            "current_task_id": current_task_id,
            "progress_percent": progress_percent,
            "updated_at": updated_at,
            "latest_summary": _mc_text((current_task or {}).get("summary"), _mc_text(project.get("latest_summary"))),
            "next_step": _mc_text((current_task or {}).get("next_action"), _mc_text(project.get("next_step"), "다음 지시 또는 승인 확인")),
            "current_task_title": _mc_text((current_task or {}).get("title")),
            "plan_items": plan_stats.get("rows")[:4],
            "plan_total_count": int(plan_stats.get("total_count") or 0),
            "plan_done_count": int(plan_stats.get("done_count") or 0),
            "plan_remaining_count": int(plan_stats.get("remaining_count") or 0),
            "active_plan_title": _mc_text(plan_stats.get("active_title")),
            "status_hint": status_hint,
            "summary_line": summary_line,
            "workspace_brief": workspace_brief,
            "workspace_state_line": workspace_state_line,
            "workspace_log_line": workspace_log_line,
        }
        projects.append(card)
    projects.sort(key=lambda item: (_mc_text(item.get("updated_at")), _mc_text(item.get("id"))), reverse=True)
    selected = None
    clean_selected_id = _mc_text(selected_project_id)
    if clean_selected_id:
        selected = next((item for item in projects if _mc_text(item.get("id")) == clean_selected_id), None)
    if not selected and projects:
        selected = projects[0]
    return {
        "items": projects,
        "selected": selected,
        "selected_id": _mc_text((selected or {}).get("id")),
    }


def _create_project(title, goal, actor=""):
    clean_title = _mc_text(title)
    clean_goal = _mc_text(goal)
    if not clean_title:
        raise ValueError("프로젝트 이름을 입력해 주세요.")
    if not clean_goal:
        raise ValueError("프로젝트 목표를 입력해 주세요.")
    payload = _load_projects_payload()
    now = _project_now()
    project_id = f"project-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    project = {
        "id": project_id,
        "title": clean_title,
        "goal": clean_goal,
        "status": "PLANNING",
        "approved": False,
        "approved_at": "",
        "created_at": now,
        "updated_at": now,
        "updated_by": _mc_text(actor, "codex"),
        "task_ids": [],
        "current_task_id": "",
        "latest_summary": "프로젝트를 만들었습니다. 먼저 기획 지시를 남기면 됩니다.",
        "next_step": "기획 지시를 남기세요.",
        "plan_items": [
            {"title": "요구 정리", "status": "IN_PROGRESS", "note": "기획 지시 대기"},
            {"title": "세부 계획 확정", "status": "TODO", "note": "승인 전"},
            {"title": "자동 실행", "status": "TODO", "note": "승인 후 자동 진행"},
            {"title": "검증/반영 판단", "status": "TODO", "note": "마지막 확인"},
        ],
    }
    payload["projects"] = [project, *(payload.get("projects") or [])]
    _save_projects_payload(payload)
    return project


def _link_task_to_project(project_id, task_id, summary="", actor=""):
    clean_project_id = _mc_text(project_id)
    clean_task_id = _mc_text(task_id)
    if not clean_project_id or not clean_task_id:
        return
    payload = _load_projects_payload()
    changed = False
    now = _project_now()
    for project in payload.get("projects") or []:
        if _mc_text(project.get("id")) != clean_project_id:
            continue
        task_ids = [task for task in (project.get("task_ids") or []) if _mc_text(task)]
        if clean_task_id not in task_ids:
            task_ids.insert(0, clean_task_id)
        project["task_ids"] = task_ids[:24]
        project["current_task_id"] = clean_task_id
        project["updated_at"] = now
        project["updated_by"] = _mc_text(actor, "codex")
        if _mc_text(summary):
            project["latest_summary"] = _mc_text(summary)
        project["next_step"] = "기획/실행 결과를 확인하세요."
        changed = True
        break
    if changed:
        _save_projects_payload(payload)


def _approve_project(project_id, actor=""):
    clean_project_id = _mc_text(project_id)
    if not clean_project_id:
        raise ValueError("project_id가 필요합니다.")
    payload = _load_projects_payload()
    now = _project_now()
    project = None
    for item in payload.get("projects") or []:
        if _mc_text(item.get("id")) != clean_project_id:
            continue
        item["approved"] = True
        item["approved_at"] = now
        item["status"] = "ACTIVE"
        item["updated_at"] = now
        item["updated_by"] = _mc_text(actor, "codex")
        item["next_step"] = "승인된 계획 기준으로 자동 실행을 이어갑니다."
        project = item
        break
    if not project:
        raise ValueError("프로젝트를 찾을 수 없습니다.")
    _save_projects_payload(payload)
    return project


def _mc_task_primary_action(task):
    if not task:
        return None
    status = _mc_text(task.get("status")).upper()
    upload_status = _mc_text(task.get("latest_upload_job_status")).upper()
    actions = task.get("actions") or {}
    upload_readiness = task.get("upload_readiness") or {}
    can_request_upload = bool(actions.get("can_request_upload")) or bool(upload_readiness.get("allowed")) or status == "READY_TO_UPLOAD"
    can_claim_upload = bool(actions.get("can_claim_upload")) or (status == "UPLOAD_APPROVED" and upload_status == "REQUESTED")
    can_finish_upload = bool(actions.get("can_finish_upload")) or (status == "UPLOADING" and upload_status == "UPLOADING")
    can_finish_post_upload_verify = bool(actions.get("can_finish_post_upload_verify")) or status == "POST_UPLOAD_VERIFY"
    can_fail_post_upload_verify = bool(actions.get("can_fail_post_upload_verify")) or status == "POST_UPLOAD_VERIFY"
    can_request_redebug = bool(actions.get("can_request_redebug")) or status == "UPLOAD_VERIFY_FAILED"
    can_start_redebug = bool(actions.get("can_start_redebug")) or status == "REVISION_REQUESTED"
    can_reflect_result = bool(actions.get("can_reflect_result")) or status in {"RUNNING", "REDEBUG_RUNNING"}
    can_confirm_review = bool(actions.get("can_confirm_review")) or status == "WAITING_USER_CHECK"
    can_prepare_upload = bool(actions.get("can_prepare_upload")) or status == "WAITING_REVIEW"

    if status == "WAITING_USER_CHECK" and can_confirm_review:
        return {
            "action": "confirm-review",
            "label": "검토 완료",
            "description": "사용자 확인을 마치고 업로드 전 마지막 검토 단계로 넘깁니다.",
            "tone": "primary",
        }
    if status == "WAITING_REVIEW" and can_prepare_upload:
        return {
            "action": "prepare-upload",
            "label": "업로드 준비 확인",
            "description": "업로드 준비 게이트를 다시 계산하고 바로 다음 업로드 가능 여부를 갱신합니다.",
            "tone": "primary",
        }
    if can_request_upload:
        return {
            "action": "request-upload",
            "label": "서버 업로드 승인",
            "description": "승인 요청을 바로 등록하고 업로드 단계로 넘깁니다.",
            "tone": "primary",
        }
    if can_claim_upload:
        return {
            "action": "claim-upload",
            "label": "업로드 시작",
            "description": "승인된 업로드를 즉시 실행 단계로 넘깁니다.",
            "tone": "primary",
        }
    if can_finish_upload:
        return {
            "action": "finish-upload",
            "label": "업로드 완료 처리",
            "description": "업로드를 마치고 반영 검증 단계로 이동합니다.",
            "tone": "primary",
        }
    if can_finish_post_upload_verify:
        return {
            "action": "finish-post-upload-verify",
            "label": "최종 검증 완료",
            "description": "업로드 후 검증을 마감하고 성공 흐름을 닫습니다.",
            "tone": "primary",
        }
    if status == "POST_UPLOAD_VERIFY" and can_fail_post_upload_verify:
        return {
            "action": "fail-post-upload-verify",
            "label": "반영 검증 실패 기록",
            "description": "업로드 후 검증 실패를 남기고 재디버그 흐름으로 전환합니다.",
            "tone": "warn",
        }
    if status == "UPLOAD_VERIFY_FAILED" and can_request_redebug:
        return {
            "action": "request-redebug",
            "label": "재디버그 요청",
            "description": "실패 원인을 묶어 복구 흐름을 다시 시작합니다.",
            "tone": "warn",
        }
    if status == "REVISION_REQUESTED" and can_start_redebug:
        return {
            "action": "start-redebug",
            "label": "재디버그 실행",
            "description": "복구 작업을 다시 시작합니다.",
            "tone": "primary",
        }
    if status == "REDEBUG_RUNNING" and can_reflect_result:
        return {
            "action": "reflect-result",
            "label": "결과 반영",
            "description": "재디버그 결과를 다시 사용자 검토 단계로 넘깁니다.",
            "tone": "primary",
        }
    if status in {"FAILED", "HOLD"} and can_request_redebug:
        return {
            "action": "request-redebug",
            "label": "재디버그 요청",
            "description": "실패 또는 보류 사유를 묶어 복구 흐름을 다시 시작합니다.",
            "tone": "warn",
        }
    if actions.get("can_execute_now"):
        return {
            "action": "execute-now",
            "label": "실행 시작",
            "description": "계획 검토가 끝난 작업을 실제 실행 단계로 넘깁니다.",
            "tone": "primary",
        }
    if actions.get("can_proceed"):
        return {
            "action": "proceed",
            "label": "진행 시작",
            "description": "보류 또는 실패 상태 작업을 다음 실행 단계로 다시 넘깁니다.",
            "tone": "primary",
        }
    if actions.get("can_request_plan"):
        return {
            "action": "request-plan",
            "label": "계획 수립 요청",
            "description": "작업 계획과 체크리스트 초안 생성을 다시 시작합니다.",
            "tone": "primary",
        }
    if actions.get("can_finalize_plan"):
        return {
            "action": "complete-plan",
            "label": "계획 검토 준비",
            "description": "계획 초안을 검토 가능한 상태로 정리합니다.",
            "tone": "primary",
        }
    if status == "DONE":
        return {
            "action": "",
            "label": "완료됨",
            "description": "이미 최종 완료된 작업입니다.",
            "tone": "muted",
            "disabled": True,
        }
    return None


def _mc_task_log_entries(task, limit=12):
    if not task:
        return []
    rows = []
    for message in task.get("messages") or []:
        body = _mc_text(message.get("content"), "-")
        if _mc_text(message.get("role")).lower() == "user":
            body = _mc_display_command_text(body) or body
        rows.append(
            {
                "role": _mc_text(message.get("role"), "system").lower(),
                "label": _mc_role_label(message.get("role"), message.get("message_type")),
                "message_type": _mc_text(message.get("message_type"), "status"),
                "body": body,
                "created_at": _mc_text(message.get("created_at")),
                "sort_key": _mc_text(message.get("created_at")),
            }
        )
    for comment in task.get("comments") or []:
        rows.append(
            {
                "role": "user",
                "label": "추가 지시",
                "message_type": "comment",
                "body": _mc_text(comment.get("body"), "-"),
                "created_at": _mc_text(comment.get("created_at")),
                "sort_key": _mc_text(comment.get("created_at")),
            }
        )
    rows.sort(key=lambda item: (item.get("sort_key") or "", item.get("message_type") or ""))
    trimmed = rows[-limit:]
    if trimmed:
        return trimmed
    return [
        {
            "role": "system",
            "label": "시스템",
            "message_type": "status",
            "body": _mc_text(task.get("summary") or task.get("next_action"), "아직 남겨진 대화 로그가 없습니다."),
            "created_at": _mc_text(task.get("updated_at") or task.get("created_at")),
            "sort_key": _mc_text(task.get("updated_at") or task.get("created_at")),
        }
    ]


def _mc_context_result_text(task):
    if not task:
        return ""
    result_payload = task.get("result_payload") or {}
    if not isinstance(result_payload, dict):
        result_payload = {}
    return _mc_compact_text(
        task.get("latest_summary")
        or result_payload.get("latest_summary")
        or task.get("summary")
        or task.get("next_action"),
        CODEX_CHAT_CONTEXT_ENTRY_TEXT_LIMIT,
    )


def _mc_context_entry(task):
    if not task:
        return None
    command = _mc_display_command_text(task.get("text") or task.get("title"))
    result = _mc_context_result_text(task)
    status = _mc_text(task.get("status_label") or task.get("user_status") or task.get("status"))
    updated_at = _mc_text(task.get("updated_at") or task.get("created_at"))
    if not (command or result):
        return None
    return {
        "command": _mc_compact_text(command, CODEX_CHAT_CONTEXT_ENTRY_TEXT_LIMIT),
        "status": _mc_compact_text(status, 80),
        "result": result,
        "updated_at": updated_at,
    }


def _mc_recent_context_entries(tasks, limit=CODEX_CHAT_CONTEXT_ENTRY_LIMIT):
    entries = []
    for task in tasks or []:
        entry = _mc_context_entry(task)
        if entry:
            entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def _mc_build_contextual_command(command, tasks):
    clean_command = _mc_text(command)
    entries = _mc_recent_context_entries(tasks)
    if not clean_command or not entries:
        return clean_command

    lines = [
        clean_command,
        CODEX_CHAT_CONTEXT_MARKER.strip(),
        "아래 문맥은 최근 모바일 대화와 직전 결과 요약입니다. 참고만 하고, 이번 실행의 최우선 지시는 위 한 줄 명령입니다.",
        "",
        "[최근 대화 3~5개]",
    ]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"{index}. {entry['updated_at'] or '-'} | 지시: {entry['command'] or '-'} | 상태: {entry['status'] or '-'}"
        )
        if entry["result"]:
            lines.append(f"   결과 요약: {entry['result']}")

    previous_result = next((entry["result"] for entry in entries if entry.get("result")), "")
    if previous_result:
        lines.extend(["", "[직전 결과 요약]", previous_result])
    lines.extend(
        [
            "",
            "[실행 규칙]",
            "- 위 문맥은 이어받기용 참고 자료입니다.",
            "- 이번 사용자 명령과 충돌하면 이번 사용자 명령을 우선합니다.",
            "- 완료/실패/질문 필요 여부를 짧게 요약할 수 있게 결과를 정리합니다.",
        ]
    )
    contextual = "\n".join(lines).strip()
    if len(contextual) <= CODEX_CHAT_CONTEXT_TOTAL_LIMIT:
        return contextual
    return contextual[:CODEX_CHAT_CONTEXT_TOTAL_LIMIT].rstrip() + "\n[문맥 일부 생략]"


def _mc_task_progress_bundle(task):
    if not task:
        return {
            "progress_percent": 0,
            "progress_label": "",
            "progress_note": "",
            "progress_ticker_messages": [],
            "progress_updated_at": "",
            "is_running": False,
            "is_done": False,
        }
    status = _mc_text(task.get("status")).upper()
    raw_percent = int(task.get("progress_percent") or 0)
    progress_percent = max(0, min(100, raw_percent))
    progress_label = _mc_text(task.get("current_step_label") or task.get("status_label") or task.get("user_status"))
    progress_updates = task.get("progress_updates") or []
    progress_updated_at = _mc_text((progress_updates[-1] or {}).get("updated_at") if progress_updates else "", _mc_text(task.get("updated_at") or task.get("created_at")))
    ticker_messages = []
    for item in progress_updates[-4:]:
        summary = _mc_text(item.get("summary"))
        step_label = _mc_text(item.get("step_label") or item.get("status_label"))
        combined = summary or step_label
        if combined:
            ticker_messages.append(combined)
    progress_note = _mc_text(
        (progress_updates[-1] or {}).get("summary") if progress_updates else "",
        _mc_text(task.get("next_action") or progress_label or task.get("summary")),
    )
    is_done = status == "DONE"
    is_running = status in {"PLANNING", "RUNNING", "REDEBUG_RUNNING", "UPLOADING", "POST_UPLOAD_VERIFY"}
    return {
        "progress_percent": 100 if is_done else progress_percent,
        "progress_label": progress_label,
        "progress_note": progress_note,
        "progress_ticker_messages": ticker_messages,
        "progress_updated_at": progress_updated_at,
        "is_running": is_running,
        "is_done": is_done,
    }


def _mc_task_card(task, primary_action):
    if not task:
        return None
    checklist_summary = task.get("checklist_summary") or {}
    progress_bundle = _mc_task_progress_bundle(task)
    return {
        "id": _mc_text(task.get("id")),
        "title": _mc_text(task.get("title"), "제목 없는 작업"),
        "status": _mc_text(task.get("status")).upper(),
        "status_label": _mc_text(task.get("status_label") or task.get("user_status"), "상태 없음"),
        "step_label": _mc_text(task.get("current_step_label"), "-"),
        "step_code": _mc_text(task.get("current_step_code")),
        "target_env": _mc_text(task.get("target_env"), "-"),
        "summary": _mc_text(task.get("latest_summary") or task.get("summary"), "아직 결과 요약이 없습니다."),
        "next_action": _mc_text(task.get("next_action"), "다음 행동을 기다리는 중입니다."),
        "decision_summary": _mc_text(task.get("decision_summary"), ""),
        "risk_summary": _mc_text(task.get("risk_summary"), ""),
        "artifact_count": len(task.get("artifacts") or []),
        "changed_file_count": len(task.get("changed_files") or []),
        "message_count": len(task.get("messages") or []),
        "comment_count": len(task.get("comments") or []),
        "open_check_count": int(checklist_summary.get("open_items") or 0),
        "primary_action_label": _mc_text((primary_action or {}).get("label")),
        "updated_at": _mc_text(task.get("updated_at") or task.get("created_at")),
        **progress_bundle,
    }


def _mc_bridge_run_state(task, primary_action):
    if not task:
        return "IDLE"
    status = _mc_text(task.get("status")).upper()
    if status == "DONE":
        return "DONE"
    if status in {"FAILED", "HOLD", "UPLOAD_VERIFY_FAILED", "REVISION_REQUESTED"}:
        return "FAILED"
    if status in {"WAITING_APPROVAL", "WAITING_USER_CHECK", "WAITING_REVIEW", "READY_TO_UPLOAD", "UPLOAD_APPROVED"}:
        return "NEEDS_USER_INPUT"
    if primary_action and not bool((primary_action or {}).get("disabled")) and status not in {
        "QUEUED",
        "CLAIMED",
        "PLANNING",
        "RUNNING",
        "REDEBUG_RUNNING",
        "UPLOADING",
        "POST_UPLOAD_VERIFY",
    }:
        return "NEEDS_USER_INPUT"
    return "RUNNING"


def _mc_task_context_included(task):
    followup_bundle = (task or {}).get("followup_bundle") or {}
    if not isinstance(followup_bundle, dict):
        return False
    return CODEX_CHAT_CONTEXT_MARKER in _mc_text(followup_bundle.get("instruction"))


def _mc_command_intent_summary(command):
    command_text = _mc_text(command)
    if not command_text:
        return "아직 받은 지시가 없습니다."

    checks = [
        ("지시를 해석한 뒤 승인 후 실행하는 흐름으로 바꾸려는 요청", ("요지", "이해", "판독", "앵무새", "승인")),
        ("문제를 고치거나 막힌 지점을 푸는 요청", ("수정", "고쳐", "해결", "복구", "디버그", "막힘")),
        ("현재 상태를 확인하고 판단하는 요청", ("확인", "체크", "점검", "검토", "판단")),
        ("실행 계획부터 정리하는 요청", ("계획", "플랜", "순서", "단계", "로드맵")),
        ("핵심만 짧게 정리하는 요청", ("요약", "정리", "압축")),
        ("의미와 이유를 설명받는 요청", ("설명", "뜻", "이유", "왜", "알려줘", "말해줘")),
        ("기능을 만들거나 연결하는 요청", ("구현", "만들", "추가", "연결", "붙여", "적용")),
    ]
    action = "새 작업을 시작하려는 요청"
    for label, keywords in checks:
        if any(keyword.lower() in command_text.lower() for keyword in keywords):
            action = label
            break

    scope_checks = [
        ("codex-chat", ("codex-chat", "Codex Chat")),
        ("모바일 채팅 화면", ("모바일", "화면", "UI", "UX", "채팅", "버블")),
        ("지시 이해/승인 흐름", ("요지", "이해", "판독", "승인", "계획")),
        ("결과 표시", ("결과", "요약", "반영")),
        ("서버/실시간 반영", ("서버", "API", "SSE", "WebSocket", "실시간")),
        ("대화 문맥", ("문맥", "프롬프트", "이전 대화")),
        ("프로젝트", ("프로젝트",)),
        ("검증", ("검증", "테스트")),
    ]
    scopes = []
    lowered = command_text.lower()
    for label, keywords in scope_checks:
        if any(keyword.lower() in lowered for keyword in keywords):
            scopes.append(label)
        if len(scopes) >= 3:
            break

    scope_text = f"{' / '.join(scopes)}에 대해 " if scopes else ""
    return f"{scope_text}{action}입니다."


def _mc_pre_execution_check_text(command, context_included):
    intent_summary = _mc_command_intent_summary(command)
    if intent_summary == "아직 받은 지시가 없습니다.":
        return "실행 전 요지 확인: 아직 받은 지시가 없습니다."
    context_label = "최근 대화와 직전 결과 요약을 함께 포함했습니다." if context_included else "추가 문맥 없이 원문 지시만 전달했습니다."
    return f"실행 전 요지 확인: {intent_summary} {context_label}"


def _mc_bridge_user_copy(run_state, current_task, command, summary, last_error, context_included=False):
    status = _mc_text(current_task.get("status")).upper()
    status_label = _mc_text(current_task.get("status_label") or current_task.get("user_status"))
    step_label = _mc_text(current_task.get("current_step_label"))
    next_action = _mc_text(current_task.get("next_action"))
    progress_percent = max(0, min(100, int(current_task.get("progress_percent") or 0))) if current_task else 0
    understanding = _mc_pre_execution_check_text(command, context_included)

    if run_state == "IDLE":
        return {
            "understanding": understanding,
            "status_message": "지시를 보내면 회사 PC의 Codex 실행기로 전달합니다.",
            "wait_hint": "아직 기다릴 작업은 없습니다.",
            "result_message": _mc_text(summary, "아직 실행 결과가 없습니다."),
            "progress_percent": 0,
        }
    if run_state == "RUNNING":
        active_label = _mc_text(step_label, _mc_text(status_label, "로컬 Codex 실행"))
        return {
            "understanding": understanding,
            "status_message": f"{active_label} 진행 중입니다.",
            "wait_hint": f"기다리면 됩니다. 현재 진행률은 {progress_percent}%로 기록되어 있습니다.",
            "result_message": _mc_text(summary, "작업이 끝나면 결과 요약이 여기에 표시됩니다."),
            "progress_percent": progress_percent,
        }
    if run_state == "NEEDS_USER_INPUT":
        return {
            "understanding": understanding,
            "status_message": _mc_text(status_label, "사용자 확인이 필요한 상태입니다."),
            "wait_hint": _mc_text(next_action, "결과를 확인한 뒤 필요하면 다음 지시를 보내면 됩니다."),
            "result_message": _mc_text(summary, "확인할 결과 요약이 아직 비어 있습니다."),
            "progress_percent": progress_percent,
        }
    if run_state == "DONE":
        return {
            "understanding": understanding,
            "status_message": "Codex 실행이 완료되었습니다.",
            "wait_hint": "이제 기다릴 필요 없이 결과만 확인하면 됩니다.",
            "result_message": _mc_text(summary, "완료되었지만 결과 요약이 비어 있습니다."),
            "progress_percent": 100,
        }
    if run_state == "FAILED":
        return {
            "understanding": understanding,
            "status_message": "Codex 실행이 실패하거나 멈췄습니다.",
            "wait_hint": _mc_text(last_error, "원인을 확인한 뒤 재시도 지시가 필요합니다."),
            "result_message": _mc_text(summary, "실패 결과 요약이 아직 비어 있습니다."),
            "progress_percent": progress_percent,
        }
    return {
        "understanding": understanding,
        "status_message": _mc_text(status_label, "상태를 확인하는 중입니다."),
        "wait_hint": _mc_text(next_action, "잠시 뒤 상태를 다시 확인하면 됩니다."),
        "result_message": _mc_text(summary, "아직 실행 결과가 없습니다."),
        "progress_percent": progress_percent,
    }


def _mc_bridge_payload(task, primary_action, selected_project):
    run_state = _mc_bridge_run_state(task, primary_action)
    project = selected_project or {}
    current_task = task or {}
    command = _mc_display_command_text(current_task.get("text")) or _mc_text(current_task.get("title"))
    summary = _mc_text(
        current_task.get("latest_summary") or current_task.get("summary"),
        _mc_text(project.get("latest_summary") or project.get("workspace_brief"), "아직 실행 결과가 없습니다."),
    )
    if run_state == "FAILED":
        last_error = _mc_text(
            current_task.get("risk_summary") or current_task.get("next_action") or current_task.get("status_label"),
            "실패 원인을 다시 확인해야 합니다.",
        )
    else:
        last_error = ""
    updated_at = _mc_text(
        current_task.get("updated_at") or current_task.get("created_at"),
        _mc_text(project.get("updated_at")),
    )
    context_included = _mc_task_context_included(current_task)
    user_copy = _mc_bridge_user_copy(
        run_state,
        current_task,
        command,
        summary,
        last_error,
        context_included=context_included,
    )
    return {
        "command": command,
        "run_state": run_state,
        "needs_user_input": run_state == "NEEDS_USER_INPUT",
        "summary": summary,
        "last_error": last_error,
        "updated_at": updated_at,
        "pre_execution_check": _mc_pre_execution_check_text(command, context_included),
        "context_included": context_included,
        **user_copy,
    }


def _mc_pick_task(tasks, conversation_task_id=""):
    clean_id = _mc_text(conversation_task_id)
    for item in tasks or []:
        if clean_id and _mc_text(item.get("id")) == clean_id:
            return item
        if not clean_id and _mc_text(item.get("id")):
            return item
    return None


def _mc_summary_counts(state):
    prompt_map = {
        "failed_or_revision": {
            "prompt_text": "실패 또는 재수정 작업부터 정리하고 바로 다음 복구 행동까지 이어가줘",
            "prompt_mode": "new-task",
            "action_hint": "눌러서 실패 복구 흐름 시작",
        },
        "waiting_review": {
            "prompt_text": "사용자 검토 대기 작업부터 정리하고 지금 바로 처리할 순서를 잡아줘",
            "prompt_mode": "new-task",
            "action_hint": "눌러서 검토 대기 처리 시작",
        },
        "upload_ready": {
            "prompt_text": "업로드 준비된 작업부터 확인하고 바로 다음 업로드 행동으로 이어가줘",
            "prompt_mode": "new-task",
            "action_hint": "눌러서 업로드 준비 흐름 시작",
        },
        "upload_verify_failed": {
            "prompt_text": "업로드 검증 실패 작업부터 정리하고 바로 재디버그 또는 후속 조치로 이어가줘",
            "prompt_mode": "new-task",
            "action_hint": "눌러서 검증 실패 복구 시작",
        },
    }
    items = []
    for item in state.get("home_summary") or []:
        key = _mc_text(item.get("key"))
        prompt_info = prompt_map.get(key, {})
        items.append(
            {
                "key": key,
                "label": _mc_text(item.get("label")),
                "count": int(item.get("count") or 0),
                "hint": _mc_text(item.get("hint")),
                "prompt_text": _mc_text(prompt_info.get("prompt_text")),
                "prompt_mode": _mc_text(prompt_info.get("prompt_mode")),
                "action_hint": _mc_text(prompt_info.get("action_hint")),
            }
        )
    return items


def _mc_ops_console_bundle(task, primary_action):
    clean_task_id = _mc_text((task or {}).get("id"))
    detail_tab = "overview"
    action_key = _mc_text((primary_action or {}).get("action"))
    status = _mc_text((task or {}).get("status")).upper()
    if action_key in {"request-redebug", "start-redebug", "fail-post-upload-verify"} or status in {"UPLOAD_VERIFY_FAILED", "REVISION_REQUESTED", "FAILED", "HOLD"}:
        detail_tab = "followup"
    elif action_key in {"prepare-upload", "request-upload", "claim-upload", "finish-upload", "finish-post-upload-verify"} or status in {"WAITING_REVIEW", "READY_TO_UPLOAD", "UPLOAD_APPROVED", "UPLOADING", "POST_UPLOAD_VERIFY"}:
        detail_tab = "check"
    if not clean_task_id:
        return {
            "url": "/mobile-control",
            "label": "운영 콘솔 열기",
        }
    query = urlencode({"task_id": clean_task_id, "detail_tab": detail_tab})
    return {
        "url": f"/mobile-control?{query}",
        "label": "현재 작업 운영 콘솔 열기",
    }


def _mc_recent_tasks(tasks, conversation_task_id="", limit=5):
    clean_id = _mc_text(conversation_task_id)
    rows = []
    for task in tasks or []:
        task_id = _mc_text(task.get("id"))
        if not task_id:
            continue
        rows.append(
            {
                "id": task_id,
                "title": _mc_text(task.get("title"), "제목 없는 작업"),
                "status": _mc_text(task.get("status")).upper(),
                "status_label": _mc_text(task.get("status_label") or task.get("user_status"), "상태 없음"),
                "step_label": _mc_text(task.get("current_step_label")),
                "progress_percent": int(task.get("progress_percent") or 0),
                "progress_updated_at": _mc_text(
                    ((task.get("progress_updates") or [{}])[-1] or {}).get("updated_at"),
                    _mc_text(task.get("updated_at") or task.get("created_at")),
                ),
                "updated_at": _mc_text(task.get("updated_at") or task.get("created_at")),
                "next_action": _mc_text(task.get("next_action"), "현재 상태를 다시 확인합니다."),
                "is_current": task_id == clean_id,
                "sort_key": _mc_text(task.get("updated_at") or task.get("created_at")),
            }
        )
    rows.sort(key=lambda item: (1 if item.get("is_current") else 0, item.get("sort_key") or ""), reverse=True)
    trimmed = rows[:limit]
    for item in trimmed:
        item.pop("sort_key", None)
    return trimmed


def _mc_starter_prompts(state, current_task=None):
    if current_task:
        title = _mc_text(current_task.get("title"), "현재 작업")
        return [
            {
                "key": "current_status",
                "label": "현재 상태 3줄 요약",
                "text": f"{title} 현재 상태를 3줄로 요약하고 지금 바로 해야 할 행동 1개만 알려줘",
                "mode": "followup",
            },
            {
                "key": "current_risk",
                "label": "막힌 원인만 정리",
                "text": f"{title}에서 지금 막히는 원인만 짧게 정리하고 바로 풀 순서만 알려줘",
                "mode": "followup",
            },
            {
                "key": "current_next_action",
                "label": "다음 행동만 압축",
                "text": f"{title}의 다음 행동만 한 문장으로 정리하고 바로 실행 준비해줘",
                "mode": "followup",
            },
            {
                "key": "new_task_parallel",
                "label": "이건 새 작업으로 분리",
                "text": "이건 현재 작업과 분리해서 새 작업으로 진행할게. 가장 짧은 실행 계획부터 잡아줘",
                "mode": "new-task",
            },
        ]
    counts = {
        _mc_text(item.get("key")): int(item.get("count") or 0)
        for item in (state.get("home_summary") or [])
    }
    prompts = []
    if counts.get("failed_or_revision", 0) > 0:
        prompts.append(
            {
                "key": "failed_or_revision",
                "label": "실패 작업부터 정리",
                "text": "실패 또는 재수정 작업부터 정리하고 바로 다음 복구 행동까지 이어가줘",
                "mode": "new-task",
            }
        )
    if counts.get("waiting_review", 0) > 0:
        prompts.append(
            {
                "key": "waiting_review",
                "label": "검토 대기부터 처리",
                "text": "사용자 검토 대기 작업부터 정리하고 지금 바로 처리할 순서를 잡아줘",
                "mode": "new-task",
            }
        )
    if counts.get("upload_ready", 0) > 0:
        prompts.append(
            {
                "key": "upload_ready",
                "label": "업로드 준비 작업 처리",
                "text": "업로드 준비된 작업부터 확인하고 바로 다음 업로드 행동으로 이어가줘",
                "mode": "new-task",
            }
        )
    defaults = [
        {
            "key": "new_task_default",
            "label": "새 작업 바로 시작",
            "text": "새 작업을 시작할게. 가장 짧은 실행 계획부터 잡아줘",
            "mode": "new-task",
        },
        {
            "key": "result_check_default",
            "label": "결과부터 점검",
            "text": "최근 작업 결과부터 요약하고 지금 내가 먼저 확인할 것만 짧게 정리해줘",
            "mode": "new-task",
        },
        {
            "key": "upload_path_default",
            "label": "업로드 경로 확인",
            "text": "업로드까지 남은 조건을 가장 짧게 정리하고 바로 막힌 한 가지를 알려줘",
            "mode": "new-task",
        },
    ]
    existing = {item["key"] for item in prompts}
    for item in defaults:
        if item["key"] in existing:
            continue
        prompts.append(item)
        if len(prompts) >= 4:
            break
    return prompts[:4]


def _mc_composer_bundle(task, selected_mode=""):
    clean_mode = _mc_text(selected_mode)
    if clean_mode not in {"followup", "new-task"}:
        clean_mode = "followup" if task else "new-task"
    if task:
        title = _mc_text(task.get("title"), "현재 작업")
        mode_label = f"현재 작업 계속 · {title}" if clean_mode == "followup" else "새 작업으로 분리"
        hint = "현재 작업 문맥이 유지됩니다. 새 작업이 필요하면 아래에서 새 작업으로 분리해서 보내세요."
        placeholder = f"{title}에 후속 지시를 남기거나, 새 작업으로 분리해서 다른 명령을 시작하세요."
        helper_text = "Enter 실행 · Shift+Enter 줄바꿈 · 현재 작업 초안과 새 작업 초안을 따로 유지합니다."
        if clean_mode == "new-task":
            hint = "현재 작업은 유지하고, 지금 입력하는 명령은 새 작업으로 따로 기록합니다."
            placeholder = "무엇을 해야 하는지 한 줄로 입력하세요. 현재 작업과 별개로 새 작업을 만듭니다."
            helper_text = "Enter 실행 · Shift+Enter 줄바꿈 · 새 작업 초안은 현재 작업과 따로 유지됩니다."
        return {
            "mode": "followup",
            "selected_mode": clean_mode,
            "mode_label": mode_label,
            "placeholder": placeholder,
            "hint": hint,
            "helper_text": helper_text,
            "send_button_label": "후속 지시 보내기" if clean_mode == "followup" else "새 작업 만들기",
            "mode_options": [
                {"key": "followup", "label": "현재 작업 계속"},
                {"key": "new-task", "label": "새 작업으로 분리"},
            ],
        }
    return {
        "mode": "new-task",
        "selected_mode": "new-task",
        "mode_label": "새 작업 시작",
        "placeholder": "무엇을 해야 하는지 한 줄로 입력하세요. 서버는 mobile-control 엔진에 새 작업으로 기록합니다.",
        "hint": "카드나 탭을 이해할 필요 없이, 여기서 바로 작업을 시작하면 됩니다.",
        "helper_text": "Enter 실행 · Shift+Enter 줄바꿈 · 새 작업 초안은 새로고침 뒤에도 유지됩니다.",
        "send_button_label": "새 작업 만들기",
        "mode_options": [
            {"key": "new-task", "label": "새 작업 시작"},
        ],
    }


def _mc_build_codex_max_view_model(conversation_task_id="", server_notice="", composer_mode="", project_id=""):
    state = _mc_get_state_bundle(limit=40)
    tasks = state.get("tasks") or []
    project_bundle = _build_projects_bundle(tasks, selected_project_id=project_id)
    bridge_mode = CODEX_CHAT_BRIDGE_MODE
    selected_project = project_bundle.get("selected") or {}
    selected_project_task_id = _mc_text(selected_project.get("current_task_id"))
    if bridge_mode == "thin-bridge":
        effective_task_id = _mc_text(conversation_task_id)
    else:
        effective_task_id = _mc_text(conversation_task_id, selected_project_task_id)
    current_task = _mc_pick_task(tasks, conversation_task_id=effective_task_id)
    primary_action = _mc_task_primary_action(current_task)
    bridge_payload = _mc_bridge_payload(current_task, primary_action, selected_project)
    ops_console = _mc_ops_console_bundle(current_task, primary_action)
    composer = _mc_composer_bundle(current_task, selected_mode=composer_mode)
    if bridge_mode == "thin-bridge":
        composer = {
            **composer,
            "mode": "new-task",
            "selected_mode": "new-task",
            "mode_label": "명령 입력",
            "placeholder": "무엇을 해야 하는지 한 줄로 입력하세요.",
            "hint": "한 줄 명령만 보내면 됩니다.",
            "helper_text": "Enter 실행",
            "send_button_label": "명령 보내기",
        }
    extras = {
        "projects": project_bundle.get("items") or [],
        "selected_project": selected_project,
        "selected_project_id": _mc_text(selected_project.get("id")),
        "summary_counts": _mc_summary_counts(state),
        "recent_tasks": _mc_recent_tasks(tasks, conversation_task_id=effective_task_id),
        "starter_prompts": _mc_starter_prompts(state, current_task=current_task),
    }
    public_projects = extras["projects"]
    public_selected_project = extras["selected_project"]
    public_selected_project_id = extras["selected_project_id"]
    public_summary_counts = extras["summary_counts"]
    public_recent_tasks = extras["recent_tasks"]
    public_starter_prompts = extras["starter_prompts"]
    if bridge_mode == "thin-bridge":
        public_projects = []
        public_selected_project = {}
        public_selected_project_id = ""
        public_summary_counts = []
        public_recent_tasks = []
        public_starter_prompts = []
    return {
        "status": "ok",
        "view_kind": "codex-max-minimal",
        "service_profile": CODEX_CHAT_ACTIVE_SERVICE_PROFILE,
        "service_module": CODEX_CHAT_ACTIVE_SERVICE_MODULE,
        "service_boundary": CODEX_CHAT_ACTIVE_SERVICE_BOUNDARY,
        "bridge_goal": CODEX_CHAT_BRIDGE_GOAL,
        "service_mode": "active-primary",
        "legacy_route_mode": "legacy-sidecar-not-routed",
        "page_title": "Codex Max",
        "hero_title": "Codex Max",
        "hero_copy": "명령은 여기서 시작하고, 예외 처리만 운영 콘솔로 넘깁니다.",
        "operational_mode": "normal-path-codex-max / exception-path-mobile-control",
        "bridge_mode": bridge_mode,
        "bridge": dict(bridge_payload),
        **bridge_payload,
        "conversation_task_id": _mc_text((current_task or {}).get("id")),
        "extras": extras,
        "projects": public_projects,
        "selected_project": public_selected_project,
        "selected_project_id": public_selected_project_id,
        "summary_counts": public_summary_counts,
        "recent_tasks": public_recent_tasks,
        "starter_prompts": public_starter_prompts,
        "current_task": _mc_task_card(current_task, primary_action),
        "primary_action": primary_action,
        "log_entries": _mc_task_log_entries(current_task),
        "composer": composer,
        "ops_console_url": ops_console["url"],
        "ops_console_label": ops_console["label"],
        "new_task_label": "현재 문맥 비우고 새 작업" if current_task else "새 작업 시작",
        "server_notice": _mc_text(server_notice),
    }


def _mc_action_notice(action_key, task_title=""):
    title = _mc_text(task_title, "현재 작업")
    notices = {
        "confirm-review": f"{title} 검토 완료를 기록했습니다.",
        "prepare-upload": f"{title} 업로드 준비 상태를 다시 계산했습니다.",
        "request-upload": f"{title} 업로드 승인 요청을 등록했습니다.",
        "claim-upload": f"{title} 업로드를 시작 단계로 넘겼습니다.",
        "finish-upload": f"{title} 업로드 완료를 반영했습니다.",
        "finish-post-upload-verify": f"{title} 최종 검증을 완료했습니다.",
        "fail-post-upload-verify": f"{title} 반영 검증 실패를 기록했습니다.",
        "request-redebug": f"{title} 재디버그 요청을 등록했습니다.",
        "start-redebug": f"{title} 재디버그를 시작했습니다.",
        "reflect-result": f"{title} 결과를 다시 사용자 검토 단계로 넘겼습니다.",
        "execute-now": f"{title} 실행을 시작했습니다.",
        "proceed": f"{title} 진행을 다시 시작했습니다.",
        "request-plan": f"{title} 계획 수립을 다시 요청했습니다.",
        "complete-plan": f"{title} 계획 검토 준비를 마쳤습니다.",
    }
    return notices.get(action_key, f"{title} 다음 행동을 실행했습니다.")


def _mc_run_primary_action(task_id, actor="", summary=""):
    task = _mc_get_task(task_id)
    if not task:
        raise ValueError("작업을 찾을 수 없습니다.")
    primary_action = _mc_task_primary_action(task)
    if not primary_action or primary_action.get("disabled"):
        raise ValueError("지금 바로 실행할 기본 액션이 없습니다.")
    action_key = _mc_text(primary_action.get("action"))
    clean_actor = _mc_text(actor, "unknown")
    clean_summary = _mc_text(summary)
    command_text = f"Codex Max · {primary_action.get('label') or action_key}"

    if action_key == "confirm-review":
        _mc_update_task_action(task_id, clean_actor, "confirm_review", clean_summary, command_text=command_text)
    elif action_key == "prepare-upload":
        _mc_update_task_action(task_id, clean_actor, "prepare_upload", clean_summary, command_text=command_text)
    elif action_key == "request-upload":
        _mc_update_task_action(task_id, clean_actor, "request_upload", clean_summary, command_text=command_text)
    elif action_key == "claim-upload":
        _mc_claim_upload_job_for_task(task_id, clean_actor)
    elif action_key == "finish-upload":
        _mc_finish_upload_for_task(task_id, clean_actor, summary=clean_summary, artifact_paths=None)
    elif action_key == "finish-post-upload-verify":
        _mc_finish_post_upload_verify_for_task(task_id, clean_actor, summary=clean_summary, artifact_paths=None)
    elif action_key == "fail-post-upload-verify":
        _mc_finish_post_upload_verify_failure_for_task(task_id, clean_actor, summary=clean_summary, artifact_paths=None, rollback_required=False)
    elif action_key == "request-redebug":
        _mc_update_task_action(task_id, clean_actor, "request_redebug", clean_summary, command_text=command_text)
    elif action_key == "start-redebug":
        _mc_start_task(task_id, clean_actor, command_text=command_text)
    elif action_key == "reflect-result":
        _mc_reflect_task_result_for_review(task_id, clean_actor, summary=clean_summary)
    elif action_key == "execute-now":
        _mc_update_task_action(task_id, clean_actor, "execute_now", clean_summary, command_text=command_text)
    elif action_key == "proceed":
        _mc_start_task(task_id, clean_actor, command_text=command_text)
    elif action_key == "request-plan":
        _mc_plan_task(task_id, clean_actor)
    elif action_key == "complete-plan":
        _mc_complete_task_plan_for_review(task_id, clean_actor, summary=clean_summary)
    else:
        raise ValueError("지원하지 않는 기본 액션입니다.")
    return _mc_build_codex_max_view_model(
        conversation_task_id=task_id,
        server_notice=_mc_action_notice(action_key, task.get("title")),
    )


def get_codex_chat_run_state(conversation_task_id: str = "", composer_mode: str = "", project_id: str = ""):
    return _mc_build_codex_max_view_model(
        conversation_task_id=conversation_task_id,
        composer_mode=composer_mode,
        project_id=project_id,
    )


def get_codex_chat_initial_view_model(state_file: str = "", conversation_task_id: str = "", composer_mode: str = "", project_id: str = ""):
    return _mc_build_codex_max_view_model(
        conversation_task_id=conversation_task_id,
        composer_mode=composer_mode,
        project_id=project_id,
    )


def dispatch_codex_chat_command(
    message: str,
    state_file: str = "",
    actor: str = "",
    preview_context=None,
    conversation_task_id: str = "",
    mode: str = "",
    project_id: str = "",
):
    clean_message = _mc_text(message)
    if not clean_message:
        raise ValueError("지시 내용을 입력해 주세요.")
    clean_actor = _mc_text(actor, "unknown")
    preview_context = preview_context or {}
    selected_mode = _mc_text(mode).lower()
    if selected_mode not in {"followup", "new-task"}:
        selected_mode = "followup"
    current_task = _mc_get_task(conversation_task_id) if _mc_text(conversation_task_id) else None
    if CODEX_CHAT_BRIDGE_MODE == "thin-bridge":
        selected_mode = "new-task"
        current_task = None
    target_env = _mc_text(preview_context.get("target_env"), "local")

    if current_task and selected_mode == "followup":
        updated_task = _mc_add_comment(
            _mc_text(current_task.get("id")),
            clean_actor,
            clean_message,
            kind="instruction",
            parent_check_item_id="",
            set_hold=False,
            command_text=clean_message,
        )
        _link_task_to_project(project_id, _mc_text(updated_task.get("id")), summary=_mc_text(updated_task.get("summary")), actor=clean_actor)
        return _mc_build_codex_max_view_model(
            conversation_task_id=_mc_text(updated_task.get("id")),
            server_notice=f"{_mc_text(current_task.get('title'), '현재 작업')}에 후속 지시를 남겼습니다.",
            composer_mode="followup",
            project_id=project_id,
        )

    context_tasks = []
    if CODEX_CHAT_BRIDGE_MODE == "thin-bridge":
        context_tasks = (_mc_get_state_bundle(limit=20) or {}).get("tasks") or []
    execution_message = _mc_build_contextual_command(clean_message, context_tasks)

    created_task = _mc_create_task(
        clean_message,
        clean_actor,
        target_env=target_env,
        task_type="FREEFORM",
        priority="NORMAL",
        model_profile="mobile_worker",
    )
    created_task_id = _mc_text(created_task.get("id"))
    _link_task_to_project(project_id, created_task_id, summary=_mc_text(created_task.get("summary")), actor=clean_actor)
    if _mc_text(project_id):
        _mc_plan_task(created_task_id, clean_actor)
    if CODEX_CHAT_BRIDGE_MODE == "thin-bridge":
        created_task = _mc_start_task(created_task_id, clean_actor, command_text=execution_message)
    return _mc_build_codex_max_view_model(
        conversation_task_id=_mc_text(created_task.get("id"), created_task_id),
        server_notice="명령을 로컬 Codex 실행기로 전달했습니다.",
        composer_mode="new-task" if CODEX_CHAT_BRIDGE_MODE == "thin-bridge" else "followup",
        project_id=project_id,
    )


def run_codex_chat_primary_action(task_id: str, actor: str = "", summary: str = "", project_id: str = ""):
    clean_task_id = _mc_text(task_id)
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    payload = _mc_run_primary_action(clean_task_id, actor=actor, summary=summary)
    if not _mc_text(project_id):
        return payload
    return _mc_build_codex_max_view_model(
        conversation_task_id=clean_task_id,
        composer_mode="followup",
        project_id=project_id,
        server_notice=_mc_text(payload.get("server_notice")),
    )


def create_codex_chat_project(title: str, goal: str, actor: str = ""):
    project = _create_project(title, goal, actor=actor)
    return _mc_build_codex_max_view_model(
        conversation_task_id="",
        composer_mode="new-task",
        project_id=_mc_text(project.get("id")),
        server_notice=f"{_mc_text(project.get('title'), '새 프로젝트')} 프로젝트를 만들었습니다.",
    )


def approve_codex_chat_project(project_id: str, actor: str = ""):
    project = _approve_project(project_id, actor=actor)
    task_id = _mc_text(project.get("current_task_id"))
    if task_id:
        auto_actions = {"execute-now", "proceed", "complete-plan", "request-plan"}
        last_view = None
        for _ in range(3):
            task = _mc_get_task(task_id)
            primary_action = _mc_task_primary_action(task)
            action_key = _mc_text((primary_action or {}).get("action"))
            if action_key not in auto_actions or bool((primary_action or {}).get("disabled")):
                break
            last_view = run_codex_chat_primary_action(
                task_id,
                actor=actor,
                summary="프로젝트 승인 후 자동 실행",
                project_id=_mc_text(project.get("id")),
            )
            if action_key in {"execute-now", "proceed"}:
                return last_view
        if last_view:
            return last_view
    return _mc_build_codex_max_view_model(
        conversation_task_id=task_id,
        composer_mode="followup" if task_id else "new-task",
        project_id=_mc_text(project.get("id")),
        server_notice=f"{_mc_text(project.get('title'), '프로젝트')} 계획을 승인했습니다.",
    )


__all__ = [
    "CODEX_CHAT_ACTIVE_SERVICE_PROFILE",
    "CODEX_CHAT_ACTIVE_SERVICE_MODULE",
    "CODEX_CHAT_ACTIVE_SERVICE_BOUNDARY",
    "CODEX_CHAT_BRIDGE_MODE",
    "CODEX_CHAT_BRIDGE_GOAL",
    "get_codex_chat_run_state",
    "get_codex_chat_initial_view_model",
    "dispatch_codex_chat_command",
    "run_codex_chat_primary_action",
    "create_codex_chat_project",
    "approve_codex_chat_project",
]
