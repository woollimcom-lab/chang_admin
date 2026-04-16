import json
import sqlite3
import subprocess
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
MOBILE_DIR = OUTPUT_DIR / "mobile_control"
DB_PATH = MOBILE_DIR / "mobile_control_v2.sqlite3"
RUNTIME_DIR = MOBILE_DIR / "runtime"
RUNTIME_FILE = RUNTIME_DIR / "runtime.json"
CANDIDATE_RUNTIME_FILE = RUNTIME_DIR / "candidate-worker.json"
STATUS_DISPATCH_FILE = RUNTIME_DIR / "mobile-control-status-dispatch.json"
SUPPORT_ACTION_FILE = RUNTIME_DIR / "local-server-support-action.json"
SUPPORT_ACTION_SCRIPT = BASE_DIR / "scripts" / "run_local_server_support_action.ps1"
LEGACY_COMMANDS_FILE = MOBILE_DIR / "commands.json"
LEGACY_AUTO_IMPORT_ENABLED = False

TASK_STATUS_LABELS = {
    "QUEUED": "대기",
    "CLAIMED": "할당",
    "PLANNING": "계획 수립",
    "CHECKLIST_ISSUED": "체크리스트 발행",
    "RUNNING": "진행",
    "WAITING_REVIEW": "검토 대기",
    "READY_TO_UPLOAD": "업로드 준비",
    "UPLOAD_REQUESTED": "업로드 승인 요청",
    "UPLOADING": "업로드 중",
    "POST_UPLOAD_VERIFY": "업로드 후 검증",
    "DONE": "완료",
    "HOLD": "보류",
    "FAILED": "실패",
    "DISCARDED": "폐기",
    "CANCELED": "중지",
    "IDLE": "대기중",
    "STALE": "응답없음",
}

CHECK_STATUS_LABELS = {
    "TODO": "대기",
    "IN_PROGRESS": "진행",
    "DONE": "완료",
    "FAILED": "실패",
    "DISCARDED": "폐기",
    "BLOCKED": "차단",
}

QUICK_ACTIONS = [
    {"label": "로컬 상태 점검", "text": "로컬 상태 점검 실행", "task_key": "health_check"},
    {"label": "최신 스크린샷", "text": "최신 화면 스크린샷 생성", "task_key": "capture_latest"},
    {"label": "업로드 준비 요약", "text": "업로드 준비 상태 요약 생성", "task_key": "prepare_upload_summary"},
]

QUICK_LINKS = [
    {"label": "대시보드", "href": "/dashboard"},
    {"label": "통계", "href": "/stats"},
    {"label": "관리", "href": "/admin"},
    {"label": "샘플 주문", "href": "/view/17701"},
]

CHECKLIST_SECTIONS = [
    ("INPUT", "입력 확인", "요청 범위와 작업 대상이 맞는지 확인합니다.", 1, 1, "검토자"),
    ("PLAN", "계획 확인", "영향 범위와 실행 계획, 롤백 방향을 확인합니다.", 1, 1, "검토자"),
    ("EXECUTION", "실행 확인", "실제 수정과 실행 로그, 산출물 생성을 확인합니다.", 1, 1, "작업"),
    ("VERIFICATION", "검증 확인", "테스트, 스크린샷, 파일 검수 결과를 확인합니다.", 1, 1, "검토자"),
    ("UPLOAD", "업로드 준비", "업로드 대상, 승인 조건, 후속 검증 계획을 확인합니다.", 1, 1, "검토자"),
]

LEGACY_STATUS_MAP = {
    "대기": "QUEUED",
    "진행": "HOLD",
    "완료": "DONE",
    "보류": "HOLD",
}

ACTIVE_TASK_STATUSES = {
    "CLAIMED",
    "PLANNING",
    "CHECKLIST_ISSUED",
    "RUNNING",
    "UPLOAD_REQUESTED",
    "UPLOADING",
    "POST_UPLOAD_VERIFY",
}

HEARTBEAT_OK_WINDOW_SECONDS = 30
HEARTBEAT_STALE_WINDOW_HOURS = 12

TASK_STATUS_LABELS = {
    "QUEUED": "대기",
    "CLAIMED": "할당",
    "PLANNING": "계획 수립 중",
    "CHECKLIST_ISSUED": "체크리스트 발행",
    "WAITING_APPROVAL": "실행 승인 대기",
    "RUNNING": "코드 수정 중",
    "SELF_REVIEW": "자체 검수 중",
    "WAITING_USER_CHECK": "사용자 검토 대기",
    "WAITING_REVIEW": "사용자 검토 대기",
    "REVISION_REQUESTED": "재디버그 요청",
    "REDEBUG_RUNNING": "재디버그 진행 중",
    "READY_TO_UPLOAD": "업로드 승인 대기",
    "UPLOAD_APPROVED": "업로드 승인됨",
    "UPLOAD_REQUESTED": "업로드 승인됨",
    "UPLOADING": "업로드 중",
    "POST_UPLOAD_VERIFY": "업로드 후 검증 대기",
    "UPLOAD_VERIFY_FAILED": "반영 검증 실패",
    "DONE": "최종 완료",
    "HOLD": "보류",
    "FAILED": "실패",
    "DISCARDED": "폐기",
    "CANCELED": "취소",
    "IDLE": "대기중",
    "STALE": "응답 없음",
}

CHECK_STATUS_LABELS = {
    "TODO": "대기",
    "PENDING": "대기",
    "IN_PROGRESS": "진행",
    "DONE": "완료",
    "FAILED": "실패",
    "CHANGE_REQUESTED": "변경요청",
    "DISCARDED": "폐기",
    "BLOCKED": "차단",
}

TASK_TYPE_LABELS = {
    "FREEFORM": "일반 지시",
    "AUTOMATION": "자동 작업",
    "REVIEW_REQUEST": "결과 재검토",
    "REDEBUG_REQUEST": "실패 재디버그",
    "CHECKLIST_REVISION": "체크리스트 후속 수정",
    "UPLOAD_REQUEST": "서버 업로드 승인",
}

