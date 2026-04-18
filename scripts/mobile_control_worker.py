import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.mobile_control_service import (
    BASE_DIR,
    OUTPUT_DIR,
    claim_next_upload_job,
    claim_next_task,
    ensure_task_checklist,
    finish_task_planning,
    finish_post_upload_verify_failure,
    finish_post_upload_verify_success,
    get_task,
    finish_upload_job_failure,
    finish_upload_job_success,
    finish_task_failure,
    finish_task_success,
    initialize_database,
    record_worker_heartbeat,
)


CAPTURE_SCRIPT = BASE_DIR / "scripts" / "mobile_control_capture.js"
BASE_URL = (os.environ.get("MOBILE_CONTROL_BASE_URL") or "http://127.0.0.1:8001").strip().rstrip("/")
DEFAULT_LOGIN_ID = (os.environ.get("MOBILE_CONTROL_LOGIN_ID") or "").strip()
DEFAULT_PASSWORD = os.environ.get("MOBILE_CONTROL_LOGIN_PASSWORD") or ""
POLL_INTERVAL = 10
HEARTBEAT_INTERVAL = 5
CODEX_TIMEOUT_SECONDS = 1800
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
UPLOAD_SCRIPT = BASE_DIR / "scripts" / "upload_changed_files.ps1"
LOCAL_MOBILE_CONTROL_DIR = BASE_DIR / "mobile_control_local"
REFRESH_LINK_SCRIPT = LOCAL_MOBILE_CONTROL_DIR / "refresh_mobile_control_link.ps1"
SFTP_CONFIG = BASE_DIR / ".vscode" / "sftp.json"
CODEX_PROFILE = (os.environ.get("MOBILE_CONTROL_CODEX_PROFILE") or "mobile_worker").strip() or "mobile_worker"
CODEX_RUNTIME_HOME = OUTPUT_DIR / "mobile_control" / "runtime" / "codex_home"
REMOTE_BASE_URL = (os.environ.get("MOBILE_CONTROL_REMOTE_BASE_URL") or "").strip().rstrip("/")
REMOTE_WORKER_KEY = (os.environ.get("MOBILE_CONTROL_REMOTE_WORKER_KEY") or "").strip()
REMOTE_MODE = bool(REMOTE_BASE_URL)
PROTECTED_UPLOAD_PREFIXES = (
    "scripts/mobile_control",
    "mobile_control_local/",
    "scripts/start_mobile_runtime",
    "scripts/get_mobile_runtime_status",
    "scripts/stop_mobile_runtime",
    "scripts/publish_mobile_control_link",
    "scripts/start_candidate_",
    "scripts/deploy_mobile_control_candidate",
    "scripts/night_agent",
    "scripts/night_auto",
    "scripts/run_night_",
    "routers/mobile_control",
    "services/mobile_control",
    "templates/mobile_control",
    "static/js/mobile_control",
)
PROTECTED_UPLOAD_KEYWORDS = (
    "mobile-control",
    "mobile_control",
    "모바일",
    "지시함",
    "워커",
    "runtime",
    "후보",
    "candidate",
    "deploy",
    "배포",
    "업로드",
    "자동화",
)


class TaskExecutionError(RuntimeError):
    def __init__(self, message, artifacts=None):
        super().__init__(message)
        self.artifacts = artifacts or []


def now_label():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_sftp_config():
    if not SFTP_CONFIG.exists():
        raise TaskExecutionError(".vscode/sftp.json 설정을 찾지 못했습니다.")
    try:
        return json.loads(SFTP_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TaskExecutionError(f"sftp 설정을 읽지 못했습니다. {exc}") from exc


def get_changed_paths():
    completed = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if completed.returncode != 0:
        raise TaskExecutionError(completed.stderr.strip() or "git status ?ㅽ뻾 ?ㅽ뙣")
    items = []
    for raw in completed.stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        normalized = path.replace("\\", "/")
        if normalized.startswith(("output/", "backup/", ".playwright-cli/", "static/uploads/")):
            continue
        items.append(normalized)
    return sorted(set(items))


def _is_protected_upload_path(rel_path):
    normalized = str(rel_path or "").replace("\\", "/").lower()
    return normalized.startswith(PROTECTED_UPLOAD_PREFIXES)


def _allow_protected_upload(rel_path, blobs):
    normalized = str(rel_path or "").replace("\\", "/").lower()
    name = Path(normalized).name
    explicit_tokens = {normalized, name}
    if any(token and any(token in blob for blob in blobs) for token in explicit_tokens):
        return True
    return any(keyword in blob for keyword in PROTECTED_UPLOAD_KEYWORDS for blob in blobs)


def extract_upload_targets(task):
    changed_paths = get_changed_paths()
    if not changed_paths:
        raise TaskExecutionError("?낅줈?쒗븷 蹂寃??뚯씪???놁뒿?덈떎.")
    sources = [
        str(task.get("task_text") or ""),
        str(task.get("task_summary") or ""),
    ]
    for artifact in task.get("artifacts") or []:
        candidate = BASE_DIR / str(artifact.get("path") or "")
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in {".md", ".txt", ".log"}:
            try:
                sources.append(candidate.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
    blobs = [source.replace("\\", "/").lower() for source in sources if source]
    targets = []
    for rel in changed_paths:
        abs_posix = (BASE_DIR / rel).resolve().as_posix().lower()
        rel_lower = rel.lower()
        if _is_protected_upload_path(rel):
            if _allow_protected_upload(rel, blobs):
                targets.append(rel)
                continue
            continue
        if any(rel_lower in blob or abs_posix in blob or f"/{abs_posix}" in blob for blob in blobs):
            targets.append(rel)
    if not targets:
        raise TaskExecutionError("寃곌낵/?붿빟 ?먮뒗 ?곗텧臾쇱뿉???낅줈????곸쑝濡??댁꽍??蹂寃??뚯씪??李얠? 紐삵뻽?듬땲??")
    return targets


def resolve_remote_root(target_env, config):
    remote_root = str(config.get("remotePath") or "").strip()
    if not remote_root:
        raise TaskExecutionError("sftp remotePath ?ㅼ젙??鍮꾩뼱 ?덉뒿?덈떎.")
    target = str(target_env or "").strip().lower()
    if target in {"candidate", "staging", "stage"}:
        return f"{remote_root.rstrip('/')}_candidate"
    if target in {"production", "prod", "server"}:
        return remote_root
    raise TaskExecutionError("?낅줈????곸? ?꾨낫 ?먮뒗 ?댁쁺?댁뼱???⑸땲??")


def get_candidate_remote_root():
    config = load_sftp_config()
    remote_root = resolve_remote_root("candidate", config)
    return config, remote_root


def remote_headers():
    headers = {"Content-Type": "application/json"}
    if REMOTE_WORKER_KEY:
        headers["X-Mobile-Worker-Key"] = REMOTE_WORKER_KEY
    return headers


def remote_json_request(method, path, payload=None, allow_404=False):
    if not REMOTE_MODE:
        raise TaskExecutionError("?먭꺽 紐⑤뱶媛 ?꾨땲誘濡?remote request瑜??ㅽ뻾?????놁뒿?덈떎.")
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{REMOTE_BASE_URL}{path}",
        data=data,
        method=method,
        headers=remote_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if allow_404 and exc.code == 404:
            return None
        raise TaskExecutionError(f"remote api {method} {path} ??쎈솭: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise TaskExecutionError(f"remote api ?怨뚭퍙 ??쎈솭: {path} {exc}") from exc


def sync_artifacts_to_candidate(artifact_paths):
    artifact_paths = [str(path or "").strip() for path in (artifact_paths or []) if str(path or "").strip()]
    if not artifact_paths:
        return []
    config, remote_root = get_candidate_remote_root()
    sync_paths = []
    for rel in artifact_paths:
        local_path = BASE_DIR / rel
        if local_path.exists() and local_path.is_file():
            sync_paths.append(rel)
    if not sync_paths:
        return artifact_paths
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(UPLOAD_SCRIPT),
        "-RemoteHost",
        str(config.get("host") or ""),
        "-Username",
        str(config.get("username") or ""),
        "-RemoteRoot",
        remote_root,
        "-Port",
        str(config.get("port") or 22),
    ]
    key_path = str(config.get("privateKeyPath") or "").strip()
    if key_path:
        args.extend(["-SshKeyPath", key_path])
    args.extend(["-RelativePaths"])
    args.extend(sync_paths)
    completed = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode != 0:
        raise TaskExecutionError(completed.stderr.strip() or completed.stdout.strip() or "?곗텧臾??먭꺽 ?숆린?붿뿉 ?ㅽ뙣?덉뒿?덈떎.")
    return artifact_paths


def claim_next_task_op(worker_id):
    if not REMOTE_MODE:
        return claim_next_task(worker_id)
    payload = remote_json_request("POST", "/api/mobile-control/v2/worker/claim-task", {"worker_id": worker_id}) or {}
    return payload.get("item")


def claim_next_upload_job_op(worker_id):
    if not REMOTE_MODE:
        return claim_next_upload_job(worker_id)
    payload = remote_json_request("POST", "/api/mobile-control/v2/worker/claim-upload-job", {"worker_id": worker_id}) or {}
    item = payload.get("item")
    if item and payload.get("task"):
        item["_task_detail"] = payload.get("task")
    return item


def ensure_task_checklist_op(task_id, actor):
    if not REMOTE_MODE:
        ensure_task_checklist(task_id, actor=actor)
        return
    remote_json_request("POST", f"/api/mobile-control/v2/worker/tasks/{task_id}/ensure-checklist", {"actor": actor})


def get_task_op(task_id):
    if not REMOTE_MODE:
        return get_task(task_id)
    payload = remote_json_request("GET", f"/api/mobile-control/v2/worker/tasks/{task_id}", allow_404=True) or {}
    return payload.get("item")


def record_worker_heartbeat_op(worker_id, state, task_id="", run_id="", progress_percent=0, current_step_code="", current_step_label="", summary="", latest_artifact_ids=None, lease_seconds=90, task_status=None):
    if not REMOTE_MODE:
        record_worker_heartbeat(
            worker_id,
            state,
            task_id=task_id,
            run_id=run_id,
            progress_percent=progress_percent,
            current_step_code=current_step_code,
            current_step_label=current_step_label,
            summary=summary,
            latest_artifact_ids=latest_artifact_ids,
            lease_seconds=lease_seconds,
            task_status=task_status,
        )
        return
    remote_json_request(
        "POST",
        "/api/mobile-control/v2/worker/heartbeat",
        {
            "worker_id": worker_id,
            "state": state,
            "task_id": task_id,
            "run_id": run_id,
            "progress_percent": progress_percent,
            "current_step_code": current_step_code,
            "current_step_label": current_step_label,
            "summary": summary,
            "latest_artifact_ids": latest_artifact_ids or [],
            "lease_seconds": lease_seconds,
            "task_status": task_status or "",
        },
    )


def finish_task_success_op(task_id, worker_id, run_id, summary, artifact_paths, plan_summary=None, result_payload=None, self_review=None, checklist_items=None, next_action="", final_decision=""):
    if not REMOTE_MODE:
        return finish_task_success(
            task_id,
            worker_id,
            run_id,
            summary,
            artifact_paths,
            plan_summary=plan_summary,
            result_payload=result_payload,
            self_review=self_review,
            checklist_items=checklist_items,
            next_action=next_action,
            final_decision=final_decision,
        )
    synced_paths = sync_artifacts_to_candidate(artifact_paths)
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/tasks/{task_id}/finish-success",
        {
            "worker_id": worker_id,
            "run_id": run_id,
            "summary": summary,
            "artifact_paths": synced_paths,
            "plan_summary": plan_summary or {},
            "result_payload": result_payload or {},
            "self_review": self_review or {},
            "checklist_items": checklist_items or [],
            "next_action": next_action,
            "final_decision": final_decision,
        },
    ) or {}
    return payload.get("item")


def finish_task_failure_op(task_id, worker_id, run_id, summary, artifact_paths=None, plan_summary=None, result_payload=None, self_review=None, checklist_items=None):
    if not REMOTE_MODE:
        return finish_task_failure(
            task_id,
            worker_id,
            run_id,
            summary,
            artifact_paths or [],
            plan_summary=plan_summary,
            result_payload=result_payload,
            self_review=self_review,
            checklist_items=checklist_items,
        )
    synced_paths = sync_artifacts_to_candidate(artifact_paths or [])
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/tasks/{task_id}/finish-failure",
        {
            "worker_id": worker_id,
            "run_id": run_id,
            "summary": summary,
            "artifact_paths": synced_paths,
            "plan_summary": plan_summary or {},
            "result_payload": result_payload or {},
            "self_review": self_review or {},
            "checklist_items": checklist_items or [],
        },
    ) or {}
    return payload.get("item")