PRIORITY_VALUES = {"LOW", "NORMAL", "HIGH", "URGENT"}
MODEL_PROFILE_VALUES = {"mobile_worker", "dev_auto", "deploy_candidate", "full_access_isolated"}
MODEL_NAME_VALUES = {"", "gpt-5.4", "gpt-5.4-mini", "gpt-5.2"}
REASONING_EFFORT_VALUES = {"", "low", "medium", "high", "xhigh"}

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS mobile_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    task_key TEXT DEFAULT '',
    model_profile TEXT DEFAULT 'mobile_worker',
    status TEXT NOT NULL,
    target_env TEXT DEFAULT 'local',
    target_branch TEXT DEFAULT 'mobile-control-v2',
    progress_percent INTEGER DEFAULT 0,
    current_step_code TEXT DEFAULT '',
    current_step_label TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    assigned_worker_id TEXT DEFAULT '',
    current_run_id TEXT DEFAULT '',
    lease_token TEXT DEFAULT '',
    lease_expires_at TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_tasks_status_updated
    ON mobile_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS mobile_check_items (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    section TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    required INTEGER NOT NULL DEFAULT 1,
    blocking INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'TODO',
    evidence_type TEXT DEFAULT '',
    evidence_ref TEXT DEFAULT '',
    note TEXT DEFAULT '',
    owner_role TEXT DEFAULT '',
    updated_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_check_items_task
    ON mobile_check_items(task_id, section, created_at);

CREATE TABLE IF NOT EXISTS mobile_artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_artifacts_task
    ON mobile_artifacts(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mobile_worker_heartbeats (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    task_id TEXT DEFAULT '',
    run_id TEXT DEFAULT '',
    state TEXT NOT NULL,
    progress_percent INTEGER DEFAULT 0,
    current_step_code TEXT DEFAULT '',
    current_step_label TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    latest_artifact_ids_json TEXT DEFAULT '[]',
    lease_expires_at TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_worker_heartbeats_task
    ON mobile_worker_heartbeats(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mobile_task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    parent_check_item_id TEXT DEFAULT '',
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_task_comments_task
    ON mobile_task_comments(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mobile_task_events (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_task_events_task
    ON mobile_task_events(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mobile_task_messages (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_task_messages_task
    ON mobile_task_messages(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mobile_upload_jobs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    target_env TEXT NOT NULL,
    approved_by TEXT DEFAULT '',
    result_summary TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mobile_upload_jobs_task
    ON mobile_upload_jobs(task_id, created_at DESC);
"""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _connect():
    MOBILE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn, table_name, column_name, column_sql):
    columns = _table_columns(conn, table_name)
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _ensure_schema_updates(conn):
    _ensure_column(conn, "mobile_tasks", "model_profile", "model_profile TEXT DEFAULT 'mobile_worker'")
    _ensure_column(conn, "mobile_tasks", "model_name", "model_name TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_tasks", "reasoning_effort", "reasoning_effort TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_tasks", "task_type", "task_type TEXT DEFAULT 'FREEFORM'")
    _ensure_column(conn, "mobile_tasks", "priority", "priority TEXT DEFAULT 'NORMAL'")
    _ensure_column(conn, "mobile_tasks", "plan_summary_json", "plan_summary_json TEXT DEFAULT '{}'")
    _ensure_column(conn, "mobile_tasks", "result_payload_json", "result_payload_json TEXT DEFAULT '{}'")
    _ensure_column(conn, "mobile_tasks", "self_review_json", "self_review_json TEXT DEFAULT '{}'")
    _ensure_column(conn, "mobile_tasks", "next_action", "next_action TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_tasks", "followup_bundle_json", "followup_bundle_json TEXT DEFAULT '{}'")
    _ensure_column(conn, "mobile_tasks", "final_decision", "final_decision TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_check_items", "parent_item_id", "parent_item_id TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_check_items", "order_no", "order_no INTEGER DEFAULT 0")
    _ensure_column(conn, "mobile_check_items", "related_files_json", "related_files_json TEXT DEFAULT '[]'")
    _ensure_column(conn, "mobile_check_items", "test_required", "test_required INTEGER DEFAULT 0")
    _ensure_column(conn, "mobile_check_items", "user_confirmation_required", "user_confirmation_required INTEGER DEFAULT 1")
    _ensure_column(conn, "mobile_check_items", "discard_reason", "discard_reason TEXT DEFAULT ''")
    _ensure_column(conn, "mobile_check_items", "result_summary", "result_summary TEXT DEFAULT ''")


def _normalize_legacy_status(raw_status):
    status = LEGACY_STATUS_MAP.get(str(raw_status or "").strip())
    if status:
        return status
    return "QUEUED"


def _record_event(conn, task_id, event_type, actor_type, actor_id, payload=None):
    conn.execute(
        """
        INSERT INTO mobile_task_events (
            id, task_id, event_type, actor_type, actor_id, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            task_id,
            event_type,
            actor_type,
            actor_id,
            json.dumps(payload or {}, ensure_ascii=False),
            _now(),
        ),
    )


def _append_task_message(conn, task_id, role, message_type, content):
    message = str(content or "").strip()
    if not message:
        return
    conn.execute(
        """
        INSERT INTO mobile_task_messages (
            id, task_id, role, message_type, content, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, task_id, str(role or "system"), str(message_type or "status"), message, _now()),
    )


def _append_user_command_message(conn, task_id, command_text):
    message = str(command_text or "").strip()
    if not message:
        return
    _append_task_message(conn, task_id, "user", "chat", message)


def _serialize_message(row):
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "message_type": row["message_type"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def initialize_database():
    with _connect() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_schema_updates(conn)
        task_count = conn.execute("SELECT COUNT(*) AS count FROM mobile_tasks").fetchone()["count"]
        if task_count or (not LEGACY_AUTO_IMPORT_ENABLED) or not LEGACY_COMMANDS_FILE.exists():
            return
        try:
            payload = json.loads(LEGACY_COMMANDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        commands = payload.get("commands") or []
        for item in reversed(list(commands)):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            now = str(item.get("updated_at") or item.get("created_at") or _now())
            task_id = str(item.get("id") or f"legacy-{uuid.uuid4().hex[:10]}")
            status = _normalize_legacy_status(item.get("status"))
            summary = str(item.get("result") or "")
            conn.execute(
                """
                INSERT OR IGNORE INTO mobile_tasks (
                    id, title, text, task_key, status, target_env, target_branch, progress_percent,
                    current_step_code, current_step_label, summary, created_by, updated_by,
                    assigned_worker_id, current_run_id, lease_token, lease_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'local', 'mobile-control-v1', ?, 'legacy', '기존 데이터',
                          ?, ?, ?, '', '', '', '', ?, ?)
                """,
                (
                    task_id,
                    text.splitlines()[0][:80],
                    text,
                    str(item.get("task_key") or ""),
                    status,
                    100 if status == "DONE" else 0,
                    summary,
                    str(item.get("created_by") or "legacy"),
                    str(item.get("updated_by") or item.get("created_by") or "legacy"),
                    str(item.get("created_at") or now),
                    now,
                ),
            )


def _normalize_task_type(task_type, task_key=""):
    raw = str(task_type or "").strip().upper()
    if raw in TASK_TYPE_LABELS:
        return raw
    if str(task_key or "").strip():
        return "AUTOMATION"
    return "FREEFORM"


def _normalize_priority(priority):
    raw = str(priority or "").strip().upper()
    if raw in PRIORITY_VALUES:
        return raw
    return "NORMAL"


def _normalize_model_profile(model_profile):
    raw = str(model_profile or "").strip()
    if raw in MODEL_PROFILE_VALUES:
        return raw
    return "mobile_worker"


def _normalize_model_name(model_name):
    raw = str(model_name or "").strip()
    if raw in MODEL_NAME_VALUES:
        return raw
    return ""


def _normalize_reasoning_effort(reasoning_effort):
    raw = str(reasoning_effort or "").strip().lower()
    if raw in REASONING_EFFORT_VALUES:
        return raw
    return ""


def _default_plan_summary(text, task_type, target_env):
    instruction = str(text or "").strip()
    first_line = instruction.splitlines()[0].strip() if instruction else "모바일 지시 작업"
    verification_plan = [
        "관련 수정 파일 검수",
        "핵심 페이지/기능 스모크 확인",
        "체크리스트 기준 사용자 확인 항목 정리",
    ]
    risk_points = [
        "작업 범위를 넘는 파일 변경 금지",
        "모바일 UI와 기존 동작 회귀 여부 확인 필요",
    ]
    if str(target_env or "").strip().lower() in {"candidate", "production"}:
        risk_points.append("업로드 대상 환경과 실제 반영 범위를 분리해서 확인 필요")
    return {
        "goal": first_line,
        "target_files": [],
        "impact_scope": "요청 범위 기준 최소 수정",
        "verification_plan": verification_plan,
        "risk_points": risk_points,
        "task_type": _normalize_task_type(task_type),
    }


def _default_result_payload(text):
    return {
        "original_instruction": str(text or "").strip(),
        "attachments": [],
        "changed_files": [],
        "implemented_features": [],
        "result_list": [],
        "checklist_items": [],
        "latest_summary": "",
    }


def _default_self_review():
    return {
        "affected_files": [],
        "affected_modules": [],
        "side_effects": "",
        "regression_risks": [],
        "verification_summary": "",
    }


def _default_followup_bundle():
    return {
        "status": "NONE",
        "instruction": "",
        "items": [],
        "comments": [],
        "created_at": "",
    }


def _task_plan_summary(row):
    return _json_loads(row["plan_summary_json"] if "plan_summary_json" in row.keys() else "", _default_plan_summary(row["text"], row["task_type"] if "task_type" in row.keys() else "FREEFORM", row["target_env"]))


def _task_result_payload(row):
    payload = _json_loads(row["result_payload_json"] if "result_payload_json" in row.keys() else "", _default_result_payload(row["text"]))
    payload.setdefault("original_instruction", row["text"])
    payload.setdefault("attachments", [])
    payload.setdefault("changed_files", [])
    payload.setdefault("implemented_features", [])
    payload.setdefault("result_list", [])
    payload.setdefault("checklist_items", [])
    payload.setdefault("latest_summary", row["summary"] or "")
    return payload


def _normalize_task_attachments(items):
    normalized = []
    for item in items or []:
        path = str((item or {}).get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        label = str((item or {}).get("label") or "").strip() or Path(path).name
        suffix = Path(path).suffix.lower()
        raw_kind = str((item or {}).get("kind") or "").strip()
        kind = raw_kind if raw_kind in {"input_image", "input_file"} else ("input_image" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "input_file")
        normalized.append(
            {
                "kind": kind,
                "label": label,
                "path": path,
                "name": Path(path).name,
            }
        )
    return normalized


def _output_artifacts_only(artifacts):
    return [item for item in (artifacts or []) if str(item.get("kind") or "") not in {"input_image", "input_file"}]


def _task_self_review(row):
    review = _json_loads(row["self_review_json"] if "self_review_json" in row.keys() else "", _default_self_review())
    review.setdefault("affected_files", [])
    review.setdefault("affected_modules", [])
    review.setdefault("side_effects", "")
    review.setdefault("regression_risks", [])
    review.setdefault("verification_summary", "")
    return review


def _task_followup_bundle(row):
    bundle = _json_loads(row["followup_bundle_json"] if "followup_bundle_json" in row.keys() else "", _default_followup_bundle())
    bundle.setdefault("status", "NONE")
    bundle.setdefault("instruction", "")
    bundle.setdefault("items", [])
    bundle.setdefault("comments", [])
    bundle.setdefault("created_at", "")
    return bundle


def _build_checklist_summary(check_items):
    counts = defaultdict(int)
    for item in check_items:
        counts[item["status"]] += 1
    return {
        "total": len(check_items),
        "pending": counts["PENDING"] + counts["TODO"] + counts["IN_PROGRESS"],
        "done": counts["DONE"],
        "failed": counts["FAILED"],
        "blocked": counts["BLOCKED"],
        "change_requested": counts["CHANGE_REQUESTED"],
        "discarded": counts["DISCARDED"],
        "completed": counts["DONE"] + counts["DISCARDED"],
        "blocking_failed": any(item["blocking"] and item["status"] == "FAILED" for item in check_items),
        "blocking_blocked": any(item["blocking"] and item["status"] == "BLOCKED" for item in check_items),
    }


def _can_finalize_task(check_items, self_review, artifacts):
    output_artifacts = _output_artifacts_only(artifacts)
    if not output_artifacts:
        return False
    if not (self_review.get("verification_summary") or self_review.get("affected_files")):
        return False
    open_items = [item for item in check_items if item["status"] not in {"DONE", "DISCARDED"}]
    failed = [item for item in check_items if item["status"] in {"FAILED", "CHANGE_REQUESTED", "BLOCKED"}]
    return not open_items and not failed


def _build_followup_bundle(task_row, check_items, comments):
    failed_items = [
        {
            "check_item_id": item["id"],
            "section": item["section"],
            "title": item["title"],
            "status": item["status"],
            "note": item["note"],
        }
        for item in check_items
        if item["status"] in {"FAILED", "CHANGE_REQUESTED"}
    ]
    comment_items = [
        {
            "id": comment["id"],
            "kind": comment["kind"],
            "body": comment["body"],
            "created_by": comment["created_by"],
            "created_at": comment["created_at"],
            "parent_check_item_id": comment.get("parent_check_item_id", ""),
        }
        for comment in comments
        if comment.get("parent_check_item_id") or comment.get("kind") in {"instruction", "followup_instruction", "change_request"}
    ]
    parts = []
    for item in failed_items:
        note = f" / 코멘트: {item['note']}" if item["note"] else ""
        parts.append(f"- [{item['status']}] {item['title']}{note}")
    for comment in comment_items:
        if comment["body"]:
            parts.append(f"- {comment['body']}")
    instruction = "\n".join(parts).strip()
    return {
        "status": "READY" if instruction else "NONE",
        "instruction": instruction,
        "items": failed_items,
        "comments": comment_items,
        "created_at": _now() if instruction else "",
        "task_id": task_row["id"],
    }


def _build_progress_updates(heartbeat_rows, event_rows):
    updates = []
    for row in heartbeat_rows[:8]:
        updates.append(
            {
                "kind": "heartbeat",
                "at": row["created_at"],
                "status": row["state"],
                "status_label": TASK_STATUS_LABELS.get(row["state"], row["state"]),
                "progress_percent": int(row["progress_percent"] or 0),
                "step_code": row["current_step_code"] or "",
                "step_label": row["current_step_label"] or "",
                "summary": row["summary"] or "",
            }
        )
    for row in event_rows[:8]:
        updates.append(
            {
                "kind": "event",
                "at": row["created_at"],
                "event_type": row["event_type"],
                "summary": row["event_type"],
            }
        )
    updates.sort(key=lambda item: item.get("at", ""), reverse=True)
    return updates[:12]


def _serialize_check_item(row):
    status = row["status"] or "PENDING"
    return {
        "id": row["id"],
        "section": row["section"],
        "title": row["title"],
        "description": row["description"] or "",
        "required": bool(row["required"]),
        "blocking": bool(row["blocking"]),
        "status": status,
        "status_label": CHECK_STATUS_LABELS.get(status, status),
        "note": row["note"] or "",
        "owner_role": row["owner_role"] or "",
        "updated_by": row["updated_by"] or "",
        "updated_at": row["updated_at"] or "",
        "parent_item_id": row["parent_item_id"] if "parent_item_id" in row.keys() else "",
        "order_no": int(row["order_no"] or 0) if "order_no" in row.keys() else 0,
        "related_files": _json_loads(row["related_files_json"] if "related_files_json" in row.keys() else "", []),
        "test_required": bool(row["test_required"]) if "test_required" in row.keys() else False,
        "user_confirmation_required": bool(row["user_confirmation_required"]) if "user_confirmation_required" in row.keys() else True,
        "discard_reason": row["discard_reason"] if "discard_reason" in row.keys() else "",
        "result_summary": row["result_summary"] if "result_summary" in row.keys() else "",
        "is_derived": bool((row["parent_item_id"] if "parent_item_id" in row.keys() else "") or False),
    }


def _serialize_artifact(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "label": row["label"],
        "path": row["path"],
        "name": Path(row["path"]).name,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


def _serialize_comment(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "body": row["body"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "parent_check_item_id": row["parent_check_item_id"] or "",
    }


def _serialize_event(row):
    payload = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except Exception:
        payload = {}
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "payload": payload,
        "created_at": row["created_at"],
    }


def _serialize_upload_job(row):
    return {
        "id": row["id"],
        "status": row["status"],
        "target_env": row["target_env"] or "",
        "approved_by": row["approved_by"] or "",
        "result_summary": row["result_summary"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_sections(items):
    sections = []
    for code, label, _desc, _required, _blocking, _owner in CHECKLIST_SECTIONS:
        section_items = [item for item in items if item["section"] == code]
        children_by_parent = {}
        for item in section_items:
            parent_id = str(item.get("parent_item_id") or "")
            if parent_id:
                children_by_parent.setdefault(parent_id, []).append(item)
        ordered_items = []
        roots = [item for item in section_items if not str(item.get("parent_item_id") or "")]
        roots.sort(key=lambda item: (int(item.get("order_no") or 0), item.get("created_at") or "", item.get("title") or ""))
        for root in roots:
            ordered_items.append(root)
            children = children_by_parent.get(root.get("id"), [])
            children.sort(key=lambda item: (int(item.get("order_no") or 0), item.get("created_at") or "", item.get("title") or ""))
            ordered_items.extend(children)
        orphan_children = [item for item in section_items if str(item.get("parent_item_id") or "") and item not in ordered_items]
        orphan_children.sort(key=lambda item: (int(item.get("order_no") or 0), item.get("created_at") or "", item.get("title") or ""))
        ordered_items.extend(orphan_children)
        sections.append({"code": code, "label": label, "items": ordered_items})
    return sections

def _upload_gate(task_row, check_items, artifacts, latest_heartbeat):
    reasons = []
    output_artifacts = _output_artifacts_only(artifacts)
    required_pending = [item for item in check_items if item["required"] and item["status"] not in {"DONE", "DISCARDED"}]
    blocking_fail = [item for item in check_items if item["blocking"] and item["status"] in {"FAILED", "BLOCKED"}]
    if required_pending:
        reasons.append("필수 체크리스트가 아직 남아 있습니다.")
    if blocking_fail:
        reasons.append("차단 항목의 실패가 있습니다.")
    if not output_artifacts:
        reasons.append("최신 산출물이 없습니다.")
    target_env = (task_row["target_env"] or "").strip().lower()
    if not target_env or target_env == "local":
        reasons.append("업로드 대상이 후보/운영으로 지정되지 않았습니다.")
    if not latest_heartbeat:
        reasons.append("최근 워커 실행 기록이 없습니다.")
    else:
        heartbeat_time = _parse_time(latest_heartbeat["created_at"])
        if not heartbeat_time or datetime.now() - heartbeat_time > timedelta(hours=HEARTBEAT_STALE_WINDOW_HOURS):
            reasons.append("최근 워커 실행 기록이 오래되었습니다.")
        if latest_heartbeat["state"] == "FAILED":
            reasons.append("최근 워커 실행이 실패했습니다.")
    can_request_upload = (not reasons) and task_row["status"] in {"WAITING_REVIEW", "READY_TO_UPLOAD", "HOLD"}
    return {"can_request_upload": can_request_upload, "reasons": reasons}


def _sync_ready_to_upload(conn, task_id):
    task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task_row:
        return {"can_request_upload": False, "reasons": ["작업을 찾을 수 없습니다."]}
    check_rows = conn.execute(
        "SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    ).fetchall()
    artifact_rows = conn.execute(
        "SELECT * FROM mobile_artifacts WHERE task_id = ? ORDER BY created_at DESC",
        (task_id,),
    ).fetchall()
    latest_heartbeat = conn.execute(
        "SELECT * FROM mobile_worker_heartbeats WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    gate = _upload_gate(
        task_row,
        [_serialize_check_item(row) for row in check_rows],
        [_serialize_artifact(row) for row in artifact_rows],
        latest_heartbeat,
    )
    if gate["can_request_upload"] and task_row["status"] in {"WAITING_REVIEW", "HOLD"}:
        conn.execute(
            "UPDATE mobile_tasks SET status = 'READY_TO_UPLOAD', updated_at = ?, updated_by = 'system' WHERE id = ?",
            (_now(), task_id),
        )
    elif (not gate["can_request_upload"]) and task_row["status"] == "READY_TO_UPLOAD":
        conn.execute(
            "UPDATE mobile_tasks SET status = 'WAITING_REVIEW', updated_at = ?, updated_by = 'system' WHERE id = ?",
            (_now(), task_id),
        )
    return gate


def _latest_upload_job_row(conn, task_id):
    return conn.execute(
        "SELECT * FROM mobile_upload_jobs WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()


def _recent_file_links(limit=12):
    initialize_database()
    items = []
    patterns = (
        ("playwright", "*.png", "스크린샷"),
        ("mobile_control", "*.json", "모바일"),
        ("mobile_control", "*.md", "모바일"),
        ("night_auto", "*.json", "자동화"),
        ("night_auto", "*.txt", "자동화"),
        ("data_seed", "*.json", "데이터"),
        ("data_seed", "*.txt", "데이터"),
    )
    for folder_name, pattern, label in patterns:
        folder = OUTPUT_DIR / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob(pattern):
            if not path.is_file() or path.suffix == ".sqlite3":
                continue
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "path": path.relative_to(OUTPUT_DIR).as_posix(),
                    "label": label,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%m/%d %H:%M"),
                    "sort_key": stat.st_mtime,
                }
            )
    items.sort(key=lambda item: item["sort_key"], reverse=True)
    return items[:limit]


def _worker_status():
    initialize_database()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM mobile_worker_heartbeats ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"state": "중지", "message": "아직 워커 heartbeat가 없습니다.", "updated_at": ""}
    created_at = _parse_time(row["created_at"])
    age = (datetime.now() - created_at).total_seconds() if created_at else 9999
    if age > HEARTBEAT_OK_WINDOW_SECONDS:
        return {"state": "응답없음", "message": "최근 heartbeat가 30초 이상 지연되었습니다.", "updated_at": row["created_at"]}
    if row["state"] == "IDLE":
        return {"state": "대기중", "message": row["summary"] or "워커가 대기 중입니다.", "updated_at": row["created_at"]}
    return {
        "state": TASK_STATUS_LABELS.get(row["state"], row["state"]),
        "message": row["summary"] or row["current_step_label"] or "워커가 작업 중입니다.",
        "updated_at": row["created_at"],
    }


def _load_runtime_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _runtime_info():
    runtime = _load_runtime_json(RUNTIME_FILE)
    candidate_runtime = _load_runtime_json(CANDIDATE_RUNTIME_FILE)
    status_dispatch = _load_runtime_json(STATUS_DISPATCH_FILE)
    published = runtime.get("published") if isinstance(runtime.get("published"), dict) else {}
    tunnel_url = str(runtime.get("tunnel_url") or "").strip().rstrip("/")
    published_relative = str(published.get("server_relative_html_url") or "").strip()
    remote_host = str(published.get("remote_host") or "").strip()
    fixed_mobile_control_url = ""
    if remote_host and published_relative:
        fixed_mobile_control_url = f"http://{remote_host}{published_relative}"
    candidate_base_url = str(candidate_runtime.get("remote_base_url") or "").strip().rstrip("/")
    dispatch_state = str(status_dispatch.get("dispatch_state") or "").strip()
    operator_ready = bool(status_dispatch.get("operator_ready"))
    local_mobile_control_url = str(status_dispatch.get("local_mobile_control_url") or "").strip()
    published_mobile_control_url = str(status_dispatch.get("published_mobile_control_url") or "").strip()
    dispatch_next_command = str(status_dispatch.get("next_command") or "").strip()
    primary_action_kind = "run-support"
    primary_action_label = "Support 준비 실행"
    primary_action_target = str(status_dispatch.get("support_cmd") or "").strip()
    primary_action_summary = str(status_dispatch.get("operator_summary") or "").strip()
    if operator_ready and dispatch_state == "ready-for-feature-flow":
        primary_action_kind = "open-url"
        primary_action_label = "모바일 컨트롤 열기"
        primary_action_target = dispatch_next_command or local_mobile_control_url or published_mobile_control_url
        primary_action_summary = str(status_dispatch.get("action_summary") or "").strip()
    return {
        "codex_profile": str(runtime.get("codex_profile") or "mobile_worker").strip() or "mobile_worker",
        "tunnel_url": tunnel_url,
        "mobile_control_url": f"{tunnel_url}/mobile-control" if tunnel_url else "",
        "fixed_mobile_control_url": fixed_mobile_control_url,
        "fixed_mobile_control_relative_url": published_relative,
        "candidate_preview_url": f"{candidate_base_url}/mobile-control" if candidate_base_url else "",
        "updated_at": str(runtime.get("updated_at") or "").strip(),
        "publish_status": str(published.get("status") or "").strip(),
        "remote_host": remote_host,
        "dispatch_state": str(status_dispatch.get("dispatch_state") or "").strip(),
        "dispatch_bucket": str(status_dispatch.get("dispatch_bucket") or "").strip(),
        "local_runtime_ready": bool(status_dispatch.get("local_runtime_ready")),
        "operator_ready": bool(status_dispatch.get("operator_ready")),
        "operator_ready_summary": str(status_dispatch.get("operator_ready_summary") or "").strip(),
        "dispatch_operator_summary": str(status_dispatch.get("operator_summary") or "").strip(),
        "dispatch_action_summary": str(status_dispatch.get("action_summary") or "").strip(),
        "dispatch_next_command": str(status_dispatch.get("next_command") or "").strip(),
        "dispatch_support_cmd": str(status_dispatch.get("support_cmd") or "").strip(),
        "dispatch_status_cmd": str(status_dispatch.get("status_cmd") or "").strip(),
        "local_mobile_control_url": local_mobile_control_url,
        "published_mobile_control_url": published_mobile_control_url,
        "status_dispatch_updated_at": str(status_dispatch.get("generated_at") or "").strip(),
        "primary_action_kind": primary_action_kind,
        "primary_action_label": primary_action_label,
        "primary_action_target": primary_action_target,
        "primary_action_summary": primary_action_summary,
    }


def run_mobile_control_support_action():
    if not SUPPORT_ACTION_SCRIPT.exists():
        raise RuntimeError(f"support action script not found: {SUPPORT_ACTION_SCRIPT}")
    process = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SUPPORT_ACTION_SCRIPT),
            "-NoOpen",
            "-IncludeFixtureAudit",
        ],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip() or "support action failed"
        raise RuntimeError(detail)
    support_action = _load_runtime_json(SUPPORT_ACTION_FILE)
    support_action["stdout"] = (process.stdout or "").strip()
    support_action["stderr"] = (process.stderr or "").strip()
    support_action["exit_code"] = process.returncode
    return support_action


def list_tasks(limit=40):
    initialize_database()
    with _connect() as conn:
        task_rows = conn.execute(
            "SELECT * FROM mobile_tasks ORDER BY updated_at DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        task_ids = [row["id"] for row in task_rows]
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        check_rows = conn.execute(
            f"SELECT * FROM mobile_check_items WHERE task_id IN ({placeholders}) ORDER BY created_at ASC",
            task_ids,
        ).fetchall()
        artifact_rows = conn.execute(
            f"SELECT * FROM mobile_artifacts WHERE task_id IN ({placeholders}) ORDER BY created_at DESC",
            task_ids,
        ).fetchall()
        comment_rows = conn.execute(
            f"SELECT * FROM mobile_task_comments WHERE task_id IN ({placeholders}) ORDER BY created_at DESC",
            task_ids,
        ).fetchall()
        event_rows = conn.execute(
            f"SELECT * FROM mobile_task_events WHERE task_id IN ({placeholders}) ORDER BY created_at DESC",
            task_ids,
        ).fetchall()
        latest_rows = conn.execute(
            f"""
            SELECT h.* FROM mobile_worker_heartbeats h
            JOIN (
                SELECT task_id, MAX(created_at) AS latest_created_at
                FROM mobile_worker_heartbeats
                WHERE task_id IN ({placeholders})
                GROUP BY task_id
            ) latest
            ON latest.task_id = h.task_id AND latest.latest_created_at = h.created_at
            """,
            task_ids,
        ).fetchall()
        upload_rows = conn.execute(
            f"""
            SELECT u.* FROM mobile_upload_jobs u
            JOIN (
                SELECT task_id, MAX(created_at) AS latest_created_at
                FROM mobile_upload_jobs
                WHERE task_id IN ({placeholders})
                GROUP BY task_id
            ) latest
            ON latest.task_id = u.task_id AND latest.latest_created_at = u.created_at
            """,
            task_ids,
        ).fetchall()
    check_map = {}
    for row in check_rows:
        check_map.setdefault(row["task_id"], []).append(_serialize_check_item(row))
    artifact_map = {}
    for row in artifact_rows:
        artifact_map.setdefault(row["task_id"], []).append(_serialize_artifact(row))
    comment_map = {}
    for row in comment_rows:
        comment_map.setdefault(row["task_id"], []).append(_serialize_comment(row))
    event_map = {}
    for row in event_rows:
        event_map.setdefault(row["task_id"], []).append(_serialize_event(row))
    latest_map = {row["task_id"]: row for row in latest_rows if row["task_id"]}
    upload_map = {}
    for row in upload_rows:
        upload_map.setdefault(row["task_id"], []).append(_serialize_upload_job(row))
    tasks = []
    for row in task_rows:
        check_items = check_map.get(row["id"], [])
        artifacts = artifact_map.get(row["id"], [])
        gate = _upload_gate(row, check_items, artifacts, latest_map.get(row["id"]))
        upload_jobs = upload_map.get(row["id"], [])
        latest_upload_job = upload_jobs[0] if upload_jobs else None
        upload_request_pending = bool(
            latest_upload_job and latest_upload_job["status"] in {"REQUESTED", "UPLOADING"}
        )
        tasks.append(
            {
                "id": row["id"],
                "title": row["title"],
                "text": row["text"],
                "task_key": row["task_key"] or "",
                "status": row["status"],
                "status_label": TASK_STATUS_LABELS.get(row["status"], row["status"]),
                "target_env": row["target_env"] or "",
                "target_branch": row["target_branch"] or "",
                "progress_percent": int(row["progress_percent"] or 0),
                "current_step_code": row["current_step_code"] or "",
                "current_step_label": row["current_step_label"] or "",
                "summary": row["summary"] or "",
                "latest_upload_job_status": latest_upload_job["status"] if latest_upload_job else "",
                "created_by": row["created_by"],
                "updated_by": row["updated_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "check_sections": _task_sections(check_items),
                "artifacts": artifacts,
                "comments": comment_map.get(row["id"], []),
                "events": event_map.get(row["id"], []),
                "upload_jobs": upload_jobs,
                "upload_gate": gate,
                "actions": {
                    "can_proceed": str(row["status"] or "").strip().upper() in {"WAITING_APPROVAL", "HOLD", "FAILED", "UPLOAD_VERIFY_FAILED", "REVISION_REQUESTED"},
                    "can_execute_now": str(row["status"] or "").strip().upper() in {"WAITING_APPROVAL"},
                    "can_start_redebug": str(row["status"] or "").strip().upper() == "REVISION_REQUESTED",
                    "can_request_plan": str(row["status"] or "").strip().upper() in {"QUEUED"},
                    "can_finalize_plan": str(row["status"] or "").strip().upper() in {"PLANNING"},
                    "can_reflect_result": str(row["status"] or "").strip().upper() in {"RUNNING", "REDEBUG_RUNNING"},
                    "can_confirm_review": str(row["status"] or "").strip().upper() in {"WAITING_USER_CHECK"},
                    "can_prepare_upload": str(row["status"] or "").strip().upper() in {"WAITING_REVIEW"},
                    "can_claim_upload": str(row["status"] or "").strip().upper() == "UPLOAD_APPROVED" and str(latest_upload_job["status"] or "").strip().upper() == "REQUESTED",
                    "can_finish_upload": str(row["status"] or "").strip().upper() == "UPLOADING" and str(latest_upload_job["status"] or "").strip().upper() == "UPLOADING",
                    "can_finish_post_upload_verify": str(row["status"] or "").strip().upper() == "POST_UPLOAD_VERIFY",
                    "can_fail_post_upload_verify": str(row["status"] or "").strip().upper() == "POST_UPLOAD_VERIFY",
                    "can_retry": str(row["status"] or "").strip().upper() in {"FAILED", "UPLOAD_VERIFY_FAILED"},
                    "can_request_upload": gate["can_request_upload"] and not upload_request_pending,
                    "can_complete": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_hold": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_fail": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_discard": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_request_redebug": bool(checklist_summary["failed"] or checklist_summary["change_requested"] or str(row["status"] or "").strip().upper() == "UPLOAD_VERIFY_FAILED" or (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED")),
                },
            }
        )
    return tasks


def get_task(task_id):
    initialize_database()
    items = list_tasks(limit=200)
    for item in items:
        if item["id"] == task_id:
            return item
    return None


def get_state_bundle(limit=40):
    tasks = list_tasks(limit=limit)
    return {
        "tasks": tasks,
        "home_summary": _build_home_summary(tasks),
        "worker_status": _worker_status(),
        "runtime_info": _runtime_info(),
        "quick_links": QUICK_LINKS,
        "quick_actions": QUICK_ACTIONS,
        "artifact_links": _recent_file_links(),
        "checked_at": _now(),
    }


def create_task(text, created_by, task_key="", target_env="local", target_branch="mobile-control-v2"):
    initialize_database()
    text = (text or "").strip()
    if not text:
        raise ValueError("지시 내용을 입력해 주세요.")
    task_id = f"task-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mobile_tasks (
                id, title, text, task_key, status, target_env, target_branch, progress_percent,
                current_step_code, current_step_label, summary, created_by, updated_by,
                assigned_worker_id, current_run_id, lease_token, lease_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'QUEUED', ?, ?, 0, 'queued', '대기', '', ?, ?, '', '', '', '', ?, ?)
            """,
            (
                task_id,
                text.splitlines()[0][:80],
                text,
                task_key,
                target_env,
                target_branch,
                created_by,
                created_by,
                now,
                now,
            ),
        )
        _record_event(conn, task_id, "task_created", "user", created_by, {"task_key": task_key, "target_env": target_env})
    return get_task(task_id)


def _claim_upload_job_row(conn, row, worker_id):
    run_id = uuid.uuid4().hex
    result_summary = "업로드를 시작합니다."
    next_action = "서버 업로드를 진행 중입니다. 업로드가 끝나면 반영 검증 단계로 넘어갑니다."
    conn.execute(
        """
        UPDATE mobile_upload_jobs
        SET status = 'UPLOADING',
            result_summary = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (result_summary, _now(), row["id"]),
    )
    conn.execute(
        """
        UPDATE mobile_tasks
        SET status = 'UPLOADING',
            progress_percent = 5,
            current_step_code = 'uploading',
            current_step_label = '업로드 실행',
            next_action = ?,
            updated_at = ?,
            updated_by = ?,
            assigned_worker_id = ?,
            current_run_id = ?
        WHERE id = ?
        """,
        (next_action, _now(), worker_id, worker_id, run_id, row["task_id"]),
    )
    _append_task_message(conn, row["task_id"], "system", "status", "업로드 워커가 승인 요청을 인계받아 업로드를 시작했습니다.")
    _record_event(conn, row["task_id"], "upload_claimed", "worker", worker_id, {"upload_job_id": row["id"], "run_id": run_id})
    claimed_row = conn.execute("SELECT * FROM mobile_upload_jobs WHERE id = ?", (row["id"],)).fetchone()
    return {
        "id": claimed_row["id"],
        "task_id": claimed_row["task_id"],
        "status": claimed_row["status"],
        "target_env": claimed_row["target_env"],
        "approved_by": claimed_row["approved_by"],
        "result_summary": claimed_row["result_summary"],
        "created_at": claimed_row["created_at"],
        "updated_at": claimed_row["updated_at"],
        "run_id": run_id,
        "task_title": row["task_title"],
        "task_text": row["task_text"],
        "task_summary": row["task_summary"],
        "target_branch": row["target_branch"],
    }


def claim_next_upload_job(worker_id):
    initialize_database()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT j.*, t.title AS task_title, t.text AS task_text, t.summary AS task_summary, t.target_branch
            FROM mobile_upload_jobs j
            JOIN mobile_tasks t ON t.id = j.task_id
            WHERE j.status = 'REQUESTED'
            ORDER BY j.created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        item = _claim_upload_job_row(conn, row, worker_id)
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "UPLOADING",
        task_id=item["task_id"],
        run_id=item["run_id"],
        progress_percent=5,
        current_step_code="uploading",
        current_step_label="업로드 실행",
        summary="업로드 워커가 승인 요청을 인계받아 업로드를 시작했습니다.",
        task_status="UPLOADING",
    )
    return item


def claim_upload_job_for_task(task_id, worker_id):
    clean_task_id = str(task_id or "").strip()
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    initialize_database()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT j.*, t.title AS task_title, t.text AS task_text, t.summary AS task_summary, t.target_branch
            FROM mobile_upload_jobs j
            JOIN mobile_tasks t ON t.id = j.task_id
            WHERE j.task_id = ? AND j.status = 'REQUESTED'
            ORDER BY j.created_at ASC
            LIMIT 1
            """,
            (clean_task_id,),
        ).fetchone()
        if not row:
            conn.commit()
            raise ValueError("업로드 승인 요청이 등록된 작업만 업로드를 시작할 수 있습니다.")
        item = _claim_upload_job_row(conn, row, worker_id)
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "UPLOADING",
        task_id=item["task_id"],
        run_id=item["run_id"],
        progress_percent=5,
        current_step_code="uploading",
        current_step_label="업로드 실행",
        summary="업로드 워커가 승인 요청을 인계받아 업로드를 시작했습니다.",
        task_status="UPLOADING",
    )
    return item


def _next_check_item_order(conn, task_id):
    row = conn.execute("SELECT COALESCE(MAX(order_no), 0) AS max_order FROM mobile_check_items WHERE task_id = ?", (task_id,)).fetchone()
    return int((row["max_order"] if row else 0) or 0) + 1


def _create_derived_check_item(conn, task_id, actor, title, description, *, section="EXECUTION", parent_item_id="", related_files=None, test_required=False, user_confirmation_required=True, required=True, blocking=True):
    clean_title = str(title or "").strip()
    if not clean_title:
        return None
    now = _now()
    item_id = uuid.uuid4().hex
    order_no = _next_check_item_order(conn, task_id)
    conn.execute(
        """
        INSERT INTO mobile_check_items (
            id, task_id, section, title, description, required, blocking, status,
            evidence_type, evidence_ref, note, owner_role, updated_by, created_at, updated_at,
            parent_item_id, order_no, related_files_json, test_required, user_confirmation_required, discard_reason, result_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', '', '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')
        """,
        (
            item_id,
            task_id,
            section,
            clean_title[:120],
            str(description or "").strip(),
            1 if required else 0,
            1 if blocking else 0,
            "작업",
            actor,
            now,
            now,
            str(parent_item_id or ""),
            order_no,
            _json_dumps(related_files or []),
            1 if test_required else 0,
            1 if user_confirmation_required else 0,
        ),
    )
    _record_event(conn, task_id, "derived_check_item_created", "user", actor, {"check_item_id": item_id, "parent_item_id": parent_item_id, "title": clean_title})
    _append_task_message(conn, task_id, "system", "status", f"파생 체크리스트 추가. {clean_title[:80]}")
    return item_id


def ensure_task_checklist(task_id, actor="system"):
    initialize_database()
    with _connect() as conn:
        exists = conn.execute(
            "SELECT COUNT(*) AS count FROM mobile_check_items WHERE task_id = ?",
            (task_id,),
        ).fetchone()["count"]
        if exists:
            return
        now = _now()
        rows = [
            (
                uuid.uuid4().hex,
                task_id,
                code,
                title,
                description,
                required,
                blocking,
                "TODO",
                "",
                "",
                "",
                owner_role,
                actor,
                now,
                now,
            )
            for code, title, description, required, blocking, owner_role in CHECKLIST_SECTIONS
        ]
        conn.executemany(
            """
            INSERT INTO mobile_check_items (
                id, task_id, section, title, description, required, blocking, status,
                evidence_type, evidence_ref, note, owner_role, updated_by, created_at, updated_at,
                parent_item_id, order_no, related_files_json, test_required, user_confirmation_required, discard_reason, result_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, '[]', 0, 1, '', '')
            """,
            rows,
        )
        _record_event(conn, task_id, "checklist_issued", "system", actor, {"count": len(rows)})


def update_task_summary(task_id, actor, summary):
    initialize_database()
    with _connect() as conn:
        conn.execute(
            "UPDATE mobile_tasks SET summary = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            ((summary or "").strip(), _now(), actor, task_id),
        )
        _record_event(conn, task_id, "summary_saved", "user", actor, {})
        _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)


def update_task_self_review(task_id, actor, verification_summary):
    initialize_database()
    cleaned_summary = str(verification_summary or "").strip()
    if not cleaned_summary:
        raise ValueError("자체검수 요약을 입력해 주세요.")
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("task not found")
        review = _task_self_review(task_row)
        review["verification_summary"] = cleaned_summary
        conn.execute(
            "UPDATE mobile_tasks SET self_review_json = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (_json_dumps(review), _now(), actor, task_id),
        )
        _record_event(conn, task_id, "self_review_saved", "user", actor, {"verification_summary": cleaned_summary[:200]})
        gate = _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        current_status = str((current_row["status"] if current_row else task_row["status"]) or "").strip().upper()
        next_action = task_row["next_action"] or ""
        if current_status == "READY_TO_UPLOAD":
            next_action = "업로드 승인 가능 상태입니다. 서버 업로드 승인을 진행하세요."
        elif current_status == "WAITING_REVIEW":
            gate_reason = (gate.get("reasons") or ["업로드 전 마지막 확인을 진행하세요."])[0]
            next_action = f"업로드 준비 미완료 · {gate_reason}" if gate_reason else "업로드 전 마지막 확인을 진행하세요."
        elif current_status == "WAITING_USER_CHECK":
            next_action = "결과와 자체검수를 검토하고 체크리스트를 확인하세요."
        conn.execute(
            "UPDATE mobile_tasks SET next_action = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (next_action, _now(), actor, task_id),
        )
        _append_task_message(conn, task_id, "system", "status", "자체검수를 저장했습니다.")
    return get_task(task_id)


def update_task_changed_files(task_id, actor, changed_files):
    initialize_database()
    raw_items = changed_files or []
    if isinstance(raw_items, str):
        raw_items = raw_items.splitlines()
    normalized = []
    seen = set()
    for item in raw_items:
        value = str(item or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError("변경 파일 목록을 한 줄 이상 입력해 주세요.")
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("task not found")
        result_payload = _task_result_payload(task_row)
        result_payload["changed_files"] = normalized
        conn.execute(
            "UPDATE mobile_tasks SET result_payload_json = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (_json_dumps(result_payload), _now(), actor, task_id),
        )
        _record_event(conn, task_id, "changed_files_saved", "user", actor, {"count": len(normalized)})
        gate = _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        current_status = str((current_row["status"] if current_row else task_row["status"]) or "").strip().upper()
        next_action = task_row["next_action"] or ""
        if current_status == "READY_TO_UPLOAD":
            next_action = "업로드 승인 가능 상태입니다. 서버 업로드 승인을 진행하세요."
        elif current_status == "WAITING_REVIEW":
            gate_reason = (gate.get("reasons") or ["업로드 전 마지막 확인을 진행하세요."])[0]
            next_action = f"업로드 준비 미완료 · {gate_reason}" if gate_reason else "업로드 전 마지막 확인을 진행하세요."
        elif current_status == "WAITING_USER_CHECK":
            next_action = "결과와 자체검수를 검토하고 체크리스트를 확인하세요."
        conn.execute(
            "UPDATE mobile_tasks SET next_action = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (next_action, _now(), actor, task_id),
        )
        _append_task_message(conn, task_id, "system", "status", f"변경 파일 목록을 저장했습니다. ({len(normalized)}개)")
    return get_task(task_id)


def update_task_latest_artifact(task_id, actor, artifact_path):
    initialize_database()
    raw_path = str(artifact_path or "").strip().replace("\\", "/")
    if not raw_path:
        raise ValueError("최신 산출물 경로를 입력해 주세요.")
    normalized_relative = raw_path.lstrip("/").strip()
    resolved_path = (OUTPUT_DIR / normalized_relative).resolve()
    output_root = OUTPUT_DIR.resolve()
    if output_root not in resolved_path.parents and resolved_path != output_root:
        raise ValueError("output 폴더 기준 상대경로만 등록할 수 있습니다.")
    if not resolved_path.exists() or not resolved_path.is_file():
        raise ValueError("등록할 산출물 파일을 찾을 수 없습니다.")
    stored_path = resolved_path.relative_to(output_root).as_posix()
    artifact_label = resolved_path.name or "산출물"
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("task not found")
        register_artifact(task_id, artifact_label, stored_path, actor)
        _record_event(conn, task_id, "latest_artifact_registered", "user", actor, {"path": stored_path})
        gate = _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        current_status = str((current_row["status"] if current_row else task_row["status"]) or "").strip().upper()
        update_fields = {
            "updated_at": _now(),
            "updated_by": actor,
        }
        if current_status == "READY_TO_UPLOAD":
            update_fields["current_step_code"] = "ready_to_upload"
            update_fields["current_step_label"] = "업로드 준비"
            update_fields["next_action"] = "업로드 승인 가능 상태입니다. 서버 업로드 승인을 진행하세요."
        elif current_status == "WAITING_REVIEW":
            gate_reason = (gate.get("reasons") or ["업로드 전 마지막 확인을 진행하세요."])[0]
            update_fields["next_action"] = f"업로드 준비 미완료 · {gate_reason}" if gate_reason else "업로드 전 마지막 확인을 진행하세요."
        elif current_status == "WAITING_USER_CHECK":
            update_fields["next_action"] = "결과와 자체검수를 검토하고 체크리스트를 확인하세요."
        columns = ", ".join(f"{key} = ?" for key in update_fields.keys())
        conn.execute(
            f"UPDATE mobile_tasks SET {columns} WHERE id = ?",
            tuple(update_fields.values()) + (task_id,),
        )
        _append_task_message(conn, task_id, "system", "status", f"최신 산출물을 등록했습니다. ({stored_path})")
    return get_task(task_id)


def update_task_target_env(task_id, actor, target_env):
    initialize_database()
    normalized_env = str(target_env or "").strip().lower() or "local"
    if normalized_env not in {"local", "candidate", "production"}:
        raise ValueError("invalid target env")
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("task not found")
        previous_env = str(task_row["target_env"] or "").strip().lower() or "local"
        if previous_env == normalized_env:
            return get_task(task_id)
        conn.execute(
            "UPDATE mobile_tasks SET target_env = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (normalized_env, _now(), actor, task_id),
        )
        _record_event(conn, task_id, "target_env_updated", "user", actor, {"from": previous_env, "to": normalized_env})
        _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)


def add_comment(task_id, actor, body, kind="instruction", parent_check_item_id="", set_hold=True):
    initialize_database()
    body = (body or "").strip()
    if not body:
        raise ValueError("추가 지시 내용을 입력해 주세요.")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mobile_task_comments (
                id, task_id, parent_check_item_id, kind, body, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, task_id, parent_check_item_id, kind, body, actor, _now()),
        )
        if set_hold:
            if kind == "instruction":
                conn.execute(
                    """
                    UPDATE mobile_upload_jobs
                    SET status = 'CANCELED',
                        result_summary = CASE
                            WHEN result_summary IS NULL OR result_summary = '' THEN '추가 지시로 기존 업로드 요청이 취소되었습니다.'
                            ELSE result_summary || '\n\n[자동 취소] 추가 지시가 등록되어 업로드 요청을 취소했습니다.'
                        END,
                        updated_at = ?
                    WHERE task_id = ? AND status IN ('REQUESTED', 'UPLOADING')
                    """,
                    (_now(), task_id),
                )
                conn.execute(
                    """
                    UPDATE mobile_tasks
                    SET status = 'QUEUED',
                        progress_percent = 0,
                        current_step_code = 'queued',
                        current_step_label = '대기',
                        updated_at = ?,
                        updated_by = ?,
                        assigned_worker_id = '',
                        current_run_id = '',
                        lease_token = '',
                        lease_expires_at = ''
                    WHERE id = ? AND status NOT IN ('DISCARDED','CANCELED')
                    """,
                    (_now(), actor, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE mobile_tasks
                    SET status = 'HOLD', updated_at = ?, updated_by = ?
                    WHERE id = ? AND status NOT IN ('DONE','FAILED','DISCARDED','CANCELED')
                    """,
                    (_now(), actor, task_id),
                )
        _record_event(conn, task_id, "comment_added", "user", actor, {"kind": kind, "parent_check_item_id": parent_check_item_id})
        _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)


def update_task_action(task_id, actor, action, summary=""):
    initialize_database()
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("작업을 찾을 수 없습니다.")
        cleaned_summary = (summary or "").strip()
        if summary:
            conn.execute(
                "UPDATE mobile_tasks SET summary = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                (cleaned_summary, _now(), actor, task_id),
            )
        if action == "hold":
            next_status = "HOLD"
        elif action == "requeue":
            next_status = "QUEUED"
            next_step_code = "queued"
            next_step_label = "대기"
            next_action = "워커가 처음부터 다시 수행합니다."
            final_decision = ""
        elif action == "fail":
            next_status = "FAILED"
        elif action == "complete":
            next_status = "DONE"
        elif action == "discard":
            next_status = "DISCARDED"
        elif action == "request_upload":
            gate = _sync_ready_to_upload(conn, task_id)
            if not gate["can_request_upload"]:
                raise ValueError("서버 업로드 승인 조건이 아직 충족되지 않았습니다.")
            latest_upload_job = _latest_upload_job_row(conn, task_id)
            if latest_upload_job and latest_upload_job["status"] in {"REQUESTED", "UPLOADING"}:
                raise ValueError("이미 서버 업로드 승인이 접수되었습니다.")
            next_status = "READY_TO_UPLOAD"
            conn.execute(
                """
                INSERT INTO mobile_upload_jobs (
                    id, task_id, status, target_env, approved_by, result_summary, created_at, updated_at
                ) VALUES (?, ?, 'REQUESTED', ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    task_id,
                    task_row["target_env"] or "local",
                    actor,
                    cleaned_summary,
                    _now(),
                    _now(),
                ),
            )
        else:
            raise ValueError("허용되지 않은 작업 액션입니다.")
        conn.execute(
            "UPDATE mobile_tasks SET status = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (next_status, _now(), actor, task_id),
        )
        _record_event(conn, task_id, "task_action", "user", actor, {"action": action})
        if next_status in {"HOLD", "FAILED", "DISCARDED", "DONE"}:
            _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)


def update_check_item_action(check_item_id, actor, action, note=""):
    mapping = {
        "done": "DONE",
        "fail": "FAILED",
        "discard": "DISCARDED",
        "progress": "IN_PROGRESS",
        "block": "BLOCKED",
        "todo": "TODO",
    }
    if action not in mapping:
        raise ValueError("허용되지 않은 체크리스트 액션입니다.")
    initialize_database()
    with _connect() as conn:
        row = conn.execute(
            "SELECT task_id FROM mobile_check_items WHERE id = ?",
            (check_item_id,),
        ).fetchone()
        if not row:
            raise ValueError("체크리스트 항목을 찾을 수 없습니다.")
        conn.execute(
            """
            UPDATE mobile_check_items
            SET status = ?, note = ?, updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (mapping[action], (note or "").strip(), actor, _now(), check_item_id),
        )
        _record_event(conn, row["task_id"], "check_item_action", "user", actor, {"check_item_id": check_item_id, "action": action})
        _sync_ready_to_upload(conn, row["task_id"])
    return get_task(row["task_id"])


def _recover_expired_leases(conn):
    now = _now()
    expired_rows = conn.execute(
        f"""
        SELECT id FROM mobile_tasks
        WHERE status IN ({",".join("?" for _ in ACTIVE_TASK_STATUSES)})
          AND lease_expires_at != ''
          AND lease_expires_at < ?
        """,
        tuple(ACTIVE_TASK_STATUSES) + (now,),
    ).fetchall()
    for row in expired_rows:
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'HOLD',
                summary = CASE
                    WHEN summary IS NULL OR summary = '' THEN '워커 lease가 만료되어 보류로 전환되었습니다.'
                    ELSE summary || '\n\n[자동 보류] 워커 lease가 만료되었습니다.'
                END,
                updated_at = ?,
                updated_by = 'system',
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (now, row["id"]),
        )
        _record_event(conn, row["id"], "lease_expired", "system", "system", {})


def claim_next_task(worker_id, lease_seconds=90):
    initialize_database()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _recover_expired_leases(conn)
        row = conn.execute(
            "SELECT * FROM mobile_tasks WHERE status = 'QUEUED' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            conn.commit()
            return None
        run_id = uuid.uuid4().hex
        lease_token = uuid.uuid4().hex
        lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'CLAIMED',
                progress_percent = 0,
                current_step_code = 'claimed',
                current_step_label = '작업 할당',
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = ?,
                current_run_id = ?,
                lease_token = ?,
                lease_expires_at = ?
            WHERE id = ?
            """,
            (_now(), worker_id, worker_id, run_id, lease_token, lease_expires_at, row["id"]),
        )
        _record_event(conn, row["id"], "task_claimed", "worker", worker_id, {"run_id": run_id})
        claimed_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (row["id"],)).fetchone()
        conn.commit()
    return dict(claimed_row)


def finish_task_success(task_id, worker_id, run_id, summary, artifact_paths, plan_summary=None, result_payload=None, self_review=None, checklist_items=None, next_action="", final_decision=""):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        merged_plan = _task_plan_summary(task_row)
        if plan_summary:
            merged_plan.update(plan_summary)
        merged_result = _task_result_payload(task_row)
        if result_payload:
            merged_result.update(result_payload)
        merged_result["latest_summary"] = (summary or "").strip()
        merged_self_review = _task_self_review(task_row)
        if self_review:
            merged_self_review.update(self_review)
        if checklist_items:
            _replace_checklist_items_from_result(conn, task_id, checklist_items, worker_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'WAITING_USER_CHECK',
                progress_percent = 100,
                current_step_code = 'waiting_user_check',
                current_step_label = '사용자 검토 대기',
                summary = ?,
                plan_summary_json = ?,
                result_payload_json = ?,
                self_review_json = ?,
                next_action = ?,
                final_decision = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (
                (summary or "").strip(),
                _json_dumps(merged_plan),
                _json_dumps(merged_result),
                _json_dumps(merged_self_review),
                next_action or "결과와 자체검수를 검토하고 체크리스트를 확인하세요.",
                final_decision or "",
                _now(),
                worker_id,
                task_id,
            ),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "success"})
        _append_task_message(conn, task_id, "agent", "result", (summary or "작업이 완료되었습니다.").strip())
        _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        final_status = current_row["status"] if current_row else "WAITING_USER_CHECK"
        final_step_code = "ready_to_upload" if final_status == "READY_TO_UPLOAD" else "waiting_user_check"
        final_step_label = "업로드 승인 대기" if final_status == "READY_TO_UPLOAD" else "사용자 검토 대기"
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        final_status,
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code=final_step_code,
        current_step_label=final_step_label,
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status=final_status,
    )
    return get_task(task_id)


def finish_task_failure(task_id, worker_id, run_id, summary, artifact_paths=None, plan_summary=None, result_payload=None, self_review=None, checklist_items=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        merged_plan = _task_plan_summary(task_row)
        if plan_summary:
            merged_plan.update(plan_summary)
        merged_result = _task_result_payload(task_row)
        if result_payload:
            merged_result.update(result_payload)
        merged_result["latest_summary"] = (summary or "").strip()
        merged_self_review = _task_self_review(task_row)
        if self_review:
            merged_self_review.update(self_review)
        if checklist_items:
            _replace_checklist_items_from_result(conn, task_id, checklist_items, worker_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'FAILED',
                current_step_code = 'failed',
                current_step_label = '실패',
                summary = ?,
                plan_summary_json = ?,
                result_payload_json = ?,
                self_review_json = ?,
                next_action = '실패 사유를 확인하고 재디버그 요청 여부를 결정하세요.',
                final_decision = 'FAILED_BY_WORKER',
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (
                (summary or "").strip(),
                _json_dumps(merged_plan),
                _json_dumps(merged_result),
                _json_dumps(merged_self_review),
                _now(),
                worker_id,
                task_id,
            ),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "failed"})
        _append_task_message(conn, task_id, "agent", "error", (summary or "작업이 실패했습니다.").strip())
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "FAILED",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="failed",
        current_step_label="실패",
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status="FAILED",
    )
    return get_task(task_id)

def _upload_gate(task_row, check_items, artifacts, latest_heartbeat):
    reasons = []
    self_review = _task_self_review(task_row)
    output_artifacts = _output_artifacts_only(artifacts)
    required_pending = [item for item in check_items if item["required"] and item["status"] not in {"DONE", "DISCARDED"}]
    blocking_fail = [item for item in check_items if item["blocking"] and item["status"] in {"FAILED", "BLOCKED"}]
    change_requested = [item for item in check_items if item["status"] == "CHANGE_REQUESTED"]
    if required_pending:
        reasons.append("필수 체크리스트가 아직 남아 있습니다.")
    if blocking_fail:
        reasons.append("차단 항목에 실패가 있습니다.")
    if change_requested:
        reasons.append("변경요청 항목이 남아 있습니다.")
    if not output_artifacts:
        reasons.append("최신 산출물이 없습니다.")
    if not (self_review.get("verification_summary") or self_review.get("affected_files")):
        reasons.append("최신 자체검수 결과가 없습니다.")
    target_env = (task_row["target_env"] or "").strip().lower()
    if not target_env or target_env == "local":
        reasons.append("업로드 대상이 후보/운영으로 지정되지 않았습니다.")
    if not latest_heartbeat:
        reasons.append("최근 워커 실행 기록이 없습니다.")
    else:
        heartbeat_time = _parse_time(latest_heartbeat["created_at"])
        if not heartbeat_time or datetime.now() - heartbeat_time > timedelta(hours=HEARTBEAT_STALE_WINDOW_HOURS):
            reasons.append("최근 워커 실행 기록이 오래되었습니다.")
        if latest_heartbeat["state"] == "FAILED":
            reasons.append("최근 워커 실행이 실패했습니다.")
    can_request_upload = (not reasons) and task_row["status"] in {
        "WAITING_USER_CHECK",
        "WAITING_REVIEW",
        "READY_TO_UPLOAD",
        "HOLD",
        "POST_UPLOAD_VERIFY",
    }
    return {"can_request_upload": can_request_upload, "reasons": reasons}


def _sync_ready_to_upload(conn, task_id):
    task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task_row:
        return {"can_request_upload": False, "reasons": ["작업을 찾을 수 없습니다."]}
    check_rows = conn.execute("SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
    artifact_rows = conn.execute("SELECT * FROM mobile_artifacts WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
    latest_heartbeat = conn.execute(
        "SELECT * FROM mobile_worker_heartbeats WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    gate = _upload_gate(
        task_row,
        [_serialize_check_item(row) for row in check_rows],
        [_serialize_artifact(row) for row in artifact_rows],
        latest_heartbeat,
    )
    if gate["can_request_upload"] and task_row["status"] in {"WAITING_USER_CHECK", "WAITING_REVIEW", "HOLD", "SELF_REVIEW"}:
        conn.execute(
            "UPDATE mobile_tasks SET status = 'READY_TO_UPLOAD', updated_at = ?, updated_by = 'system' WHERE id = ?",
            (_now(), task_id),
        )
    elif (not gate["can_request_upload"]) and task_row["status"] == "READY_TO_UPLOAD":
        conn.execute(
            "UPDATE mobile_tasks SET status = 'WAITING_USER_CHECK', updated_at = ?, updated_by = 'system' WHERE id = ?",
            (_now(), task_id),
        )
    return gate


def record_worker_heartbeat(
    worker_id,
    state,
    task_id="",
    run_id="",
    progress_percent=0,
    current_step_code="",
    current_step_label="",
    summary="",
    latest_artifact_ids=None,
    lease_seconds=90,
    task_status=None,
):
    initialize_database()
    latest_artifact_ids = latest_artifact_ids or []
    heartbeat_time = _now()
    lease_expires_at = ""
    if task_id:
        lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mobile_worker_heartbeats (
                id, worker_id, task_id, run_id, state, progress_percent,
                current_step_code, current_step_label, summary, latest_artifact_ids_json,
                lease_expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                worker_id,
                task_id or "",
                run_id or "",
                state,
                int(progress_percent or 0),
                current_step_code or "",
                current_step_label or "",
                summary or "",
                json.dumps(latest_artifact_ids, ensure_ascii=False),
                lease_expires_at,
                heartbeat_time,
            ),
        )
        if task_id:
            updates = {
                "updated_at": heartbeat_time,
                "updated_by": worker_id,
                "progress_percent": int(progress_percent or 0),
                "current_step_code": current_step_code or "",
                "current_step_label": current_step_label or "",
                "lease_expires_at": lease_expires_at,
                "assigned_worker_id": worker_id,
                "current_run_id": run_id or "",
            }
            if task_status:
                updates["status"] = task_status
            columns = ", ".join(f"{key} = ?" for key in updates.keys())
            conn.execute(
                f"UPDATE mobile_tasks SET {columns} WHERE id = ?",
                tuple(updates.values()) + (task_id,),
            )


def register_artifact(task_id, label, path, created_by, kind="artifact"):
    initialize_database()
    artifact_path = str(path or "").strip()
    if not artifact_path:
        return None
    with _connect() as conn:
        artifact_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO mobile_artifacts (id, task_id, kind, label, path, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (artifact_id, task_id, kind, label, artifact_path, created_by, _now()),
        )
    return artifact_id


def finish_task_success(task_id, worker_id, run_id, summary, artifact_paths):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    final_status = "WAITING_REVIEW"
    final_step_code = "waiting_review"
    final_step_label = "검토 대기"
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'WAITING_REVIEW',
                progress_percent = 100,
                current_step_code = 'waiting_review',
                current_step_label = '검토 대기',
                summary = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            ((summary or "").strip(), _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "success"})
        _append_task_message(conn, task_id, "agent", "result", (summary or "작업이 완료되었습니다.").strip())
        _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if current_row and current_row["status"] == "READY_TO_UPLOAD":
            final_status = "READY_TO_UPLOAD"
            final_step_code = "ready_to_upload"
            final_step_label = "업로드 준비"
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        final_status,
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code=final_step_code,
        current_step_label=final_step_label,
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status=final_status,
    )
    return get_task(task_id)