def finish_task_planning_op(task_id, worker_id, run_id, summary, artifact_paths=None, plan_summary=None, result_payload=None, checklist_items=None, next_action=""):
    if not REMOTE_MODE:
        return finish_task_planning(
            task_id,
            worker_id,
            run_id,
            summary,
            plan_summary=plan_summary,
            result_payload=result_payload,
            checklist_items=checklist_items,
            next_action=next_action,
        )
    if artifact_paths:
        sync_artifacts_to_candidate(artifact_paths)
    raise TaskExecutionError("원격 planning 완료 API는 아직 없어 local mode에서만 planning 저장을 지원합니다.", artifact_paths or [])


def finish_upload_job_success_op(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths=None):
    if not REMOTE_MODE:
        return finish_upload_job_success(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths or [])
    synced_paths = sync_artifacts_to_candidate(artifact_paths or [])
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/upload-jobs/{upload_job_id}/finish-success",
        {"task_id": task_id, "worker_id": worker_id, "run_id": run_id, "summary": summary, "artifact_paths": synced_paths},
    ) or {}
    return payload.get("item")


def finish_upload_job_failure_op(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths=None):
    if not REMOTE_MODE:
        return finish_upload_job_failure(upload_job_id, task_id, worker_id, run_id, summary, artifact_paths or [])
    synced_paths = sync_artifacts_to_candidate(artifact_paths or [])
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/upload-jobs/{upload_job_id}/finish-failure",
        {"task_id": task_id, "worker_id": worker_id, "run_id": run_id, "summary": summary, "artifact_paths": synced_paths},
    ) or {}
    return payload.get("item")


def finish_post_upload_verify_success_op(task_id, worker_id, run_id, summary, artifact_paths=None):
    if not REMOTE_MODE:
        return finish_post_upload_verify_success(task_id, worker_id, run_id, summary, artifact_paths or [])
    synced_paths = sync_artifacts_to_candidate(artifact_paths or [])
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/tasks/{task_id}/finish-post-upload-verify-success",
        {"worker_id": worker_id, "run_id": run_id, "summary": summary, "artifact_paths": synced_paths},
    ) or {}
    return payload.get("item")


def finish_post_upload_verify_failure_op(task_id, worker_id, run_id, summary, artifact_paths=None, rollback_required=False):
    if not REMOTE_MODE:
        return finish_post_upload_verify_failure(task_id, worker_id, run_id, summary, artifact_paths or [], rollback_required=rollback_required)
    synced_paths = sync_artifacts_to_candidate(artifact_paths or [])
    payload = remote_json_request(
        "POST",
        f"/api/mobile-control/v2/worker/tasks/{task_id}/finish-post-upload-verify-failure",
        {
            "worker_id": worker_id,
            "run_id": run_id,
            "summary": summary,
            "artifact_paths": synced_paths,
            "rollback_required": bool(rollback_required),
        },
    ) or {}
    return payload.get("item")


def run_upload_job(task, upload_job, heartbeat):
    config = load_sftp_config()
    targets = extract_upload_targets(task)
    remote_root = resolve_remote_root(upload_job.get("target_env"), config)
    result_dir = OUTPUT_DIR / "mobile_control" / "upload_jobs"
    result_dir.mkdir(parents=True, exist_ok=True)
    log_path = result_dir / f"{task['id']}-{upload_job['id']}.upload.log"
    report_path = result_dir / f"{task['id']}-{upload_job['id']}.upload.md"
    heartbeat("UPLOADING", 30, "upload_prepare", "업로드 준비", f"업로드 대상 {len(targets)}개를 확인했습니다.")
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(UPLOAD_SCRIPT),
        "-RemoteHost",
        str(config.get("host") or ""),
        "-Username",
        str(config.get("username") or ""),
        "-RemoteRoot",
        remote_root,
        "-Port",
        str(config.get("port") or 22),
    ]
    key_path = str(config.get("privateKeyPath") or "").strip()
    if key_path:
        args.extend(["-SshKeyPath", key_path])
    args.extend(["-RelativePaths"])
    args.extend(targets)
    completed = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    log_parts = []
    if completed.stdout:
        log_parts.append(completed.stdout.rstrip())
    if completed.stderr:
        log_parts.append(completed.stderr.rstrip())
    log_path.write_text("\n\n".join(part for part in log_parts if part), encoding="utf-8")
    if completed.returncode != 0:
        raise TaskExecutionError(
            completed.stderr.strip() or completed.stdout.strip() or "업로드 실행 실패",
            [log_path.relative_to(BASE_DIR).as_posix()],
        )
    heartbeat("UPLOADING", 80, "upload_complete", "업로드 완료", f"업로드 대상 {len(targets)}개 전송을 마쳤습니다.")
    publish_result = refresh_mobile_control_link(heartbeat, task, upload_job, result_dir)
    report_lines = [
        "# 모바일 업로드 실행 결과",
        "",
        f"- 실행 시각: {now_label()}",
        f"- 대상 환경: {upload_job.get('target_env')}",
        f"- 원격 경로: {remote_root}",
        f"- 고정 링크 갱신: {publish_result.get('status') or 'unknown'}",
        "- 고정 HTML: http://43.202.209.122/static/mobile-control-link.html",
        "",
        "## 전송 파일",
    ]
    report_lines.extend([f"- `{path}`" for path in targets])
    if publish_result.get("mobile_control_url"):
        report_lines.extend([
            "",
            "## 최신 외부 링크",
            f"- `{publish_result.get('mobile_control_url')}`",
        ])
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return {
        "summary": f"업로드 실행 완료\n- 대상 환경: {upload_job.get('target_env')}\n- 전송 파일: {len(targets)}개\n- 고정 링크 갱신: {publish_result.get('status') or 'unknown'}",
        "artifacts": [
            report_path.relative_to(BASE_DIR).as_posix(),
            log_path.relative_to(BASE_DIR).as_posix(),
            publish_result["artifact_path"],
        ],
    }


def run_runtime_status_check():
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LOCAL_MOBILE_CONTROL_DIR / "get_mobile_runtime_status.ps1"),
        ],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise TaskExecutionError(completed.stderr.strip() or completed.stdout.strip() or "런타임 상태 확인 실패")
    try:
        return json.loads(completed.stdout or "{}")
    except Exception as exc:
        raise TaskExecutionError(f"런타임 상태 JSON 파싱 실패: {exc}") from exc