def finish_task_failure(task_id, worker_id, run_id, summary, artifact_paths=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'FAILED',
                current_step_code = 'failed',
                current_step_label = '실패',
                summary = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            ((summary or "").strip(), _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "failed"})
        _append_task_message(conn, task_id, "agent", "error", (summary or "작업이 실패했습니다.").strip())
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "FAILED",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="failed",
        current_step_label="실패",
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status="FAILED",
    )
    return get_task(task_id)


def finish_upload_job_success(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    clean_summary = (summary or "").strip()
    if not clean_summary:
        clean_summary = "업로드가 완료되어 반영 검증 단계로 넘어갑니다."
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id, kind="upload")
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_upload_jobs
            SET status = 'DONE',
                result_summary = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (clean_summary, _now(), upload_job_id),
        )
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'POST_UPLOAD_VERIFY',
                progress_percent = 100,
                current_step_code = 'post_upload_verify',
                current_step_label = '업로드 후 검증',
                next_action = '서버 반영은 끝났습니다. 업로드 후 검증을 진행하세요.',
                summary = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (clean_summary, _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "upload_finished", "worker", worker_id, {"upload_job_id": upload_job_id, "run_id": run_id, "result": "success"})
        _append_task_message(conn, task_id, "system", "status", "업로드가 완료되어 반영 검증 단계로 넘어갑니다.")
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "POST_UPLOAD_VERIFY",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="post_upload_verify",
        current_step_label="업로드 후 검증",
        summary=clean_summary[:300],
        latest_artifact_ids=artifact_ids,
        task_status="POST_UPLOAD_VERIFY",
    )
    return get_task(task_id)


def finish_upload_for_task(task_id, actor, summary="", artifact_paths=None):
    clean_task_id = str(task_id or "").strip()
    clean_actor = str(actor or "").strip() or "worker"
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    initialize_database()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT j.*, t.current_run_id
            FROM mobile_upload_jobs j
            JOIN mobile_tasks t ON t.id = j.task_id
            WHERE j.task_id = ? AND j.status = 'UPLOADING'
            ORDER BY j.updated_at DESC, j.created_at DESC
            LIMIT 1
            """,
            (clean_task_id,),
        ).fetchone()
    if not row:
        raise ValueError("업로드 실행 중인 작업만 업로드 완료 처리할 수 있습니다.")
    run_id = str(row["current_run_id"] or "").strip() or uuid.uuid4().hex
    worker_id = f"{clean_actor}-upload-worker"
    return finish_upload_job_success(
        row["id"],
        clean_task_id,
        worker_id,
        run_id,
        summary,
        artifact_paths=artifact_paths or [],
    )


def finish_upload_job_failure(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id, kind="upload")
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_upload_jobs
            SET status = 'FAILED',
                result_summary = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ((summary or "").strip(), _now(), upload_job_id),
        )
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'HOLD',
                current_step_code = 'upload_failed',
                current_step_label = '업로드 실패',
                next_action = '',
                summary = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            ((summary or "").strip(), _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "upload_finished", "worker", worker_id, {"upload_job_id": upload_job_id, "run_id": run_id, "result": "failed"})
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "HOLD",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="upload_failed",
        current_step_label="업로드 실패",
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status="HOLD",
    )
    return get_task(task_id)


def finish_post_upload_verify_success(task_id, worker_id, run_id, summary, artifact_paths=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    clean_summary = (summary or "").strip()
    if not clean_summary:
        clean_summary = "업로드 후 검증이 완료되어 작업을 최종 완료했습니다."
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id, kind="verify")
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'DONE',
                progress_percent = 100,
                current_step_code = 'done',
                current_step_label = '최종 완료',
                summary = ?,
                next_action = '모든 검증이 완료되었습니다.',
                final_decision = CASE
                    WHEN final_decision IS NULL OR final_decision = '' THEN 'DONE_AFTER_UPLOAD_VERIFY'
                    ELSE final_decision
                END,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (clean_summary, _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "upload_verified", "worker", worker_id, {"run_id": run_id, "result": "success"})
        _record_event(conn, task_id, "task_completed", "worker", worker_id, {"run_id": run_id, "result": "upload_verified"})
        _append_task_message(conn, task_id, "system", "status", "업로드 후 검증이 완료되어 작업을 최종 완료했습니다.")
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "DONE",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="done",
        current_step_label="최종 완료",
        summary=clean_summary[:300],
        latest_artifact_ids=artifact_ids,
        task_status="DONE",
    )
    return get_task(task_id)


def finish_post_upload_verify_for_task(task_id, actor, summary="", artifact_paths=None):
    clean_task_id = str(task_id or "").strip()
    clean_actor = str(actor or "").strip() or "worker"
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    initialize_database()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT current_run_id, status
            FROM mobile_tasks
            WHERE id = ?
            """,
            (clean_task_id,),
        ).fetchone()
    if not row or str(row["status"] or "").strip().upper() != "POST_UPLOAD_VERIFY":
        raise ValueError("업로드 후 검증 상태의 작업만 최종 검증 완료 처리할 수 있습니다.")
    run_id = str(row["current_run_id"] or "").strip() or uuid.uuid4().hex
    worker_id = f"{clean_actor}-verify-worker"
    return finish_post_upload_verify_success(
        clean_task_id,
        worker_id,
        run_id,
        summary,
        artifact_paths=artifact_paths or [],
    )