def refresh_mobile_control_link(heartbeat, task, upload_job, result_dir):
    if not REFRESH_LINK_SCRIPT.exists():
        raise TaskExecutionError("고정 링크 갱신 스크립트를 찾지 못했습니다.")
    runtime_status = run_runtime_status_check()
    tunnel_url = str(runtime_status.get("tunnel_url") or "").strip().rstrip("/")
    if not tunnel_url:
        raise TaskExecutionError("현재 tunnel_url이 없어 고정 링크를 갱신할 수 없습니다.")
    heartbeat("UPLOADING", 90, "publish_link", "고정 링크 갱신", "고정 HTML 주소를 최신 모바일 링크로 갱신합니다.")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REFRESH_LINK_SCRIPT),
        ],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    artifact_path = result_dir / f"{task['id']}-{upload_job['id']}.publish.json"
    if completed.returncode != 0:
        artifact_path.write_text(
            json.dumps(
                {
                    "checked_at": now_label(),
                    "status": "failed",
                    "tunnel_url": tunnel_url,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise TaskExecutionError(
            completed.stderr.strip() or completed.stdout.strip() or "고정 링크 갱신 실패",
            [artifact_path.relative_to(BASE_DIR).as_posix()],
        )
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception as exc:
        artifact_path.write_text(
            json.dumps(
                {
                    "checked_at": now_label(),
                    "status": "failed",
                    "tunnel_url": tunnel_url,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "error": f"JSON parse failed: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise TaskExecutionError(f"고정 링크 갱신 결과 파싱 실패: {exc}", [artifact_path.relative_to(BASE_DIR).as_posix()]) from exc
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if str(payload.get("status") or "").strip().lower() != "ok":
        raise TaskExecutionError(
            str(payload.get("error") or "고정 링크 갱신 실패"),
            [artifact_path.relative_to(BASE_DIR).as_posix()],
        )
    payload["artifact_path"] = artifact_path.relative_to(BASE_DIR).as_posix()
    return payload


def _scan_upload_log_errors(task):
    markers = ("traceback", "upload failed", "permission denied", "no such file", "fatal:")
    problems = []
    for artifact in task.get("artifacts") or []:
        rel_path = str(artifact.get("path") or "").strip()
        if artifact.get("kind") != "upload" or not rel_path.lower().endswith(".log"):
            continue
        target = BASE_DIR / rel_path
        if not target.exists() or not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        if any(marker in content for marker in markers):
            problems.append(rel_path)
    return problems


def run_post_upload_verify(task, heartbeat):
    result_dir = OUTPUT_DIR / "mobile_control" / "post_upload_verify"
    result_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    json_path = result_dir / f"{task['id']}-{stamp}.json"
    report_path = result_dir / f"{task['id']}-{stamp}.md"

    heartbeat("POST_UPLOAD_VERIFY", 92, "post_upload_verify", "업로드 후 검증", "업로드 이후 반영 상태를 확인합니다.")
    runtime_status = run_runtime_status_check()
    heartbeat("POST_UPLOAD_VERIFY", 95, "post_upload_verify_http", "페이지 점검", "주요 페이지와 API 응답을 확인합니다.")

    token = request_token()
    page_checks = []
    for label, path in [
        ("mobile-control", "/mobile-control"),
        ("dashboard", "/dashboard"),
        ("state-api", "/api/mobile-control/v2/state?limit=1"),
    ]:
        status, _body = fetch_page(path, token)
        page_checks.append({"label": label, "path": path, "status": status, "ok": 200 <= status < 400})

    upload_log_problems = _scan_upload_log_errors(task)
    latest_upload_status = str(task.get("latest_upload_job_status") or "").strip().upper()
    permission_ok = str(task.get("created_by") or "").strip() == "bibaram1"

    checks = [
        {"key": "upload_job", "label": "업로드 잡 완료", "ok": latest_upload_status == "DONE", "detail": f"최근 업로드 잡 상태: {latest_upload_status or '없음'}"},
        {"key": "app_running", "label": "앱 프로세스", "ok": bool(runtime_status.get("app_running")), "detail": f"app_running={bool(runtime_status.get('app_running'))}"},
        {"key": "mysql_running", "label": "DB 프로세스", "ok": bool(runtime_status.get("mysql_running")), "detail": f"mysql_running={bool(runtime_status.get('mysql_running'))}"},
        {"key": "permission_rule", "label": "권한 규칙", "ok": permission_ok, "detail": "bibaram1 전용 규칙 확인" if permission_ok else "생성자 권한 규칙을 다시 확인해야 합니다."},
        {"key": "upload_logs", "label": "최근 업로드 로그", "ok": not upload_log_problems, "detail": "오류 패턴 없음" if not upload_log_problems else f"오류 패턴 감지: {', '.join(upload_log_problems)}"},
    ]
    checks.extend(
        {
            "key": f"page_{item['label']}",
            "label": f"{item['label']} 응답",
            "ok": item["ok"],
            "detail": f"{item['path']} -> {item['status']}",
        }
        for item in page_checks
    )

    passed = all(item["ok"] for item in checks)
    failed_items = [item for item in checks if not item["ok"]]
    rollback_required = any(item["key"] in {"app_running", "mysql_running", "page_mobile-control", "page_dashboard", "page_state-api", "upload_logs"} for item in failed_items)
    summary_lines = ["업로드 후 검증 통과" if passed else "업로드 후 검증 실패"]
    summary_lines.extend(f"- {item['label']}: {item['detail']}" for item in failed_items[:5] or checks[:3])

    payload = {
        "checked_at": now_label(),
        "task_id": task["id"],
        "latest_upload_job_status": latest_upload_status,
        "passed": passed,
        "rollback_required": rollback_required,
        "runtime_status": runtime_status,
        "page_checks": page_checks,
        "checks": checks,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# 모바일 업로드 후 검증",
        "",
        f"- 작업 ID: {task['id']}",
        f"- 점검 시각: {payload['checked_at']}",
        f"- 결과: {'통과' if passed else '실패'}",
        f"- 롤백 검토 필요: {'예' if rollback_required else '아니오'}",
        "",
        "## 점검 항목",
    ]
    report_lines.extend([f"- [{'OK' if item['ok'] else 'FAIL'}] {item['label']}: {item['detail']}" for item in checks])
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "passed": passed,
        "rollback_required": rollback_required,
        "summary": "\n".join(summary_lines),
        "artifacts": [
            report_path.relative_to(BASE_DIR).as_posix(),
            json_path.relative_to(BASE_DIR).as_posix(),
        ],
    }


def request_token():
    if not DEFAULT_LOGIN_ID or not DEFAULT_PASSWORD:
        raise RuntimeError("MOBILE_CONTROL_LOGIN_ID / MOBILE_CONTROL_LOGIN_PASSWORD 환경변수가 필요합니다.")
    payload = urllib.parse.urlencode({"username": DEFAULT_LOGIN_ID, "password": DEFAULT_PASSWORD}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/auth/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["access_token"]


def fetch_page(path, token=None):
    headers = {}
    if token:
        headers["Cookie"] = f"access_token=Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def run_health_check():
    token = request_token()
    targets = [
        ("login", "/login", None),
        ("dashboard", "/dashboard", token),
        ("stats", "/stats", token),
        ("view", "/view/17701", token),
        ("mobile-control", "/mobile-control", token),
    ]
    rows = []
    for label, path, auth_token in targets:
        status, body = fetch_page(path, auth_token)
        rows.append(
            {
                "label": label,
                "path": path,
                "status": status,
                "ok": 200 <= status < 400,
                "has_login_form": 'name="username"' in body,
            }
        )
    out_path = OUTPUT_DIR / "mobile_control" / "health-check-latest.json"
    out_path.write_text(json.dumps({"checked_at": now_label(), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": "濡쒖뺄 ?곹깭 ?먭? ?꾨즺\n" + "\n".join(f"- {row['label']}: {row['status']}" for row in rows),
        "artifacts": [out_path.relative_to(BASE_DIR).as_posix()],
    }


def run_capture_latest():
    completed = subprocess.run(
        [
            "node",
            str(CAPTURE_SCRIPT),
            "--base-url",
            BASE_URL,
            "--username",
            DEFAULT_LOGIN_ID,
            "--password",
            DEFAULT_PASSWORD,
        ],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "?ㅽ겕由곗꺑 ?앹꽦 ?ㅽ뙣")
    payload = json.loads(completed.stdout or "{}")
    shots = payload.get("shots") or []
    out_path = OUTPUT_DIR / "mobile_control" / "capture-latest.json"
    out_path.write_text(json.dumps({"created_at": now_label(), "shots": shots}, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = [out_path.relative_to(BASE_DIR).as_posix()]
    artifacts.extend([shot.get("file") for shot in shots if shot.get("file")])
    return {
        "summary": "理쒖떊 ?붾㈃ ?ㅽ겕由곗꺑 ?앹꽦 ?꾨즺\n" + "\n".join(f"- {shot.get('name')}: {shot.get('file')}" for shot in shots),
        "artifacts": artifacts,
    }


def run_prepare_upload_summary():
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        ).stdout.strip()
    except Exception:
        branch = ""
    try:
        status_lines = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        ).stdout.splitlines()
    except Exception:
        status_lines = []
    out_path = OUTPUT_DIR / "mobile_control" / "upload-ready-summary.md"
    body = [
        "# ?낅줈??以鍮??붿빟",
        "",
        f"- ?앹꽦 ?쒓컖: {now_label()}",
        f"- 釉뚮옖移? {branch or '(?뺤씤 遺덇?)'}",
        "",
        "## 蹂寃??뚯씪",
    ]
    body.extend([f"- `{line}`" for line in status_lines[:60]] or ["- 蹂寃??뚯씪 ?놁쓬"])
    out_path.write_text("\n".join(body), encoding="utf-8")
    return {
        "summary": "?낅줈??以鍮??붿빟 ?앹꽦 ?꾨즺",
        "artifacts": [out_path.relative_to(BASE_DIR).as_posix()],
    }


def run_codex_command(task_id, text, heartbeat):
    result_dir = OUTPUT_DIR / "mobile_control" / "codex_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    output_file = result_dir / f"{task_id}.md"
    stdout_file = result_dir / f"{task_id}.stdout.log"
    stderr_file = result_dir / f"{task_id}.stderr.log"
    prompt = (
        "d:\\dev\\chang_admin 프로젝트에서 작업한다. 기본 응답은 한국어로 하고, 관련 없는 파일은 수정하지 말고 최소 수정만 한다.\n\n"
        f"사용자 지시\n{text}"
    )
    with stdout_file.open("w", encoding="utf-8") as stdout_handle, stderr_file.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            ["codex", "exec", "-s", "workspace-write", "-C", str(BASE_DIR), "-o", str(output_file), prompt],
            cwd=str(BASE_DIR),
            env=codex_subprocess_env(),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        started = time.monotonic()
        next_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_heartbeat:
                heartbeat("RUNNING", 45, "codex_exec", "Codex 실행", f"Codex가 작업 중입니다. 경과 {int(now - started)}초")
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if now - started > CODEX_TIMEOUT_SECONDS:
                process.kill()
                raise RuntimeError("Codex 실행 시간이 제한을 초과했습니다.")
            time.sleep(1)
    if process.returncode != 0:
        error_text = stderr_file.read_text(encoding="utf-8", errors="replace").strip()
        artifacts = []
        if output_file.exists() and output_file.stat().st_size:
            artifacts.append(output_file.relative_to(BASE_DIR).as_posix())
        if stdout_file.exists() and stdout_file.stat().st_size:
            artifacts.append(stdout_file.relative_to(BASE_DIR).as_posix())
        if stderr_file.exists() and stderr_file.stat().st_size:
            artifacts.append(stderr_file.relative_to(BASE_DIR).as_posix())
        raise TaskExecutionError(error_text or "Codex 실행 실패", artifacts)
    message = output_file.read_text(encoding="utf-8", errors="replace").strip() if output_file.exists() else ""
    if not message:
        message = "Codex 실행은 끝났지만 결과 메시지를 읽지 못했습니다."
    if len(message) > 4500:
        message = message[:4300].rstrip() + f"\n\n(전체 결과: {output_file.relative_to(BASE_DIR).as_posix()})"
    artifacts = [output_file.relative_to(BASE_DIR).as_posix()]
    if stdout_file.exists() and stdout_file.stat().st_size:
        artifacts.append(stdout_file.relative_to(BASE_DIR).as_posix())
    if stderr_file.exists() and stderr_file.stat().st_size:
        artifacts.append(stderr_file.relative_to(BASE_DIR).as_posix())
    return {"summary": message, "artifacts": artifacts}


TASK_MAP = {
    "health_check": run_health_check,
    "capture_latest": run_capture_latest,
    "prepare_upload_summary": run_prepare_upload_summary,
}


def process_one(task):
    task_id = task["id"]
    task_key = task.get("task_key") or ""
    run_id = task.get("current_run_id") or ""

    def heartbeat(state, progress, code, label, summary):
        record_worker_heartbeat_op(
            WORKER_ID,
            state,
            task_id=task_id,
            run_id=run_id,
            progress_percent=progress,
            current_step_code=code,
            current_step_label=label,
            summary=summary,
            task_status=state,
        )

    ensure_task_checklist_op(task_id, actor=WORKER_ID)
    heartbeat("PLANNING", 5, "planning", "계획 수립", "작업 계획과 체크리스트를 준비합니다.")
    time.sleep(0.2)
    heartbeat("CHECKLIST_ISSUED", 10, "checklist_issued", "체크리스트 발행", "기본 체크리스트를 발행했습니다.")
    time.sleep(0.2)
    heartbeat("RUNNING", 15, "running", "실행 시작", "워커가 작업을 시작합니다.")
    try:
        if task_key:
            runner = TASK_MAP.get(task_key)
            if not runner:
                raise RuntimeError("지원하지 않는 자동 작업입니다.")
            result = runner()
        else:
            result = run_codex_command(task_id, task["text"], heartbeat)
        finish_task_success_op(task_id, WORKER_ID, run_id, result.get("summary") or "", result.get("artifacts") or [])
    except Exception as exc:
        failure_artifacts = getattr(exc, "artifacts", None) or []
        finish_task_failure_op(task_id, WORKER_ID, run_id, str(exc), failure_artifacts)


def process_upload_job(upload_job):
    task_id = upload_job["task_id"]
    run_id = upload_job.get("run_id") or ""
    task_details = upload_job.get("_task_detail") or get_task_op(task_id) or {}
    task_payload = {**task_details, **upload_job}

    def heartbeat(state, progress, code, label, summary):
        record_worker_heartbeat_op(
            WORKER_ID,
            state,
            task_id=task_id,
            run_id=run_id,
            progress_percent=progress,
            current_step_code=code,
            current_step_label=label,
            summary=summary,
            task_status=state,
        )

    heartbeat("UPLOADING", 10, "uploading", "?낅줈???ㅽ뻾", "?쒕쾭 ?낅줈?쒕? ?쒖옉?⑸땲??")
    try:
        result = run_upload_job(task_payload, upload_job, heartbeat)
        finish_upload_job_success_op(upload_job["id"], task_id, WORKER_ID, run_id, result.get("summary") or "", result.get("artifacts") or [])
    except Exception as exc:
        failure_artifacts = getattr(exc, "artifacts", None) or []
        finish_upload_job_failure_op(upload_job["id"], task_id, WORKER_ID, run_id, str(exc), failure_artifacts)


def _extract_json_payload(raw_text):
    if not raw_text:
        return None
    fenced = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw_text, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw_text.strip()
    try:
        return json.loads(candidate)
    except Exception:
        matches = re.findall(r"(\{[\s\S]*\})", raw_text)
        for item in reversed(matches):
            try:
                return json.loads(item)
            except Exception:
                continue
    return None


def _resolve_input_image_path(path_value):
    raw_path = str(path_value or "").strip().replace("\\", "/")
    if not raw_path:
        return None
    candidates = []
    if raw_path.startswith("output/"):
        candidates.append(BASE_DIR / raw_path)
        candidates.append(BASE_DIR / raw_path[len("output/"):].lstrip("/"))
    else:
        candidates.append(OUTPUT_DIR / raw_path)
        candidates.append(BASE_DIR / raw_path)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _task_attachment_items(task):
    payload = task.get("result_payload") or {}
    if not payload:
        raw_payload = task.get("result_payload_json")
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except Exception:
                payload = {}
    attachments = payload.get("attachments") or []
    if attachments:
        return attachments
    artifacts = task.get("artifacts") or []
    return [
        {
            "kind": str(item.get("kind") or "").strip() or "input_image",
            "label": str(item.get("label") or item.get("name") or "").strip() or Path(str(item.get("path") or "")).name,
            "path": str(item.get("path") or "").strip(),
            "name": Path(str(item.get("path") or "")).name,
        }
        for item in artifacts
        if str(item.get("kind") or "").strip() in {"input_image", "input_file"} and str(item.get("path") or "").strip()
    ]


def _task_input_images(task):
    attachments = _task_attachment_items(task)
    items = []
    for item in attachments:
        if str(item.get("kind") or "").strip() != "input_image":
            continue
        resolved = _resolve_input_image_path(item.get("path"))
        if not resolved:
            continue
        items.append(
            {
                "label": str(item.get("label") or item.get("name") or resolved.name).strip() or resolved.name,
                "resolved_path": resolved,
            }
        )
    return items


def _task_reference_files(task):
    attachments = _task_attachment_items(task)
    notes = []
    for item in attachments:
        if str(item.get("kind") or "").strip() != "input_file":
            continue
        raw_path = str(item.get("path") or "").strip()
        resolved = _resolve_input_image_path(raw_path)
        note = f"- {str(item.get('label') or item.get('name') or Path(raw_path).name).strip()} ({raw_path})"
        if resolved and resolved.suffix.lower() in {".txt", ".md", ".json", ".log"}:
            try:
                excerpt = resolved.read_text(encoding="utf-8", errors="replace")[:1200].strip()
            except Exception:
                excerpt = ""
            if excerpt:
                note += f"\n  미리보기: {excerpt}"
        notes.append(note)
    return notes


def _task_effective_instruction(task):
    original_instruction = str(
        task.get("text")
        or task.get("original_instruction")
        or task.get("user_instruction")
        or ""
    ).strip()
    followup_bundle = task.get("followup_bundle") or {}
    followup_instruction = str(followup_bundle.get("instruction") or "").strip()
    if not followup_instruction:
        return original_instruction
    if not original_instruction:
        return followup_instruction
    return (
        f"{original_instruction}\n\n"
        "후속 지시 및 변경 요청\n"
        f"{followup_instruction}"
    )


PLANNING_INSPECTION_KEYWORDS = (
    "smoke",
    "check",
    "health check",
    "health-check",
    "inspection",
    "inspect",
    "review",
    "verify",
    "검토",
    "점검",
    "확인",
    "상태 확인",
    "헬스 체크",
)


def codex_subprocess_env():
    env = os.environ.copy()
    env.setdefault("CODEX_HOME", str(CODEX_RUNTIME_HOME))
    CODEX_RUNTIME_HOME.mkdir(parents=True, exist_ok=True)
    return env

PLANNING_CHANGE_KEYWORDS = (
    "수정",
    "구현",
    "추가",
    "리팩터링",
    "배포",
    "업로드",
    "변경",
    "패치",
    "고쳐",
    "fix",
    "implement",
    "modify",
    "refactor",
    "deploy",
    "upload",
)

PLANNING_PRIMARY_TARGETS = [
    "scripts/mobile_control_worker.py",
    "services/mobile_control_service.py",
    "routers/mobile_control_v2_router.py",
    "templates/mobile_control_v2.html",
    "static/js/mobile_control_v2.js",
    "mobile_control_local/",
]

PLANNING_DEFAULT_EXCLUDES = [
    "main.py",
    "routers/dashboard*.py",
    "routers/stats*.py",
    "routers/view*.py",
    "templates/dashboard*.html",
    "templates/stats*.html",
    "templates/view*.html",
    "static/js/dashboard*.js",
    "static/js/stats*.js",
    "static/js/view*.js",
    "cloudflared",
    "publish_mobile_control_link.ps1",
    "refresh_mobile_control_link.ps1",
    "watchdog",
]


def _matches_any_keyword(text, keywords):
    blob = str(text or "").lower()
    return any(str(keyword or "").lower() in blob for keyword in (keywords or []))


def _build_scope_guard_notes(scope):
    primary_targets = scope.get("primary_targets") or []
    excluded_targets = scope.get("excluded_targets") or []
    guard_lines = [
        f"- 작업 성격: {scope.get('mode_label') or scope.get('mode') or 'general'}",
        f"- local-only first: {'yes' if scope.get('local_only_first') else 'no'}",
    ]
    if primary_targets:
        guard_lines.append("- 1차 후보:")
        guard_lines.extend(f"  - {item}" for item in primary_targets)
    if excluded_targets:
        guard_lines.append("- 기본 제외:")
        guard_lines.extend(f"  - {item}" for item in excluded_targets)
    if scope.get("inspection_first_note"):
        guard_lines.append(f"- inspection 우선 원칙: {scope['inspection_first_note']}")
    return "\n".join(guard_lines)


def _classify_planning_scope(task, text):
    instruction = str(text or "").strip()
    task_key = str(task.get("task_key") or "").strip().lower()
    inspection = _matches_any_keyword(instruction, PLANNING_INSPECTION_KEYWORDS) or task_key in {"health_check", "capture_latest"}
    explicit_change = _matches_any_keyword(instruction, PLANNING_CHANGE_KEYWORDS)
    is_inspection = inspection and not explicit_change
    return {
        "mode": "inspection" if is_inspection else "change",
        "mode_label": "inspection/read-first" if is_inspection else "change/minimal-edit",
        "local_only_first": bool(is_inspection),
        "primary_targets": list(PLANNING_PRIMARY_TARGETS),
        "excluded_targets": list(PLANNING_DEFAULT_EXCLUDES),
        "inspection_first_note": (
            "수정보다 읽기/검토/재현/상태 확인 계획을 먼저 만들고, 꼭 필요할 때만 최소 수정 계획을 추가한다."
            if is_inspection
            else "명시적 수정 지시가 있는 경우에만 최소 수정 계획을 포함한다."
        ),
    }


def _build_codex_prompt(text, image_labels=None, file_notes=None):
    labels = [str(label or "").strip() for label in (image_labels or []) if str(label or "").strip()]
    image_block = ""
    if labels:
        image_block = "\n\n첨부 이미지 참고\n" + "\n".join(f"- {label}" for label in labels) + "\n이미지가 보이면 상태, 레이아웃, 오류 문구를 함께 참고한다."
    notes = [str(note or "").strip() for note in (file_notes or []) if str(note or "").strip()]
    file_block = ""
    if notes:
        file_block = "\n\n첨부 파일 참고\n" + "\n".join(notes) + "\n텍스트성 첨부는 planning과 실행 판단에 함께 참고한다."
    return (
        "d:\\dev\\chang_admin 프로젝트에서 작업한다. 기본 응답은 한국어로 한다. "
        "내부 추론 전체를 드러내지 말고, 사람이 검수 가능한 수준의 계획/판단 근거 요약만 제공한다. "
        "관련 없는 파일은 수정하지 말고 최소 수정만 한다. 서버 업로드는 하지 않는다.\n\n"
        "최종 출력은 JSON 하나만 반환한다. JSON 외 설명은 추가하지 않는다.\n"
        "필수 키:\n"
        "- latest_summary\n"
        "- plan_summary { goal, target_files[], impact_scope, verification_plan[], risk_points[] }\n"
        "- result_list [{ path, change_type, summary }]\n"
        "- implemented_features[]\n"
        "- self_review { affected_files[], affected_modules[], side_effects, regression_risks[], verification_summary }\n"
        "- checklist_items [{ section, title, description, status }]\n"
        "- next_action\n"
        "- final_decision\n\n"
        f"사용자 지시\n{text}{image_block}{file_block}"
    )


def _build_planning_codex_prompt(text, scope, image_labels=None, file_notes=None):
    labels = [str(label or "").strip() for label in (image_labels or []) if str(label or "").strip()]
    image_block = ""
    if labels:
        image_block = "\n\n첨부 이미지 참고\n" + "\n".join(f"- {label}" for label in labels) + "\n계획 수립 시 첨부 이미지의 상태, 구조, 오류 문구를 함께 참고한다."
    notes = [str(note or "").strip() for note in (file_notes or []) if str(note or "").strip()]
    file_block = ""
    if notes:
        file_block = "\n\n첨부 파일 참고\n" + "\n".join(notes) + "\n텍스트성 첨부는 계획 수립 시 우선 참고한다."
    scope_block = _build_scope_guard_notes(scope)
    return (
        "d:\\dev\\chang_admin 프로젝트에서 planning phase만 수행한다. 기본 응답은 한국어로 한다. "
        "코드 수정, 배포, 업로드, 검증 실행은 하지 말고 작업 계획만 구조화한다.\n\n"
        "범위 가드:\n"
        f"{scope_block}\n\n"
        "반드시 mobile-control 관련 파일을 1차 후보로 두고, dashboard/stats/view/main.py/cloudflared/publish/watchdog 계열은 기본 제외로 취급한다.\n"
        "inspection/read-first 성격이면 수정 없는 검토 계획 또는 최소 수정 계획을 우선 제안하고, 명시적 수정/구현 지시가 있을 때만 수정 계획을 넓힌다.\n\n"
        "최종 출력은 JSON 하나만 반환한다. JSON 외 설명은 추가하지 않는다.\n"
        "필수 키:\n"
        "- latest_summary\n"
        "- plan_summary { goal, target_files[], impact_scope, verification_plan[], risk_points[] }\n"
        "- checklist_items [{ section, title, description, status }]\n"
        "- next_action\n\n"
        f"사용자 지시\n{text}{image_block}{file_block}"
    )


def _fallback_codex_payload(text, message, changed_files):
    instruction = str(text or "").strip()
    first_line = instruction.splitlines()[0].strip() if instruction else "모바일 지시 작업"
    return {
        "latest_summary": message[:3000].strip(),
        "plan_summary": {
            "goal": first_line,
            "target_files": changed_files,
            "impact_scope": "요청 범위 기준 최소 수정",
            "verification_plan": ["관련 파일 검토", "연관 화면 또는 기능 확인"],
            "risk_points": ["작업 범위 밖 파일 변경 금지", "추가 영향 여부 확인 필요"],
        },
        "result_list": [{"path": path, "change_type": "modify", "summary": "변경 반영"} for path in changed_files],
        "implemented_features": [first_line],
        "self_review": {
            "affected_files": changed_files,
            "affected_modules": changed_files,
            "side_effects": "요청 범위 내 파일만 수정하도록 제한했습니다.",
            "regression_risks": ["관련 화면 동작 확인 필요"],
            "verification_summary": "산출물 로그와 화면 동작을 함께 검토해 주세요.",
        },
        "checklist_items": [
            {"section": "INPUT", "title": "입력 확인", "description": "지시문과 작업 범위가 맞는지 확인", "status": "PENDING"},
            {"section": "PLAN", "title": "계획 확인", "description": "영향 범위와 검증 계획 확인", "status": "PENDING"},
            {"section": "EXECUTION", "title": "실행 확인", "description": "변경 파일과 핵심 수정 내용 확인", "status": "PENDING"},
            {"section": "VERIFICATION", "title": "검증 확인", "description": "실행 및 검증 결과 확인", "status": "PENDING"},
            {"section": "UPLOAD", "title": "업로드 준비", "description": "업로드 전 확인 조건 점검", "status": "PENDING"},
        ],
        "next_action": "결과와 체크리스트를 검토해 주세요.",
        "final_decision": "",
    }


def _fallback_planning_payload(text, message, scope):
    instruction = str(text or "").strip()
    first_line = instruction.splitlines()[0].strip() if instruction else "모바일 작업 계획"
    primary_targets = scope.get("primary_targets") or []
    excluded_targets = scope.get("excluded_targets") or []
    local_only_first = bool(scope.get("local_only_first"))
    verification_plan = ["계획과 체크리스트를 검토합니다."]
    if local_only_first:
        verification_plan.insert(0, "local 환경에서 읽기/상태 확인 중심으로 먼저 점검합니다.")
    checklist_items = [
        {
            "section": "INPUT",
            "title": "최초 지시 확인",
            "description": "사용자 첫 지시와 첨부 자료가 planning 범위와 맞는지 확인합니다.",
            "status": "PENDING",
        },
        {
            "section": "PLAN",
            "title": "계획 요약 확인",
            "description": f"목표와 영향 범위가 '{first_line}' 요청에 맞는지 확인합니다.",
            "status": "PENDING",
        },
        {
            "section": "EXECUTION",
            "title": "수정 후보 확인",
            "description": "수정 또는 점검 대상 파일 범위가 mobile-control 관련 파일로 좁혀졌는지 확인합니다.",
            "status": "PENDING",
        },
        {
            "section": "VERIFICATION",
            "title": "검증 계획 확인",
            "description": verification_plan[0],
            "status": "PENDING",
        },
        {
            "section": "UPLOAD",
            "title": "후속 단계 확인",
            "description": "계획 승인 전에는 업로드나 배포로 넘어가지 않는지 확인합니다.",
            "status": "PENDING",
        },
    ]
    risk_points = ["관련 없는 파일 수정 금지", "실행 전 승인 필요"]
    if excluded_targets:
        risk_points.append("dashboard/stats/view/main.py/cloudflared/publish/watchdog 계열은 기본 제외합니다.")
    return {
        "latest_summary": message[:3000].strip() or "작업 계획 초안을 생성했습니다.",
        "plan_summary": {
            "goal": first_line,
            "target_files": primary_targets,
            "impact_scope": "mobile-control 관련 파일만 1차 후보로 제한해 사용자 첫 지시 기준으로 범위를 정리합니다.",
            "verification_plan": verification_plan,
            "risk_points": risk_points,
        },
        "checklist_items": checklist_items,
        "next_action": "계획과 체크리스트를 확인한 뒤 진행 여부를 결정하세요." if local_only_first else "계획과 체크리스트를 확인한 뒤 진행을 누르세요.",
    }


def _task_model_profile(task):
    requested = str(task.get("model_profile") or "").strip()
    return requested or CODEX_PROFILE


def _task_model_name(task):
    return str(task.get("model_name") or "").strip()


def _task_reasoning_effort(task):
    effort = str(task.get("reasoning_effort") or "").strip().lower()
    return effort if effort in {"low", "medium", "high", "xhigh"} else ""


_RESOLVED_CODEX_EXECUTABLE = ""


def _resolve_codex_executable():
    global _RESOLVED_CODEX_EXECUTABLE
    if _RESOLVED_CODEX_EXECUTABLE:
        return _RESOLVED_CODEX_EXECUTABLE

    candidates = []
    env_path = str(os.environ.get("MOBILE_CONTROL_CODEX_PATH") or "").strip()
    if env_path:
        candidates.append(Path(env_path))

    for name in ("codex", "codex.exe"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))

    home_dir = Path.home()
    extension_roots = [
        home_dir / ".vscode" / "extensions",
        home_dir / ".vscode-insiders" / "extensions",
    ]
    for root in extension_roots:
        if root.exists():
            candidates.extend(sorted(root.glob("openai.chatgpt-*-win32-x64/bin/windows-x86_64/codex.exe"), reverse=True))

    for candidate in candidates:
        resolved = Path(candidate).expanduser()
        if resolved.exists() and resolved.is_file():
            _RESOLVED_CODEX_EXECUTABLE = str(resolved)
            return _RESOLVED_CODEX_EXECUTABLE

    raise FileNotFoundError("codex 실행 파일을 찾지 못했습니다. PATH 또는 MOBILE_CONTROL_CODEX_PATH를 확인해 주세요.")


def _build_codex_exec_command(prompt, image_paths, output_file, model_profile, model_name="", reasoning_effort=""):
    # `-i/--image` is variadic, so keep the prompt immediately after `exec`.
    # If the prompt is placed after image flags, Codex can treat it as another
    # image path and then fall back to reading stdin, which breaks task runs.
    command = [_resolve_codex_executable(), "-p", str(model_profile or CODEX_PROFILE), "exec"]
    if model_name:
        command.extend(["-m", str(model_name)])
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.extend([str(prompt or ""), "-C", str(BASE_DIR), "-o", str(output_file)])
    for image_path in image_paths:
        command.extend(["-i", str(image_path)])
    return command


def run_codex_command(task_id, task, heartbeat):
    result_dir = OUTPUT_DIR / "mobile_control" / "codex_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    output_file = result_dir / f"{task_id}.md"
    stdout_file = result_dir / f"{task_id}.stdout.log"
    stderr_file = result_dir / f"{task_id}.stderr.log"
    input_images = _task_input_images(task)
    reference_files = _task_reference_files(task)
    model_profile = _task_model_profile(task)
    model_name = _task_model_name(task)
    reasoning_effort = _task_reasoning_effort(task)
    task_instruction = _task_effective_instruction(task)
    prompt = _build_codex_prompt(task_instruction, [item["label"] for item in input_images], reference_files)
    try:
        codex_command = _build_codex_exec_command(
            prompt,
            [item["resolved_path"] for item in input_images],
            output_file,
            model_profile,
            model_name=model_name,
            reasoning_effort=reasoning_effort,
        )
    except FileNotFoundError as exc:
        raise TaskExecutionError(str(exc), []) from exc

    command = codex_command

    with stdout_file.open("w", encoding="utf-8") as stdout_handle, stderr_file.open("w", encoding="utf-8") as stderr_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                env=codex_subprocess_env(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise TaskExecutionError("codex 실행 파일을 시작하지 못했습니다. 경로 설정을 확인해 주세요.", []) from exc
        started = time.monotonic()
        next_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_heartbeat:
                image_hint = f" / 첨부 이미지 {len(input_images)}장 참고 중" if input_images else ""
                profile_hint = f" / 프로필 {model_profile}" if model_profile else ""
                model_hint = f" / 모델 {model_name}" if model_name else ""
                effort_hint = f" / 성능 {reasoning_effort}" if reasoning_effort else ""
                heartbeat("RUNNING", 45, "codex_exec", "Codex 실행", f"Codex가 작업 중입니다. 경과 {int(now - started)}초{image_hint}{profile_hint}{model_hint}{effort_hint}")
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if now - started > CODEX_TIMEOUT_SECONDS:
                process.kill()
                raise RuntimeError("Codex 실행 시간이 제한을 초과했습니다.")
            time.sleep(1)
    heartbeat("SELF_REVIEW", 72, "collect_output", "결과 수집", "Codex 출력과 로그 파일을 수집하고 있습니다.")
    output_text = output_file.read_text(encoding="utf-8", errors="replace").strip() if output_file.exists() else ""
    artifacts = []
    if output_file.exists() and output_file.stat().st_size:
        artifacts.append(output_file.relative_to(BASE_DIR).as_posix())
    if stdout_file.exists() and stdout_file.stat().st_size:
        artifacts.append(stdout_file.relative_to(BASE_DIR).as_posix())
    if stderr_file.exists() and stderr_file.stat().st_size:
        artifacts.append(stderr_file.relative_to(BASE_DIR).as_posix())
    if process.returncode != 0:
        error_text = stderr_file.read_text(encoding="utf-8", errors="replace").strip()
        raise TaskExecutionError(error_text or "Codex 실행 실패", artifacts)
    heartbeat("SELF_REVIEW", 84, "parse_result", "결과 정리", "결과 요약, 변경 파일, 체크리스트를 정리하고 있습니다.")
    changed_files = get_changed_paths()
    payload = _extract_json_payload(output_text) or _fallback_codex_payload(
        task_instruction,
        output_text or "Codex 실행 결과가 비어 있습니다.",
        changed_files,
    )
    existing_attachments = (task.get("result_payload") or {}).get("attachments") or []
    result_payload = {
        "original_instruction": str(task.get("text") or "").strip(),
        "effective_instruction": task_instruction,
        "attachments": [
            {
                "kind": str(item.get("kind") or "").strip() or "input_image",
                "label": str(item.get("label") or item.get("name") or "").strip(),
                "path": str(item.get("path") or "").strip(),
                "name": Path(str(item.get("path") or "")).name,
            }
            for item in existing_attachments
        ],
        "changed_files": changed_files,
        "implemented_features": payload.get("implemented_features") or [],
        "result_list": payload.get("result_list") or [
            {"path": path, "change_type": "modify", "summary": "변경 반영"} for path in changed_files
        ],
        "checklist_items": payload.get("checklist_items") or [],
        "latest_summary": str(payload.get("latest_summary") or output_text or "").strip(),
    }
    heartbeat("SELF_REVIEW", 92, "prepare_review", "검수 준비", "모바일에서 바로 검수할 결과와 체크리스트를 준비했습니다.")
    return {
        "summary": str(payload.get("latest_summary") or output_text or "").strip(),
        "artifacts": artifacts,
        "plan_summary": payload.get("plan_summary") or {},
        "result_payload": result_payload,
        "self_review": payload.get("self_review") or {},
        "checklist_items": payload.get("checklist_items") or [],
        "next_action": str(payload.get("next_action") or "결과와 체크리스트를 검토해 주세요.").strip(),
        "final_decision": str(payload.get("final_decision") or "").strip(),
    }


def run_codex_planning(task_id, task, heartbeat):
    result_dir = OUTPUT_DIR / "mobile_control" / "codex_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    output_file = result_dir / f"{task_id}.planning.md"
    stdout_file = result_dir / f"{task_id}.planning.stdout.log"
    stderr_file = result_dir / f"{task_id}.planning.stderr.log"
    input_images = _task_input_images(task)
    attachment_items = _task_attachment_items(task)
    reference_files = _task_reference_files(task)
    model_profile = _task_model_profile(task)
    model_name = _task_model_name(task)
    reasoning_effort = _task_reasoning_effort(task)
    task_instruction = _task_effective_instruction(task)
    planning_scope = _classify_planning_scope(task, task_instruction)
    prompt = _build_planning_codex_prompt(task_instruction, planning_scope, [item["label"] for item in input_images], reference_files)
    try:
        codex_command = _build_codex_exec_command(
            prompt,
            [item["resolved_path"] for item in input_images],
            output_file,
            model_profile,
            model_name=model_name,
            reasoning_effort=reasoning_effort,
        )
    except FileNotFoundError as exc:
        raise TaskExecutionError(str(exc), []) from exc

    with stdout_file.open("w", encoding="utf-8") as stdout_handle, stderr_file.open("w", encoding="utf-8") as stderr_handle:
        try:
            process = subprocess.Popen(
                codex_command,
                cwd=str(BASE_DIR),
                env=codex_subprocess_env(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise TaskExecutionError("codex 실행 파일을 시작하지 못했습니다. 경로 설정을 확인해 주세요.", []) from exc
        started = time.monotonic()
        next_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_heartbeat:
                image_hint = f" / 첨부 이미지 {len(input_images)}장 참고 중" if input_images else ""
                profile_hint = f" / 프로필 {model_profile}" if model_profile else ""
                model_hint = f" / 모델 {model_name}" if model_name else ""
                effort_hint = f" / 성능 {reasoning_effort}" if reasoning_effort else ""
                heartbeat("PLANNING", 45, "codex_planning", "계획 생성", f"Codex가 작업 계획을 정리 중입니다. 경과 {int(now - started)}초{image_hint}{profile_hint}{model_hint}{effort_hint}")
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if now - started > CODEX_TIMEOUT_SECONDS:
                process.kill()
                raise RuntimeError("Codex planning 실행 시간이 제한을 초과했습니다.")
            time.sleep(1)

    output_text = output_file.read_text(encoding="utf-8", errors="replace").strip() if output_file.exists() else ""
    artifacts = []
    if output_file.exists() and output_file.stat().st_size:
        artifacts.append(output_file.relative_to(BASE_DIR).as_posix())
    if stdout_file.exists() and stdout_file.stat().st_size:
        artifacts.append(stdout_file.relative_to(BASE_DIR).as_posix())
    if stderr_file.exists() and stderr_file.stat().st_size:
        artifacts.append(stderr_file.relative_to(BASE_DIR).as_posix())
    if process.returncode != 0:
        error_text = stderr_file.read_text(encoding="utf-8", errors="replace").strip()
        raise TaskExecutionError(error_text or "Codex planning 실행 실패", artifacts)

    payload = _extract_json_payload(output_text) or _fallback_planning_payload(
        task_instruction,
        output_text or "Codex planning 결과가 비어 있습니다.",
        planning_scope,
    )
    planning_checklist_items = payload.get("checklist_items") or _fallback_planning_payload(
        task_instruction,
        output_text or "Codex planning 결과가 비어 있습니다.",
        planning_scope,
    ).get("checklist_items") or []
    return {
        "summary": str(payload.get("latest_summary") or output_text or "").strip(),
        "artifacts": artifacts,
        "plan_summary": payload.get("plan_summary") or {},
        "result_payload": {
            "original_instruction": str(task.get("text") or "").strip(),
            "effective_instruction": task_instruction,
            "attachments": [
                {
                    "kind": str(item.get("kind") or "").strip() or "input_image",
                    "label": str(item.get("label") or item.get("name") or "").strip(),
                    "path": str(item.get("path") or "").strip(),
                    "name": Path(str(item.get("path") or "")).name,
                }
                for item in attachment_items
            ],
            "changed_files": [],
            "implemented_features": [],
            "result_list": [],
            "checklist_items": planning_checklist_items,
            "latest_summary": str(payload.get("latest_summary") or output_text or "").strip(),
        },
        "checklist_items": planning_checklist_items,
        "next_action": str(payload.get("next_action") or "계획과 체크리스트를 확인한 뒤 진행을 누르세요.").strip(),
    }


def process_one(task):
    task_id = task["id"]
    task_key = task.get("task_key") or ""
    run_id = task.get("current_run_id") or ""
    task_status = str(task.get("status") or "").strip().upper()
    is_redebug = task_status == "REDEBUG_RUNNING"

    def heartbeat(state, progress, code, label, summary):
        record_worker_heartbeat_op(
            WORKER_ID,
            state,
            task_id=task_id,
            run_id=run_id,
            progress_percent=progress,
            current_step_code=code,
            current_step_label=label,
            summary=summary,
            task_status=state,
        )

    if task_status == "POST_UPLOAD_VERIFY":
        task_detail = get_task_op(task_id) or task
        heartbeat("POST_UPLOAD_VERIFY", 90, "post_upload_verify", "업로드 후 검증", "업로드 이후 반영 상태를 확인합니다.")
        try:
            result = run_post_upload_verify(task_detail, heartbeat)
            if result.get("passed"):
                finish_post_upload_verify_success_op(
                    task_id,
                    WORKER_ID,
                    run_id,
                    result.get("summary") or "",
                    result.get("artifacts") or [],
                )
            else:
                finish_post_upload_verify_failure_op(
                    task_id,
                    WORKER_ID,
                    run_id,
                    result.get("summary") or "",
                    result.get("artifacts") or [],
                    rollback_required=bool(result.get("rollback_required")),
                )
        except Exception as exc:
            failure_artifacts = getattr(exc, "artifacts", None) or []
            finish_post_upload_verify_failure_op(
                task_id,
                WORKER_ID,
                run_id,
                str(exc),
                failure_artifacts,
                rollback_required=True,
            )
        return

    task_detail = {**task, **(get_task_op(task_id) or {})}
    task_key = task_detail.get("task_key") or task_key

    if task_status == "PLANNING":
        heartbeat("PLANNING", 10, "planning", "계획 수립", "Codex가 작업 계획과 체크리스트를 정리합니다.")
        try:
            result = run_codex_planning(task_id, task_detail, heartbeat)
            finish_task_planning_op(
                task_id,
                WORKER_ID,
                run_id,
                result.get("summary") or "",
                result.get("artifacts") or [],
                plan_summary=result.get("plan_summary") or {},
                result_payload=result.get("result_payload") or {},
                checklist_items=result.get("checklist_items") or [],
                next_action=result.get("next_action") or "",
            )
            heartbeat("WAITING_APPROVAL", 100, "waiting_approval", "실행 승인 대기", (result.get("summary") or "작업 계획이 준비되었습니다.")[:300])
        except Exception as exc:
            failure_artifacts = getattr(exc, "artifacts", None) or []
            finish_task_failure_op(task_id, WORKER_ID, run_id, str(exc), failure_artifacts)
        return

    ensure_task_checklist_op(task_id, actor=WORKER_ID)
    heartbeat("PLANNING", 5, "planning", "계획 수립", "작업 계획과 체크리스트를 준비합니다.")
    time.sleep(0.2)
    heartbeat("CHECKLIST_ISSUED", 10, "checklist_issued", "체크리스트 발행", "기본 체크리스트를 발행했습니다.")
    time.sleep(0.2)
    heartbeat("REDEBUG_RUNNING" if is_redebug else "RUNNING", 15, "running", "실행 시작", "워커가 작업을 시작합니다.")
    try:
        if task_key:
            runner = TASK_MAP.get(task_key)
            if not runner:
                raise RuntimeError("지원하지 않는 자동 작업입니다.")
            result = runner()
            finish_task_success_op(task_id, WORKER_ID, run_id, result.get("summary") or "", result.get("artifacts") or [])
            return
        heartbeat("SELF_REVIEW", 70, "self_review", "자체 검수", "Codex 결과를 구조화하고 자체 검수를 정리합니다.")
        result = run_codex_command(task_id, task_detail, heartbeat)
        finish_task_success_op(
            task_id,
            WORKER_ID,
            run_id,
            result.get("summary") or "",
            result.get("artifacts") or [],
            plan_summary=result.get("plan_summary") or {},
            result_payload=result.get("result_payload") or {},
            self_review=result.get("self_review") or {},
            checklist_items=result.get("checklist_items") or [],
            next_action=result.get("next_action") or "",
            final_decision=result.get("final_decision") or "",
        )
    except Exception as exc:
        failure_artifacts = getattr(exc, "artifacts", None) or []
        finish_task_failure_op(task_id, WORKER_ID, run_id, str(exc), failure_artifacts)


def main():
    if not REMOTE_MODE:
        initialize_database()
    while True:
        try:
            task = claim_next_task_op(WORKER_ID)
            if task:
                process_one(task)
            else:
                upload_job = claim_next_upload_job_op(WORKER_ID)
                if upload_job:
                    process_upload_job(upload_job)
                else:
                    record_worker_heartbeat_op(
                        WORKER_ID,
                        "IDLE",
                        progress_percent=0,
                        current_step_code="idle",
                        current_step_label="작업 대기",
                        summary="워커가 대기 중입니다.",
                    )
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            record_worker_heartbeat_op(
                WORKER_ID,
                "STALE",
                progress_percent=0,
                current_step_code="stopped",
                current_step_label="중지",
                summary="워커가 중지되었습니다.",
            )
            raise
        except Exception as exc:
            record_worker_heartbeat_op(
                WORKER_ID,
                "FAILED",
                progress_percent=0,
                current_step_code="worker_error",
                current_step_label="워커 오류",
                summary=str(exc),
            )
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