def finish_post_upload_verify_failure(task_id, worker_id, run_id, summary, artifact_paths=None, rollback_required=False):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    clean_summary = (summary or "").strip()
    if not clean_summary:
        clean_summary = "업로드 후 검증에서 문제가 확인되었습니다."
    next_action = "롤백 필요 여부를 검토해 주세요." if rollback_required else "실패 사유를 확인하고 재디버그 또는 재검증을 진행해 주세요."
    final_decision = "ROLLBACK_REVIEW_NEEDED" if rollback_required else ""
    with _connect() as conn:
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id, kind="verify")
            if artifact_id:
                artifact_ids.append(artifact_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'UPLOAD_VERIFY_FAILED',
                progress_percent = 100,
                current_step_code = 'upload_verify_failed',
                current_step_label = '반영 검증 실패',
                summary = ?,
                next_action = ?,
                final_decision = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (clean_summary, next_action, final_decision, _now(), worker_id, task_id),
        )
        _record_event(conn, task_id, "upload_verify_failed", "worker", worker_id, {"run_id": run_id, "rollback_required": bool(rollback_required)})
        _append_task_message(conn, task_id, "system", "error", clean_summary)
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "UPLOAD_VERIFY_FAILED",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="upload_verify_failed",
        current_step_label="반영 검증 실패",
        summary=clean_summary[:300],
        latest_artifact_ids=artifact_ids,
        task_status="UPLOAD_VERIFY_FAILED",
    )
    return get_task(task_id)


def finish_post_upload_verify_failure_for_task(task_id, actor, summary="", artifact_paths=None, rollback_required=False):
    clean_task_id = str(task_id or "").strip()
    clean_actor = str(actor or "").strip() or "worker"
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    initialize_database()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT current_run_id, status
            FROM mobile_tasks
            WHERE id = ?
            """,
            (clean_task_id,),
        ).fetchone()
    if not row or str(row["status"] or "").strip().upper() != "POST_UPLOAD_VERIFY":
        raise ValueError("업로드 후 검증 상태의 작업만 검증 실패 처리할 수 있습니다.")
    run_id = str(row["current_run_id"] or "").strip() or uuid.uuid4().hex
    worker_id = f"{clean_actor}-verify-worker"
    return finish_post_upload_verify_failure(
        clean_task_id,
        worker_id,
        run_id,
        summary,
        artifact_paths=artifact_paths or [],
        rollback_required=bool(rollback_required),
    )


def _priority_rank(priority):
    return {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}.get(str(priority or "").upper(), 2)


def map_user_status(task_status):
    status = str(task_status or "").strip().upper()
    if status == "WAITING_APPROVAL":
        return "승인 대기"
    if status in {"QUEUED", "CLAIMED", "PLANNING"}:
        return "대기중"
    if status in {"RUNNING", "REDEBUG_RUNNING"}:
        return "작업중"
    if status in {"SELF_REVIEW", "WAITING_USER_CHECK", "WAITING_REVIEW", "REVISION_REQUESTED"}:
        return "검수중"
    if status in {"READY_TO_UPLOAD", "UPLOAD_APPROVED"}:
        return "업로드 준비"
    if status in {"UPLOADING", "UPLOAD_REQUESTED"}:
        return "업로드 중"
    if status in {"POST_UPLOAD_VERIFY", "UPLOAD_VERIFIED"}:
        return "반영 확인중"
    if status == "DONE":
        return "완료"
    return "실패/보류"


def summarize_checklist(check_items):
    summary = _build_checklist_summary(check_items)
    required_pending = [item for item in check_items if item["required"] and item["status"] not in {"DONE", "DISCARDED"}]
    open_items = [item for item in check_items if item["status"] not in {"DONE", "DISCARDED"}]
    blocking_items = [item for item in check_items if item["blocking"] and item["status"] in {"FAILED", "BLOCKED"}]
    summary["required_pending"] = len(required_pending)
    summary["open_items"] = len(open_items)
    summary["blocking_failed_items"] = len(blocking_items)
    summary["all_required_done"] = not required_pending
    summary["all_items_resolved"] = not open_items
    summary["has_blocking_failure"] = bool(blocking_items)
    return summary


def compute_upload_gate(task_row, check_items, artifacts, latest_heartbeat):
    checklist_summary = summarize_checklist(check_items)
    self_review = _task_self_review(task_row)
    result_payload = _task_result_payload(task_row)
    output_artifacts = _output_artifacts_only(artifacts)
    changed_files = result_payload.get("changed_files") or self_review.get("affected_files") or []
    target_env = (task_row["target_env"] or "").strip().lower()
    permission_confirmed = str(task_row["created_by"] or "").strip() == "bibaram1"
    self_review_ready = bool(self_review.get("verification_summary") or self_review.get("affected_files"))
    reasons = []
    if checklist_summary["open_items"]:
        reasons.append("완료되지 않은 체크리스트 항목이 남아 있습니다.")
    if checklist_summary["failed"]:
        reasons.append("실패한 체크리스트 항목이 있습니다.")
    if checklist_summary.get("blocked"):
        reasons.append("차단된 체크리스트 항목이 있습니다.")
    if checklist_summary["change_requested"]:
        reasons.append("변경요청 항목이 남아 있습니다.")
    if not self_review_ready:
        reasons.append("자체검수가 완료되지 않았습니다.")
    if not output_artifacts:
        reasons.append("최신 산출물이 없습니다.")
    if not permission_confirmed:
        reasons.append("권한 확인이 필요합니다.")
    if not target_env or target_env == "local":
        reasons.append("업로드 대상환경이 지정되지 않았습니다.")
    if not changed_files:
        reasons.append("변경 파일 목록이 없습니다.")
    if not latest_heartbeat:
        reasons.append("최근 작업 실행 기록이 없습니다.")
    else:
        heartbeat_time = _parse_time(latest_heartbeat["created_at"])
        if not heartbeat_time or datetime.now() - heartbeat_time > timedelta(hours=HEARTBEAT_STALE_WINDOW_HOURS):
            reasons.append("최근 작업 실행 기록이 오래되었습니다.")
        if latest_heartbeat["state"] == "FAILED":
            reasons.append("최근 작업 실행이 실패했습니다.")
    can_request_upload = (not reasons) and str(task_row["status"] or "").strip().upper() in {
        "WAITING_USER_CHECK",
        "WAITING_REVIEW",
        "READY_TO_UPLOAD",
        "HOLD",
    }
    return {
        "allowed": can_request_upload,
        "can_request_upload": can_request_upload,
        "reasons": reasons,
        "reason_text": "\n".join(reasons),
        "required_ready": checklist_summary["required_pending"] == 0,
        "all_items_resolved": checklist_summary["open_items"] == 0,
        "self_review_ready": self_review_ready,
        "artifact_ready": bool(output_artifacts),
        "permission_confirmed": permission_confirmed,
        "target_env_ready": bool(target_env and target_env != "local"),
        "changed_files_ready": bool(changed_files),
        "artifact_count": len(output_artifacts),
        "changed_files_count": len(changed_files),
    }


def compute_decision_summary(task_row, checklist_summary, upload_gate):
    status = str(task_row["status"] or "").strip().upper()
    if status == "DONE":
        return "최종 완료 처리된 작업입니다."
    if status in {"UPLOAD_APPROVED", "UPLOADING"}:
        return "업로드 승인 이후 서버 반영 단계가 진행 중입니다."
    if status == "POST_UPLOAD_VERIFY":
        return "업로드는 끝났고 반영 확인이 남아 있습니다."
    if upload_gate.get("allowed"):
        return "필수 검수가 끝나 업로드 승인 가능한 상태입니다."
    if checklist_summary.get("change_requested"):
        return "변경요청이 남아 있어 후속 반영 여부를 결정해야 합니다."
    if checklist_summary.get("failed"):
        return "실패 항목이 남아 있어 재디버그 여부를 결정해야 합니다."
    if status == "WAITING_APPROVAL":
        return "체크리스트와 실행 계획을 확인한 뒤 진행 여부를 결정해야 합니다."
    if status in {"SELF_REVIEW", "WAITING_USER_CHECK", "WAITING_REVIEW"}:
        return "체크리스트와 자체검수 결과를 검토해야 합니다."
    if status in {"RUNNING", "REDEBUG_RUNNING"}:
        return "워커가 작업을 진행 중입니다."
    if status in {"FAILED", "HOLD", "DISCARDED"}:
        return "보류 또는 실패 상태로 추가 판단이 필요합니다."
    return "현재 상태를 확인하고 다음 액션을 진행하세요."


def compute_risk_summary(task_row, checklist_summary, upload_gate):
    risks = []
    if checklist_summary.get("failed"):
        risks.append("실패 체크리스트가 남아 있습니다.")
    if checklist_summary.get("change_requested"):
        risks.append("변경요청이 해소되지 않았습니다.")
    if upload_gate.get("reasons"):
        risks.extend(upload_gate["reasons"][:2])
    if str(task_row["status"] or "").strip().upper() == "HOLD":
        risks.append("보류 상태입니다.")
    unique_risks = []
    for item in risks:
        if item and item not in unique_risks:
            unique_risks.append(item)
    return " / ".join(unique_risks[:2]) if unique_risks else "현재 치명적 차단 리스크는 보이지 않습니다."


def compute_next_action(task_row, upload_gate, checklist_summary):
    current = str(task_row["next_action"] or "").strip()
    status = str(task_row["status"] or "").strip().upper()
    current_step_code = str(task_row["current_step_code"] or "").strip().lower()
    if current and current_step_code != "upload_failed" and status != "UPLOAD_VERIFY_FAILED":
        return current
    return _derive_next_action(status, upload_gate, checklist_summary)


def append_event(conn, task_id, event_type, actor_type, actor_id, payload=None):
    _record_event(conn, task_id, event_type, actor_type, actor_id, payload)


def run_pre_upload_verify(task_row, check_items, artifacts, latest_heartbeat):
    upload_gate = compute_upload_gate(task_row, check_items, artifacts, latest_heartbeat)
    output_artifacts = _output_artifacts_only(artifacts)
    result_payload = _task_result_payload(task_row)
    self_review = _task_self_review(task_row)
    changed_files = result_payload.get("changed_files") or self_review.get("affected_files") or []
    upload_script_path = BASE_DIR / "scripts" / "upload_changed_files.ps1"
    runtime_probe_path = BASE_DIR / "mobile_control_local" / "get_mobile_runtime_status.ps1"

    checks = [
        {
            "key": "gate",
            "label": "업로드 게이트",
            "ok": bool(upload_gate.get("allowed")),
            "detail": "업로드 게이트 조건 충족" if upload_gate.get("allowed") else (upload_gate.get("reasons") or ["업로드 게이트 조건 미충족"])[0],
        },
        {
            "key": "target_env",
            "label": "대상 환경",
            "ok": bool(upload_gate.get("target_env_ready")),
            "detail": "대상 환경 확인" if upload_gate.get("target_env_ready") else "대상 환경이 지정되지 않았습니다.",
        },
        {
            "key": "changed_files",
            "label": "변경 파일",
            "ok": bool(changed_files),
            "detail": f"변경 파일 {len(changed_files)}개 확인" if changed_files else "변경 파일 목록이 없습니다.",
        },
        {
            "key": "artifacts",
            "label": "산출물",
            "ok": bool(output_artifacts),
            "detail": f"산출물 {len(output_artifacts)}개 확인" if output_artifacts else "최신 산출물이 없습니다.",
        },
        {
            "key": "upload_script",
            "label": "업로드 스크립트",
            "ok": upload_script_path.exists(),
            "detail": "업로드 스크립트 준비됨" if upload_script_path.exists() else "upload_changed_files.ps1 파일이 없습니다.",
        },
        {
            "key": "runtime_probe",
            "label": "런타임 확인 스크립트",
            "ok": runtime_probe_path.exists(),
            "detail": "런타임 확인 스크립트 준비됨" if runtime_probe_path.exists() else "get_mobile_runtime_status.ps1 파일이 없습니다.",
        },
    ]
    passed = all(item["ok"] for item in checks)
    reasons = [item["detail"] for item in checks if not item["ok"]]
    return {
        "passed": passed,
        "ok": passed,
        "items": checks,
        "reasons": reasons,
        "reason_text": "\n".join(reasons),
        "summary": "사전 업로드 검증 통과" if passed else "사전 업로드 검증 실패",
    }


def _build_warning_badges(task_row, checklist_summary, upload_gate, latest_upload_job=None):
    badges = []
    if checklist_summary.get("failed"):
        badges.append("실패")
    if checklist_summary.get("change_requested"):
        badges.append("변경요청")
    task_status = str(task_row["status"] or "").strip().upper()
    latest_upload_status = str((latest_upload_job or {}).get("status") or "").strip().upper()
    if task_status == "UPLOAD_VERIFY_FAILED":
        badges.append("반영 검증 실패")
    elif latest_upload_status == "FAILED":
        badges.append("보류")
    elif task_status == "HOLD":
        badges.append("보류")
    if (not upload_gate.get("allowed")) and upload_gate.get("reasons"):
        badges.append("업로드 불가")
    return badges[:3]


def _build_home_summary(tasks):
    waiting_review = 0
    failed_or_revision = 0
    upload_ready = 0
    upload_verify_failed = 0
    for task in tasks:
        status = str(task.get("status") or "").upper()
        checklist_summary = task.get("checklist_summary") or {}
        latest_upload_job_status = str(task.get("latest_upload_job_status") or "").upper()
        if status in {"SELF_REVIEW", "WAITING_USER_CHECK", "WAITING_REVIEW"}:
            waiting_review += 1
        if checklist_summary.get("failed") or checklist_summary.get("change_requested") or status in {"FAILED", "REVISION_REQUESTED", "HOLD"}:
            failed_or_revision += 1
        if task.get("actions", {}).get("can_request_upload"):
            upload_ready += 1
        if status == "UPLOAD_VERIFY_FAILED":
            upload_verify_failed += 1
    return [
        {"key": "waiting_review", "label": "검수 대기", "count": waiting_review, "hint": "체크리스트 확인 필요"},
        {"key": "failed_or_revision", "label": "실패/변경요청", "count": failed_or_revision, "hint": "재디버그 또는 후속 요청 필요"},
        {"key": "upload_ready", "label": "업로드 가능", "count": upload_ready, "hint": "업로드 승인 가능"},
        {"key": "upload_verify_failed", "label": "반영 검증 실패", "count": upload_verify_failed, "hint": "업로드 후 재확인 필요"},
    ]


# Live runtime block: 이후 _upload_gate 패치는 앞쪽 중복 정의가 아니라 여기 최종 위임 지점을 기준으로 수정한다.
def _upload_gate(task_row, check_items, artifacts, latest_heartbeat):
    return compute_upload_gate(task_row, check_items, artifacts, latest_heartbeat)


def _derive_next_action(task_status, gate, checklist_summary):
    if checklist_summary["change_requested"] or checklist_summary["failed"]:
        return "변경요청/실패 코멘트를 확인하고 재디버그 요청을 실행하세요."
    if task_status == "WAITING_APPROVAL":
        return "체크리스트를 확인한 뒤 진행을 눌러 실행하세요."
    if task_status in {"FAILED", "HOLD", "UPLOAD_VERIFY_FAILED"}:
        return "실패 사유를 확인하고 재시도 여부를 결정하세요."
    if gate.get("can_request_upload"):
        return "체크리스트가 모두 완료되었습니다. 필요 시 서버 업로드 승인을 진행하세요."
    if task_status in {"WAITING_USER_CHECK", "WAITING_REVIEW", "POST_UPLOAD_VERIFY"}:
        return "결과와 자체검수를 검토하고 체크리스트를 확인하세요."
    if task_status == "DONE":
        return "모든 검수가 완료되었습니다."
    return "진행 상태를 확인하세요."


def _replace_checklist_items_from_result(conn, task_id, checklist_items, actor):
    if not checklist_items:
        return
    rows = conn.execute(
        "SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    ).fetchall()
    if not rows:
        section_meta = {
            code: {
                "title": title,
                "description": description,
                "required": required,
                "blocking": blocking,
                "owner_role": owner_role,
            }
            for code, title, description, required, blocking, owner_role in CHECKLIST_SECTIONS
        }
        now = _now()
        insert_rows = []
        for order_no, item in enumerate(checklist_items, start=1):
            section = str(item.get("section") or "").strip().upper() or "PLAN"
            meta = section_meta.get(section) or section_meta["PLAN"]
            status = str(item.get("status") or "").strip().upper()
            if status not in CHECK_STATUS_LABELS:
                status = "PENDING"
            insert_rows.append(
                (
                    uuid.uuid4().hex,
                    task_id,
                    section,
                    str(item.get("title") or meta["title"]).strip() or meta["title"],
                    str(item.get("description") or meta["description"] or "").strip(),
                    int(meta["required"]),
                    int(meta["blocking"]),
                    status,
                    "",
                    "",
                    str(item.get("note") or "").strip(),
                    meta["owner_role"],
                    actor,
                    now,
                    now,
                    "",
                    order_no,
                    _json_dumps(item.get("related_files") or []),
                    int(bool(item.get("test_required"))),
                    int(bool(item.get("user_confirmation_required", True))),
                    "",
                    str(item.get("result_summary") or "").strip(),
                )
            )
        if insert_rows:
            conn.executemany(
                """
                INSERT INTO mobile_check_items (
                    id, task_id, section, title, description, required, blocking, status,
                    evidence_type, evidence_ref, note, owner_role, updated_by, created_at, updated_at,
                    parent_item_id, order_no, related_files_json, test_required, user_confirmation_required, discard_reason, result_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
            _record_event(conn, task_id, "checklist_issued", "system", actor, {"count": len(insert_rows), "source": "planning_result"})
        rows = conn.execute(
            "SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC, order_no ASC",
            (task_id,),
        ).fetchall()
    if not rows:
        return
    by_section = {str(item.get("section") or "").strip().upper(): item for item in checklist_items if item.get("section")}
    sequential = list(checklist_items)
    for index, row in enumerate(rows):
        structured = by_section.get(row["section"]) or (sequential[index] if index < len(sequential) else None)
        if not structured:
            continue
        next_title = str(structured.get("title") or row["title"]).strip() or row["title"]
        next_description = str(structured.get("description") or row["description"] or "").strip()
        next_note = str(structured.get("note") or row["note"] or "").strip()
        next_status = str(structured.get("status") or "").strip().upper()
        if next_status not in CHECK_STATUS_LABELS:
            next_status = "PENDING"
        conn.execute(
            """
            UPDATE mobile_check_items
            SET title = ?, description = ?, note = ?, status = ?, updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_title, next_description, next_note, next_status, actor, _now(), row["id"]),
        )


def _reset_check_items_for_revision(conn, task_id, actor):
    conn.execute(
        """
        UPDATE mobile_check_items
        SET status = CASE
                WHEN status IN ('DONE', 'DISCARDED') THEN status
                ELSE 'PENDING'
            END,
            updated_by = ?,
            updated_at = ?
        WHERE task_id = ?
        """,
        (actor, _now(), task_id),
    )

# Live runtime block: create_task 패치는 앞쪽 중복 정의가 아니라 여기서만 진행한다.
def create_task(text, created_by, task_key="", target_env="local", target_branch="mobile-control-v2", task_type="", priority="NORMAL", attachments=None, model_profile="mobile_worker", model_name="", reasoning_effort=""):
    initialize_database()
    text = (text or "").strip()
    if not text:
        raise ValueError("지시 내용을 입력해 주세요.")
    normalized_type = _normalize_task_type(task_type, task_key)
    normalized_priority = _normalize_priority(priority)
    normalized_model_profile = _normalize_model_profile(model_profile)
    normalized_model_name = _normalize_model_name(model_name)
    normalized_reasoning_effort = _normalize_reasoning_effort(reasoning_effort)
    normalized_attachments = _normalize_task_attachments(attachments)
    task_id = f"task-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mobile_tasks (
                id, title, text, task_key, model_profile, status, target_env, target_branch, progress_percent,
                current_step_code, current_step_label, summary, created_by, updated_by,
                assigned_worker_id, current_run_id, lease_token, lease_expires_at, created_at, updated_at,
                task_type, priority, plan_summary_json, result_payload_json, self_review_json,
                next_action, followup_bundle_json, final_decision, model_name, reasoning_effort
            ) VALUES (
                ?, ?, ?, ?, ?, 'WAITING_APPROVAL', ?, ?, 0, 'waiting_approval', '실행 승인 대기', '', ?, ?, '', '', '', '', ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                task_id,
                text.splitlines()[0][:80],
                text,
                task_key,
                normalized_model_profile,
                target_env,
                target_branch,
                created_by,
                created_by,
                now,
                now,
                normalized_type,
                normalized_priority,
                "{}",
                "{}",
                "{}",
                "",
                "{}",
                "",
                normalized_model_name,
                normalized_reasoning_effort,
            ),
        )
        for item in normalized_attachments:
            conn.execute(
                """
                INSERT INTO mobile_artifacts (id, task_id, kind, label, path, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, task_id, item["kind"], item["label"], item["path"], created_by, now),
            )
        _record_event(
            conn,
            task_id,
            "task_created",
            "user",
            created_by,
            {
                "task_key": task_key,
                "target_env": target_env,
                "task_type": normalized_type,
                "priority": normalized_priority,
                "model_profile": normalized_model_profile,
                "attachment_count": len(normalized_attachments),
            },
        )
        _append_task_message(conn, task_id, "user", "chat", text)
    return get_task(task_id)


def list_tasks(limit=40):
    initialize_database()
    with _connect() as conn:
        task_rows = conn.execute(
            """
            SELECT * FROM mobile_tasks
            ORDER BY
                CASE UPPER(COALESCE(priority, 'NORMAL'))
                    WHEN 'URGENT' THEN 0
                    WHEN 'HIGH' THEN 1
                    WHEN 'NORMAL' THEN 2
                    ELSE 3
                END,
                updated_at DESC,
                created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        task_ids = [row["id"] for row in task_rows]
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        check_rows = conn.execute(f"SELECT * FROM mobile_check_items WHERE task_id IN ({placeholders}) ORDER BY created_at ASC", task_ids).fetchall()
        artifact_rows = conn.execute(f"SELECT * FROM mobile_artifacts WHERE task_id IN ({placeholders}) ORDER BY created_at DESC", task_ids).fetchall()
        comment_rows = conn.execute(f"SELECT * FROM mobile_task_comments WHERE task_id IN ({placeholders}) ORDER BY created_at DESC", task_ids).fetchall()
        event_rows = conn.execute(f"SELECT * FROM mobile_task_events WHERE task_id IN ({placeholders}) ORDER BY created_at DESC", task_ids).fetchall()
        message_rows = conn.execute(f"SELECT * FROM mobile_task_messages WHERE task_id IN ({placeholders}) ORDER BY created_at ASC, rowid ASC", task_ids).fetchall()
        heartbeat_rows = conn.execute(f"SELECT * FROM mobile_worker_heartbeats WHERE task_id IN ({placeholders}) ORDER BY created_at DESC", task_ids).fetchall()
        latest_rows = conn.execute(
            f"""
            SELECT h.* FROM mobile_worker_heartbeats h
            JOIN (
                SELECT task_id, MAX(created_at) AS latest_created_at
                FROM mobile_worker_heartbeats
                WHERE task_id IN ({placeholders})
                GROUP BY task_id
            ) latest
            ON latest.task_id = h.task_id AND latest.latest_created_at = h.created_at
            """,
            task_ids,
        ).fetchall()
        upload_rows = conn.execute(f"SELECT * FROM mobile_upload_jobs WHERE task_id IN ({placeholders}) ORDER BY created_at DESC", task_ids).fetchall()
    check_map = defaultdict(list)
    artifact_map = defaultdict(list)
    comment_map = defaultdict(list)
    event_map = defaultdict(list)
    message_map = defaultdict(list)
    heartbeat_map = defaultdict(list)
    upload_map = defaultdict(list)
    latest_map = {row["task_id"]: row for row in latest_rows if row["task_id"]}
    for row in check_rows:
        check_map[row["task_id"]].append(_serialize_check_item(row))
    for row in artifact_rows:
        artifact_map[row["task_id"]].append(_serialize_artifact(row))
    for row in comment_rows:
        comment_map[row["task_id"]].append(_serialize_comment(row))
    for row in event_rows:
        event_map[row["task_id"]].append(_serialize_event(row))
    for row in message_rows:
        message_map[row["task_id"]].append(_serialize_message(row))
    for row in heartbeat_rows:
        if row["task_id"]:
            heartbeat_map[row["task_id"]].append(row)
    for row in upload_rows:
        upload_map[row["task_id"]].append(_serialize_upload_job(row))
    tasks = []
    for row in task_rows:
        check_items = check_map.get(row["id"], [])
        artifacts = artifact_map.get(row["id"], [])
        comments = comment_map.get(row["id"], [])
        events = event_map.get(row["id"], [])
        gate = _upload_gate(row, check_items, artifacts, latest_map.get(row["id"]))
        checklist_summary = summarize_checklist(check_items)
        followup_bundle = _task_followup_bundle(row)
        if followup_bundle.get("status") == "NONE":
            followup_bundle = _build_followup_bundle(row, check_items, comments)
        upload_jobs = upload_map.get(row["id"], [])
        latest_upload_job = upload_jobs[0] if upload_jobs else None
        upload_request_pending = bool(latest_upload_job and latest_upload_job["status"] in {"REQUESTED", "UPLOADING"})
        result_payload = _task_result_payload(row)
        self_review = _task_self_review(row)
        user_status = map_user_status(row["status"])
        next_action = compute_next_action(row, gate, checklist_summary)
        decision_summary = compute_decision_summary(row, checklist_summary, gate)
        risk_summary = compute_risk_summary(row, checklist_summary, gate)
        warning_badges = _build_warning_badges(row, checklist_summary, gate, latest_upload_job)
        tasks.append(
            {
                "id": row["id"],
                "task_id": row["id"],
                "task_type": row["task_type"] or "FREEFORM",
                "task_type_label": TASK_TYPE_LABELS.get(row["task_type"] or "FREEFORM", row["task_type"] or "FREEFORM"),
                "model_profile": row["model_profile"] or "mobile_worker",
                "model_name": row["model_name"] or "",
                "reasoning_effort": row["reasoning_effort"] or "",
                "title": row["title"],
                "text": row["text"],
                "user_instruction": row["text"],
                "original_instruction": row["text"],
                "task_key": row["task_key"] or "",
                "priority": row["priority"] or "NORMAL",
                "status": row["status"],
                "status_label": TASK_STATUS_LABELS.get(row["status"], row["status"]),
                "user_status": user_status,
                "target_env": row["target_env"] or "",
                "target_branch": row["target_branch"] or "",
                "progress_percent": int(row["progress_percent"] or 0),
                "current_step_code": row["current_step_code"] or "",
                "current_step_label": row["current_step_label"] or "",
                "summary": row["summary"] or "",
                "latest_summary": row["summary"] or "",
                "created_by": row["created_by"],
                "updated_by": row["updated_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "plan_summary": _task_plan_summary(row),
                "result_payload": result_payload,
                "implemented_features": result_payload.get("implemented_features", []),
                "changed_files": result_payload.get("changed_files", []),
                "self_review": self_review,
                "progress_updates": _build_progress_updates(heartbeat_map.get(row["id"], []), events),
                "check_sections": _task_sections(check_items),
                "checklist_items": check_items,
                "checklist_summary": checklist_summary,
                "artifacts": artifacts,
                "comments": comments,
                "user_comments": comments,
                "events": events,
                "messages": message_map.get(row["id"], []),
                "upload_jobs": upload_jobs,
                "latest_upload_job_status": latest_upload_job["status"] if latest_upload_job else "",
                "upload_gate": gate,
                "upload_readiness": {"allowed": gate["can_request_upload"], "reasons": gate["reasons"]},
                "warning_badges": warning_badges,
                "decision_summary": decision_summary,
                "risk_summary": risk_summary,
                "next_action": next_action,
                "followup_bundle": followup_bundle,
                "final_decision": (row["final_decision"] or "").strip(),
                "actions": {
                    "can_proceed": str(row["status"] or "").strip().upper() in {"WAITING_APPROVAL", "HOLD", "FAILED", "UPLOAD_VERIFY_FAILED", "REVISION_REQUESTED"},
                    "can_execute_now": str(row["status"] or "").strip().upper() in {"WAITING_APPROVAL"},
                    "can_start_redebug": str(row["status"] or "").strip().upper() == "REVISION_REQUESTED",
                    "can_request_plan": str(row["status"] or "").strip().upper() in {"QUEUED"},
                    "can_finalize_plan": str(row["status"] or "").strip().upper() in {"PLANNING"},
                    "can_reflect_result": str(row["status"] or "").strip().upper() in {"RUNNING", "REDEBUG_RUNNING"},
                    "can_confirm_review": str(row["status"] or "").strip().upper() in {"WAITING_USER_CHECK"},
                    "can_prepare_upload": str(row["status"] or "").strip().upper() in {"WAITING_REVIEW"},
                    "can_claim_upload": str(row["status"] or "").strip().upper() == "UPLOAD_APPROVED" and str(latest_upload_job["status"] or "").strip().upper() == "REQUESTED",
                    "can_finish_upload": str(row["status"] or "").strip().upper() == "UPLOADING" and str(latest_upload_job["status"] or "").strip().upper() == "UPLOADING",
                    "can_finish_post_upload_verify": str(row["status"] or "").strip().upper() == "POST_UPLOAD_VERIFY",
                    "can_fail_post_upload_verify": str(row["status"] or "").strip().upper() == "POST_UPLOAD_VERIFY",
                    "can_retry": str(row["status"] or "").strip().upper() in {"FAILED", "UPLOAD_VERIFY_FAILED"},
                    "can_request_upload": gate["can_request_upload"] and not upload_request_pending,
                    "can_complete": _can_finalize_task(check_items, self_review, artifacts) and row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_hold": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_fail": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_requeue": row["status"] not in {"QUEUED", "PLANNING", "RUNNING", "REDEBUG_RUNNING", "UPLOADING", "DISCARDED", "CANCELED"},
                    "can_discard": row["status"] not in {"DONE", "FAILED", "UPLOAD_VERIFY_FAILED", "DISCARDED", "CANCELED"} and not (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED"),
                    "can_request_redebug": bool(checklist_summary["failed"] or checklist_summary["change_requested"] or checklist_summary.get("blocked") or str(row["status"] or "").strip().upper() == "UPLOAD_VERIFY_FAILED" or (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED")),
                },
            }
        )
    return tasks


def get_task(task_id):
    for item in list_tasks(limit=200):
        if item["id"] == task_id:
            return item
    return None


def get_task_messages(task_id):
    task = get_task(task_id)
    if not task:
        return []
    return task.get("messages", [])


def get_task_checklist(task_id):
    task = get_task(task_id)
    if not task:
        return {"sections": [], "summary": {}}
    return {
        "sections": task.get("check_sections", []),
        "items": task.get("checklist_items", []),
        "summary": task.get("checklist_summary", {}),
    }


def recompute_task_upload_readiness(task_id):
    initialize_database()
    with _connect() as conn:
        gate = _sync_ready_to_upload(conn, task_id)
    task = get_task(task_id)
    return {
        "allowed": gate.get("can_request_upload", False),
        "reasons": gate.get("reasons", []),
        "item": task,
    }


def plan_task(task_id, actor):
    initialize_database()
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("작업을 찾을 수 없습니다.")
        checklist_count = conn.execute("SELECT COUNT(*) AS count FROM mobile_check_items WHERE task_id = ?", (task_id,)).fetchone()["count"]
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'PLANNING',
                progress_percent = 0,
                current_step_code = 'planning',
                current_step_label = '계획 수립 중',
                next_action = 'Codex가 작업 계획을 정리하고 있습니다.',
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (_now(), actor, task_id),
        )
        _record_event(conn, task_id, 'task_planning_requested', 'system', actor, {'checklist_count': checklist_count})
        _append_task_message(conn, task_id, 'system', 'status', '계획 수립을 요청했습니다. Codex가 작업 범위를 정리합니다.')
    return get_task(task_id)


def complete_task_plan_for_review(task_id, actor, summary=""):
    task = get_task(task_id)
    if not task:
        raise ValueError("작업을 찾을 수 없습니다.")
    status = str(task.get("status") or "").strip().upper()
    if status != "PLANNING":
        raise ValueError("계획 수립 중인 작업만 검토 준비 상태로 전환할 수 있습니다.")
    plan = task.get("plan_summary") or {}
    cleaned_summary = (summary or "").strip()
    if not cleaned_summary:
        goal = str(plan.get("goal") or task.get("title") or "작업 계획").strip()
        impact_scope = str(plan.get("impact_scope") or "요청 범위 기준 최소 수정").strip()
        cleaned_summary = f"작업 계획을 정리했습니다. 목표 · {goal} / 영향 범위 · {impact_scope}"
    return finish_task_planning(
        task_id,
        actor,
        "manual-plan-review",
        cleaned_summary,
        next_action="계획과 체크리스트를 확인한 뒤 진행을 누르세요.",
    )


def reflect_task_result_for_review(task_id, actor, summary=""):
    task = get_task(task_id)
    if not task:
        raise ValueError("작업을 찾을 수 없습니다.")
    status = str(task.get("status") or "").strip().upper()
    if status not in {"RUNNING", "REDEBUG_RUNNING"}:
        raise ValueError("코드 수정 중 또는 재디버그 중인 작업만 결과 반영을 실행할 수 있습니다.")
    cleaned_summary = (summary or "").strip()
    review_reset = None
    if not cleaned_summary:
        title = str(task.get("title") or "작업").strip()
        if status == "REDEBUG_RUNNING":
            cleaned_summary = f"{title} 재디버그 결과를 정리해 다시 사용자 검토 단계로 넘겼습니다."
            review_reset = {
                "verification_summary": "",
                "affected_files": [],
                "affected_modules": [],
                "side_effects": "",
                "regression_risks": [],
            }
        else:
            cleaned_summary = f"{title} 결과를 정리해 사용자 검토 단계로 넘겼습니다."
    elif status == "REDEBUG_RUNNING":
        review_reset = {
            "verification_summary": "",
            "affected_files": [],
            "affected_modules": [],
            "side_effects": "",
            "regression_risks": [],
        }
    return finish_task_success(
        task_id,
        actor,
        "manual-redebug-review" if status == "REDEBUG_RUNNING" else "manual-result-review",
        cleaned_summary,
        [],
        self_review=review_reset,
        next_action="재디버그 결과와 체크리스트를 다시 검토하고 필요한 확인을 진행하세요." if status == "REDEBUG_RUNNING" else "결과와 체크리스트를 검토하고 필요한 확인을 진행하세요.",
    )


def finish_task_planning(task_id, worker_id, run_id, summary, plan_summary=None, result_payload=None, checklist_items=None, next_action=""):
    initialize_database()
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("작업을 찾을 수 없습니다.")
        merged_plan = _task_plan_summary(task_row)
        if plan_summary:
            merged_plan.update(plan_summary)
        merged_result = _task_result_payload(task_row)
        if result_payload:
            merged_result.update(result_payload)
        merged_result["latest_summary"] = (summary or "").strip()
        if checklist_items:
            _replace_checklist_items_from_result(conn, task_id, checklist_items, worker_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'WAITING_APPROVAL',
                progress_percent = 0,
                current_step_code = 'waiting_approval',
                current_step_label = '실행 승인 대기',
                summary = ?,
                plan_summary_json = ?,
                result_payload_json = ?,
                self_review_json = '{}',
                next_action = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (
                (summary or "").strip(),
                _json_dumps(merged_plan),
                _json_dumps(merged_result),
                next_action or '계획과 체크리스트를 확인한 뒤 진행을 누르세요.',
                _now(),
                worker_id,
                task_id,
            ),
        )
        _record_event(conn, task_id, 'task_planned', 'worker', worker_id, {'run_id': run_id})
        _append_task_message(conn, task_id, 'agent', 'plan', (summary or '작업 계획이 준비되었습니다.').strip())
        conn.commit()
    return get_task(task_id)


def start_task(task_id, actor, command_text=""):
    task = get_task(task_id)
    if not task:
        raise ValueError("작업을 찾을 수 없습니다.")
    status = str(task.get("status") or "").strip().upper()
    if status == "REVISION_REQUESTED":
        return start_redebug_for_task(task_id, actor, command_text=command_text)
    if status not in {"WAITING_APPROVAL", "HOLD", "FAILED", "UPLOAD_VERIFY_FAILED"}:
        raise ValueError("진행 가능한 상태가 아닙니다.")
    return update_task_action(task_id, actor, 'requeue', command_text=command_text)


def start_redebug_for_task(task_id, actor, command_text=""):
    clean_task_id = str(task_id or "").strip()
    clean_actor = str(actor or "").strip() or "worker"
    if not clean_task_id:
        raise ValueError("task_id가 필요합니다.")
    initialize_database()
    worker_id = f"{clean_actor}-redebug-worker"
    run_id = uuid.uuid4().hex
    lease_token = uuid.uuid4().hex
    lease_expires_at = (datetime.now() + timedelta(seconds=90)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (clean_task_id,)).fetchone()
        if not row:
            raise ValueError("작업을 찾을 수 없습니다.")
        if str(row["status"] or "").strip().upper() != "REVISION_REQUESTED":
            raise ValueError("재디버그 요청 상태의 작업만 재디버그를 시작할 수 있습니다.")
        _append_user_command_message(conn, clean_task_id, command_text)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'REDEBUG_RUNNING',
                progress_percent = 0,
                current_step_code = 'redebug_running',
                current_step_label = '재디버그 시작',
                next_action = '반영 검증 실패 내용을 반영해 재디버그를 진행 중입니다.',
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = ?,
                current_run_id = ?,
                lease_token = ?,
                lease_expires_at = ?
            WHERE id = ?
            """,
            (_now(), clean_actor, worker_id, run_id, lease_token, lease_expires_at, clean_task_id),
        )
        _record_event(conn, clean_task_id, "task_claimed", "worker", worker_id, {"run_id": run_id, "mode": "REDEBUG_RUNNING", "source": "user_start"})
        _append_task_message(conn, clean_task_id, "system", "status", "재디버그 실행을 시작했습니다. 실패 내용을 반영해 다시 작업합니다.")
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "REDEBUG_RUNNING",
        task_id=clean_task_id,
        run_id=run_id,
        progress_percent=0,
        current_step_code="redebug_running",
        current_step_label="재디버그 시작",
        summary="재디버그 실행을 시작했습니다. 실패 내용을 반영해 다시 작업합니다."[:300],
        task_status="REDEBUG_RUNNING",
    )
    return get_task(clean_task_id)


def add_comment(task_id, actor, body, kind="instruction", parent_check_item_id="", set_hold=True, command_text=""):
    initialize_database()
    body = (body or "").strip()
    if not body:
        raise ValueError("추가 지시 내용을 입력해 주세요.")
    with _connect() as conn:
        _append_user_command_message(conn, task_id, command_text)
        conn.execute(
            """
            INSERT INTO mobile_task_comments (
                id, task_id, parent_check_item_id, kind, body, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, task_id, parent_check_item_id, kind, body, actor, _now()),
        )
        if kind in {"instruction", "followup_instruction"}:
            first_line = body.splitlines()[0][:80]
            derived_title = f"후속 요청 · {first_line}" if first_line else "후속 요청"
            _create_derived_check_item(
                conn,
                task_id,
                actor,
                derived_title,
                body,
                section="EXECUTION",
                parent_item_id=parent_check_item_id,
                test_required=False,
                user_confirmation_required=True,
            )
        if set_hold and kind in {"instruction", "followup_instruction"}:
            conn.execute(
                """
                UPDATE mobile_upload_jobs
                SET status = 'CANCELED',
                    result_summary = CASE
                        WHEN result_summary IS NULL OR result_summary = '' THEN '추가 지시로 인해 기존 업로드 요청을 취소했습니다.'
                        ELSE result_summary || '\n\n[자동 취소] 추가 지시로 인해 업로드 요청을 취소했습니다.'
                    END,
                    updated_at = ?
                WHERE task_id = ? AND status IN ('REQUESTED', 'UPLOADING')
                """,
                (_now(), task_id),
            )
            conn.execute(
                """
                UPDATE mobile_tasks
                SET status = 'WAITING_APPROVAL',
                    progress_percent = 0,
                    current_step_code = 'waiting_approval',
                    current_step_label = '실행 승인 대기',
                    next_action = '추가 지시를 확인한 뒤 진행을 눌러 다시 실행하세요.',
                    final_decision = '',
                    updated_at = ?,
                    updated_by = ?,
                    assigned_worker_id = '',
                    current_run_id = '',
                    lease_token = '',
                    lease_expires_at = ''
                WHERE id = ? AND status NOT IN ('DISCARDED','CANCELED')
                """,
                (_now(), actor, task_id),
            )
        _record_event(conn, task_id, "comment_added", "user", actor, {"kind": kind, "parent_check_item_id": parent_check_item_id})
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        check_rows = conn.execute("SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
        comment_rows = conn.execute("SELECT * FROM mobile_task_comments WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
        followup_bundle = _build_followup_bundle(
            task_row,
            [_serialize_check_item(row) for row in check_rows],
            [_serialize_comment(row) for row in comment_rows],
        )
        conn.execute(
            "UPDATE mobile_tasks SET followup_bundle_json = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (_json_dumps(followup_bundle), _now(), actor, task_id),
        )
        _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)


def update_check_item_action(check_item_id, actor, action, note=""):
    mapping = {
        "done": "DONE",
        "fail": "FAILED",
        "discard": "DISCARDED",
        "progress": "IN_PROGRESS",
        "block": "BLOCKED",
        "todo": "PENDING",
        "change_request": "CHANGE_REQUESTED",
    }
    if action not in mapping:
        raise ValueError("허용되지 않은 체크리스트 액션입니다.")
    cleaned_note = (note or "").strip()
    if action in {"fail", "change_request"} and not cleaned_note:
        raise ValueError("실패와 변경요청은 코멘트를 반드시 입력해야 합니다.")
    initialize_database()
    with _connect() as conn:
        row = conn.execute("SELECT task_id, title, section FROM mobile_check_items WHERE id = ?", (check_item_id,)).fetchone()
        if not row:
            raise ValueError("체크리스트 항목을 찾을 수 없습니다.")
        new_status = mapping[action]
        conn.execute(
            """
            UPDATE mobile_check_items
            SET status = ?, note = ?, updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, cleaned_note, actor, _now(), check_item_id),
        )
        if cleaned_note and action in {"fail", "change_request"}:
            conn.execute(
                """
                INSERT INTO mobile_task_comments (
                    id, task_id, parent_check_item_id, kind, body, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, row["task_id"], check_item_id, "change_request" if action == "change_request" else "failure_note", cleaned_note, actor, _now()),
            )
            if action == "change_request":
                _create_derived_check_item(
                    conn,
                    row["task_id"],
                    actor,
                    f"보완 요청 · {str(row['title'] or '').strip()[:80]}",
                    cleaned_note,
                    section=str(row["section"] or "EXECUTION"),
                    parent_item_id=check_item_id,
                    test_required=False,
                    user_confirmation_required=True,
                )
        _record_event(conn, row["task_id"], "check_item_action", "user", actor, {"check_item_id": check_item_id, "action": action})
        message_map = {
            "done": ("status", f"항목 완료. {row['title']}"),
            "discard": ("status", f"항목 폐기. {row['title']}"),
            "fail": ("error", f"항목 실패. {row['title']}"),
            "change_request": ("status", f"보완 요청 등록. {row['title']}"),
            "progress": ("status", f"항목 진행 중. {row['title']}"),
            "todo": ("status", f"항목 재대기. {row['title']}"),
            "block": ("error", f"항목 차단. {row['title']}"),
        }
        message_type, message_text = message_map.get(action, ("status", "체크 상태가 변경되었습니다."))
        if cleaned_note and action in {"fail", "change_request"}:
            message_text = f"{message_text} · {cleaned_note}"
        _append_task_message(conn, row["task_id"], "system", message_type, message_text)
        if new_status in {"FAILED", "CHANGE_REQUESTED"}:
            conn.execute(
                """
                UPDATE mobile_tasks
                SET status = 'WAITING_USER_CHECK',
                    current_step_code = 'waiting_user_check',
                    current_step_label = '사용자 검토 대기',
                    next_action = '변경요청/실패 코멘트를 검토한 뒤 재디버그 요청을 실행하세요.',
                    final_decision = ''
                WHERE id = ?
                """,
                (row["task_id"],),
            )
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (row["task_id"],)).fetchone()
        check_rows = conn.execute("SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC", (row["task_id"],)).fetchall()
        comment_rows = conn.execute("SELECT * FROM mobile_task_comments WHERE task_id = ? ORDER BY created_at DESC", (row["task_id"],)).fetchall()
        followup_bundle = _build_followup_bundle(
            task_row,
            [_serialize_check_item(item) for item in check_rows],
            [_serialize_comment(item) for item in comment_rows],
        )
        conn.execute(
            "UPDATE mobile_tasks SET followup_bundle_json = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (_json_dumps(followup_bundle), _now(), actor, row["task_id"]),
        )
        _sync_ready_to_upload(conn, row["task_id"])
    return get_task(row["task_id"])

# Live runtime block: task claim 로직 패치는 이 최종 정의를 기준으로 수정한다.
def claim_next_task(worker_id, lease_seconds=90):
    initialize_database()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _recover_expired_leases(conn)
        row = conn.execute(
            """
            SELECT * FROM mobile_tasks
            WHERE status IN ('POST_UPLOAD_VERIFY', 'PLANNING', 'QUEUED', 'REVISION_REQUESTED')
              AND COALESCE(lease_token, '') = ''
            ORDER BY
                CASE
                    WHEN status = 'POST_UPLOAD_VERIFY' THEN 0
                    WHEN status = 'PLANNING' THEN 1
                    WHEN status = 'REVISION_REQUESTED' THEN 2
                    ELSE 3
                END,
                CASE UPPER(COALESCE(priority, 'NORMAL'))
                    WHEN 'URGENT' THEN 0
                    WHEN 'HIGH' THEN 1
                    WHEN 'NORMAL' THEN 2
                    ELSE 3
                END,
                created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        run_id = uuid.uuid4().hex
        lease_token = uuid.uuid4().hex
        lease_expires_at = (datetime.now() + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        if row["status"] == "REVISION_REQUESTED":
            next_status = "REDEBUG_RUNNING"
            next_label = "재디버그 시작"
            next_code = "redebug_running"
            next_progress = 0
        elif row["status"] == "POST_UPLOAD_VERIFY":
            next_status = "POST_UPLOAD_VERIFY"
            next_label = "업로드 후 검증"
            next_code = "post_upload_verify"
            next_progress = 90
        elif row["status"] == "PLANNING":
            next_status = "PLANNING"
            next_label = "계획 수립 중"
            next_code = "planning"
            next_progress = 5
        else:
            next_status = "RUNNING"
            next_label = "실행 시작"
            next_code = "running"
            next_progress = 0
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = ?,
                progress_percent = ?,
                current_step_code = ?,
                current_step_label = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = ?,
                current_run_id = ?,
                lease_token = ?,
                lease_expires_at = ?
            WHERE id = ?
            """,
            (next_status, next_progress, next_code, next_label, _now(), worker_id, worker_id, run_id, lease_token, lease_expires_at, row["id"]),
        )
        _record_event(conn, row["id"], "task_claimed", "worker", worker_id, {"run_id": run_id, "mode": next_status})
        claimed_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (row["id"],)).fetchone()
        conn.commit()
    return dict(claimed_row)


def update_task_action(task_id, actor, action, summary="", command_text=""):
    initialize_database()
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task_row:
            raise ValueError("작업을 찾을 수 없습니다.")
        cleaned_summary = (summary or "").strip()
        if cleaned_summary:
            conn.execute(
                "UPDATE mobile_tasks SET summary = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                (cleaned_summary, _now(), actor, task_id),
            )
        check_rows = conn.execute("SELECT * FROM mobile_check_items WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
        artifact_rows = conn.execute("SELECT * FROM mobile_artifacts WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
        comment_rows = conn.execute("SELECT * FROM mobile_task_comments WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
        check_items = [_serialize_check_item(row) for row in check_rows]
        artifacts = [_serialize_artifact(row) for row in artifact_rows]
        comments = [_serialize_comment(row) for row in comment_rows]
        self_review = _task_self_review(task_row)
        latest_upload_job = _latest_upload_job_row(conn, task_id)
        next_status = None
        next_step_code = task_row["current_step_code"] or ""
        next_step_label = task_row["current_step_label"] or ""
        next_action = task_row["next_action"] or ""
        final_decision = task_row["final_decision"] or ""
        followup_bundle = _task_followup_bundle(task_row)
        if action == "hold":
            next_status = "HOLD"
            next_step_code = "hold"
            next_step_label = "보류"
            next_action = "보류 사유를 정리하고 재개 시점을 결정하세요."
        elif action == "fail":
            next_status = "FAILED"
            next_step_code = "failed"
            next_step_label = "실패"
            next_action = "실패 사유를 확인하고 재디버그 여부를 결정하세요."
            final_decision = "FAILED_BY_USER"
        elif action == "complete":
            if (
                str(task_row["status"] or "").strip().upper() == "UPLOAD_VERIFY_FAILED"
                or (latest_upload_job and str(latest_upload_job["status"] or "").strip().upper() == "FAILED")
                or not _can_finalize_task(check_items, self_review, artifacts)
            ):
                raise ValueError("필수 체크리스트와 자체검수가 모두 끝나기 전에는 완료 처리할 수 없습니다.")
            next_status = "DONE"
            next_step_code = "done"
            next_step_label = "최종 완료"
            next_action = "모든 검수가 완료되었습니다."
            final_decision = "DONE_BY_USER"
        elif action == "discard":
            next_status = "DISCARDED"
            next_step_code = "discarded"
            next_step_label = "폐기"
            next_action = "폐기된 작업입니다."
            final_decision = "DISCARDED_BY_USER"
        elif action == "request_upload":
            gate = _sync_ready_to_upload(conn, task_id)
            if not gate["can_request_upload"]:
                raise ValueError("서버 업로드 승인 조건이 아직 충족되지 않았습니다.")
            latest_heartbeat = conn.execute(
                "SELECT * FROM mobile_worker_heartbeats WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            pre_verify = run_pre_upload_verify(task_row, check_items, artifacts, latest_heartbeat)
            if not pre_verify["passed"]:
                raise ValueError(pre_verify["reason_text"] or "사전 업로드 검증을 통과하지 못했습니다.")
            if latest_upload_job and latest_upload_job["status"] in {"REQUESTED", "UPLOADING"}:
                raise ValueError("이미 서버 업로드 승인 요청이 접수되었습니다.")
            next_status = "UPLOAD_APPROVED"
            next_step_code = "upload_approved"
            next_step_label = "업로드 승인됨"
            next_action = "업로드 워커가 승인 요청을 처리하고 있습니다."
            append_event(conn, task_id, "pre_upload_verify_passed", "system", actor, {"checks": pre_verify["items"]})
            conn.execute(
                """
                INSERT INTO mobile_upload_jobs (
                    id, task_id, status, target_env, approved_by, result_summary, created_at, updated_at
                ) VALUES (?, ?, 'REQUESTED', ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, task_id, task_row["target_env"] or "local", actor, cleaned_summary, _now(), _now()),
            )
        elif action == "execute_now":
            if str(task_row["status"] or "").strip().upper() != "WAITING_APPROVAL":
                raise ValueError("실행 승인 대기 상태의 작업만 바로 실행할 수 있습니다.")
            next_status = "RUNNING"
            next_step_code = "running"
            next_step_label = "코드 수정 중"
            next_action = "Codex가 작업을 수행 중입니다. 결과가 정리되면 사용자 검토 단계로 넘어갑니다."
            final_decision = ""
        elif action == "confirm_review":
            if str(task_row["status"] or "").strip().upper() != "WAITING_USER_CHECK":
                raise ValueError("사용자 검토 대기 상태의 작업만 검토 완료 처리할 수 있습니다.")
            next_status = "WAITING_REVIEW"
            next_step_code = "waiting_review"
            next_step_label = "검토 완료"
            next_action = "업로드 전 마지막 확인을 진행하세요."
            final_decision = ""
        elif action == "prepare_upload":
            if str(task_row["status"] or "").strip().upper() != "WAITING_REVIEW":
                raise ValueError("검토 완료 상태의 작업만 업로드 준비 확인을 진행할 수 있습니다.")
            gate = _sync_ready_to_upload(conn, task_id)
            if gate["can_request_upload"]:
                next_status = "READY_TO_UPLOAD"
                next_step_code = "ready_to_upload"
                next_step_label = "업로드 준비"
                next_action = "업로드 승인 가능 상태입니다. 서버 업로드 승인을 진행하세요."
            else:
                next_status = "WAITING_REVIEW"
                next_step_code = "waiting_review"
                next_step_label = "검토 완료"
                gate_reason = (gate.get("reasons") or ["업로드 전 마지막 확인이 남아 있습니다."])[0]
                next_action = f"업로드 준비 미완료 · {gate_reason}"
            final_decision = ""
        elif action == "requeue":
            next_status = "QUEUED"
            next_step_code = "queued"
            next_step_label = "대기"
            next_action = "Codex 작업 대기"
            final_decision = ""
        elif action == "request_redebug":
            followup_bundle = _build_followup_bundle(task_row, check_items, comments)
            if (not cleaned_summary) and str(task_row["status"] or "").strip().upper() == "UPLOAD_VERIFY_FAILED":
                cleaned_summary = str(task_row["summary"] or "").strip()
                if not cleaned_summary:
                    cleaned_summary = "업로드 후 검증에서 문제가 확인되어 재디버그를 다시 요청합니다."
            if cleaned_summary:
                comment_created_at = _now()
                comment_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO mobile_task_comments (
                        id, task_id, parent_check_item_id, kind, body, created_by, created_at
                    ) VALUES (?, ?, '', 'followup_instruction', ?, ?, ?)
                    """,
                    (comment_id, task_id, cleaned_summary, actor, comment_created_at),
                )
                comments = [
                    {
                        "id": comment_id,
                        "kind": "followup_instruction",
                        "body": cleaned_summary,
                        "created_by": actor,
                        "created_at": comment_created_at,
                        "parent_check_item_id": "",
                    },
                    *comments,
                ]
                followup_bundle = _build_followup_bundle(task_row, check_items, comments)
            if not followup_bundle.get("instruction"):
                raise ValueError("실패/변경요청 코멘트가 없어서 재디버그 요청을 만들 수 없습니다.")
            conn.execute(
                """
                UPDATE mobile_upload_jobs
                SET status = 'CANCELED',
                    result_summary = CASE
                        WHEN result_summary IS NULL OR result_summary = '' THEN '재디버그 요청으로 기존 업로드 요청을 취소했습니다.'
                        ELSE result_summary || '\n\n[자동 취소] 재디버그 요청으로 업로드 요청을 취소했습니다.'
                    END,
                    updated_at = ?
                WHERE task_id = ? AND status IN ('REQUESTED', 'UPLOADING')
                """,
                (_now(), task_id),
            )
            _reset_check_items_for_revision(conn, task_id, actor)
            followup_bundle["status"] = "READY"
            followup_bundle["created_at"] = _now()
            next_status = "REVISION_REQUESTED"
            next_step_code = "revision_requested"
            next_step_label = "재디버그 요청"
            if str(task_row["status"] or "").strip().upper() == "UPLOAD_VERIFY_FAILED":
                next_action = "반영 검증 실패 내용을 반영해 재디버그를 다시 수행합니다."
            else:
                next_action = "변경요청 코멘트를 반영해 재디버그를 다시 수행합니다."
            final_decision = ""
        else:
            raise ValueError("허용되지 않은 작업 액션입니다.")
        _append_user_command_message(conn, task_id, command_text)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = ?, current_step_code = ?, current_step_label = ?, next_action = ?,
                final_decision = ?, followup_bundle_json = ?, updated_at = ?, updated_by = ?,
                assigned_worker_id = CASE WHEN ? IN ('REVISION_REQUESTED', 'QUEUED') THEN '' ELSE assigned_worker_id END,
                current_run_id = CASE WHEN ? IN ('REVISION_REQUESTED', 'QUEUED') THEN '' ELSE current_run_id END,
                lease_token = CASE WHEN ? IN ('REVISION_REQUESTED', 'QUEUED') THEN '' ELSE lease_token END,
                lease_expires_at = CASE WHEN ? IN ('REVISION_REQUESTED', 'QUEUED') THEN '' ELSE lease_expires_at END,
                progress_percent = CASE WHEN ? IN ('REVISION_REQUESTED', 'QUEUED') THEN 0 ELSE progress_percent END
            WHERE id = ?
            """,
            (
                next_status,
                next_step_code,
                next_step_label,
                next_action,
                final_decision,
                _json_dumps(followup_bundle),
                _now(),
                actor,
                next_status,
                next_status,
                next_status,
                next_status,
                next_status,
                task_id,
            ),
        )
        _record_event(conn, task_id, "task_action", "user", actor, {"action": action})
        task_action_messages = {
            "execute_now": ("status", "실행을 시작했습니다. 작업 결과를 기다리세요."),
            "confirm_review": ("status", "사용자 검토를 완료했습니다."),
            "prepare_upload": ("status", "업로드 준비 상태를 확인했습니다."),
            "requeue": ("status", "진행 승인됨. 순차 실행을 시작합니다."),
            "hold": ("status", "작업이 보류 상태로 전환되었습니다."),
            "fail": ("error", "작업이 실패 처리되었습니다."),
            "complete": ("result", "모든 확인이 끝나 작업을 완료 처리했습니다."),
            "discard": ("status", "작업을 폐기 처리했습니다."),
            "request_upload": ("status", "업로드 승인 요청이 등록되었습니다."),
            "request_redebug": ("status", "보완 요청을 반영해 재디버그 대기 상태로 전환했습니다."),
        }
        message_type, message_text = task_action_messages.get(action, ("status", "작업 상태가 변경되었습니다."))
        if action == "prepare_upload":
            if next_status == "READY_TO_UPLOAD":
                message_text = "업로드 준비 확인이 끝났습니다. 서버 업로드 승인을 진행할 수 있습니다."
            else:
                message_text = next_action
        if cleaned_summary and action in {"fail", "request_redebug"}:
            message_text = f"{message_text} · {cleaned_summary}"
        _append_task_message(conn, task_id, "system", message_type, message_text)
        _sync_ready_to_upload(conn, task_id)
    return get_task(task_id)

# Live runtime block: success 완료 후처리 패치는 이 최종 정의를 기준으로 수정한다.
def finish_task_success(task_id, worker_id, run_id, summary, artifact_paths, plan_summary=None, result_payload=None, self_review=None, checklist_items=None, next_action="", final_decision=""):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        merged_plan = _task_plan_summary(task_row)
        if plan_summary:
            merged_plan.update(plan_summary)
        merged_result = _task_result_payload(task_row)
        if result_payload:
            merged_result.update(result_payload)
        merged_result["latest_summary"] = (summary or "").strip()
        merged_self_review = _task_self_review(task_row)
        if self_review:
            merged_self_review.update(self_review)
        if checklist_items:
            _replace_checklist_items_from_result(conn, task_id, checklist_items, worker_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'WAITING_USER_CHECK',
                progress_percent = 100,
                current_step_code = 'waiting_user_check',
                current_step_label = '사용자 검토 대기',
                summary = ?,
                plan_summary_json = ?,
                result_payload_json = ?,
                self_review_json = ?,
                next_action = ?,
                final_decision = ?,
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (
                (summary or "").strip(),
                _json_dumps(merged_plan),
                _json_dumps(merged_result),
                _json_dumps(merged_self_review),
                next_action or "결과와 자체검수를 검토하고 체크리스트를 확인하세요.",
                final_decision or "",
                _now(),
                worker_id,
                task_id,
            ),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "success"})
        _append_task_message(conn, task_id, "agent", "result", (summary or "작업이 완료되었습니다.").strip())
        _sync_ready_to_upload(conn, task_id)
        current_row = conn.execute("SELECT status FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        final_status = current_row["status"] if current_row else "WAITING_USER_CHECK"
        final_step_code = "ready_to_upload" if final_status == "READY_TO_UPLOAD" else "waiting_user_check"
        final_step_label = "업로드 승인 대기" if final_status == "READY_TO_UPLOAD" else "사용자 검토 대기"
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        final_status,
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code=final_step_code,
        current_step_label=final_step_label,
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status=final_status,
    )
    return get_task(task_id)

# Live runtime block: failure 완료 후처리 패치는 이 최종 정의를 기준으로 수정한다.
def finish_task_failure(task_id, worker_id, run_id, summary, artifact_paths=None, plan_summary=None, result_payload=None, self_review=None, checklist_items=None):
    initialize_database()
    artifact_paths = artifact_paths or []
    artifact_ids = []
    with _connect() as conn:
        task_row = conn.execute("SELECT * FROM mobile_tasks WHERE id = ?", (task_id,)).fetchone()
        for artifact_path in artifact_paths:
            artifact_id = register_artifact(task_id, Path(artifact_path).name, artifact_path, worker_id)
            if artifact_id:
                artifact_ids.append(artifact_id)
        merged_plan = _task_plan_summary(task_row)
        if plan_summary:
            merged_plan.update(plan_summary)
        merged_result = _task_result_payload(task_row)
        if result_payload:
            merged_result.update(result_payload)
        merged_result["latest_summary"] = (summary or "").strip()
        merged_self_review = _task_self_review(task_row)
        if self_review:
            merged_self_review.update(self_review)
        if checklist_items:
            _replace_checklist_items_from_result(conn, task_id, checklist_items, worker_id)
        conn.execute(
            """
            UPDATE mobile_tasks
            SET status = 'FAILED',
                current_step_code = 'failed',
                current_step_label = '실패',
                summary = ?,
                plan_summary_json = ?,
                result_payload_json = ?,
                self_review_json = ?,
                next_action = '실패 사유를 확인하고 재디버그 요청 여부를 결정하세요.',
                final_decision = 'FAILED_BY_WORKER',
                updated_at = ?,
                updated_by = ?,
                assigned_worker_id = '',
                current_run_id = '',
                lease_token = '',
                lease_expires_at = ''
            WHERE id = ?
            """,
            (
                (summary or "").strip(),
                _json_dumps(merged_plan),
                _json_dumps(merged_result),
                _json_dumps(merged_self_review),
                _now(),
                worker_id,
                task_id,
            ),
        )
        _record_event(conn, task_id, "task_finished", "worker", worker_id, {"run_id": run_id, "result": "failed"})
        _append_task_message(conn, task_id, "agent", "error", (summary or "작업이 실패했습니다.").strip())
        conn.commit()
    record_worker_heartbeat(
        worker_id,
        "FAILED",
        task_id=task_id,
        run_id=run_id,
        progress_percent=100,
        current_step_code="failed",
        current_step_label="실패",
        summary=(summary or "").strip()[:300],
        latest_artifact_ids=artifact_ids,
        task_status="FAILED",
    )
    return get_task(task_id)
