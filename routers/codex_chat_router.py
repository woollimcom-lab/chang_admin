import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates

from auth import NeedsLogin, get_current_user
from database import get_db
from services.codex_chat_active_service import (
    approve_codex_chat_project as approve_codex_chat_active_project,
    create_codex_chat_project as create_codex_chat_active_project,
    dispatch_codex_chat_command as dispatch_codex_chat_active_command,
    get_codex_chat_initial_view_model as get_codex_chat_active_initial_view_model,
    get_codex_chat_run_state as get_codex_chat_active_run_state,
    run_codex_chat_primary_action as run_codex_chat_active_primary_action,
)


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


def _codex_chat_state_signature(payload):
    task = (payload or {}).get("current_task") or {}
    return "|".join(
        [
            str((payload or {}).get("conversation_task_id") or ""),
            str((payload or {}).get("run_state") or ""),
            str((payload or {}).get("updated_at") or ""),
            str((payload or {}).get("summary") or ""),
            str((payload or {}).get("result_message") or ""),
            str(task.get("status") or ""),
            str(task.get("progress_percent") or ""),
            str(task.get("updated_at") or ""),
        ]
    )


def _sse_payload(event_name, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {body}\n\n"


async def _ensure_codex_chat_user(request: Request, db: Session):
    try:
        current_user = await get_current_user(request, db)
    except NeedsLogin as exc:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해주세요.") from exc
    if not current_user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    login_id = str(getattr(current_user, "LoginID", "") or "").strip()
    if login_id != "bibaram1":
        raise HTTPException(status_code=404, detail="Not Found")
    return current_user


@router.get("/codex-chat")
async def codex_chat_page(request: Request, conversation_task_id: str = "", composer_mode: str = "", project_id: str = "", db: Session = Depends(get_db)):
    current_user = await _ensure_codex_chat_user(request, db)
    initial_view = get_codex_chat_active_initial_view_model(conversation_task_id=conversation_task_id, composer_mode=composer_mode, project_id=project_id)
    return templates.TemplateResponse(
        "codex_chat.html",
        {
            "request": request,
            "user_name": getattr(current_user, "Name", "") or getattr(current_user, "LoginID", "") or "사용자",
            "initial_view_model": initial_view,
        },
    )


@router.get("/api/codex-chat/state")
async def codex_chat_state(request: Request, conversation_task_id: str = "", composer_mode: str = "", project_id: str = "", db: Session = Depends(get_db)):
    await _ensure_codex_chat_user(request, db)
    return get_codex_chat_active_initial_view_model(conversation_task_id=conversation_task_id, composer_mode=composer_mode, project_id=project_id)


@router.get("/api/codex-chat/events")
async def codex_chat_events(request: Request, conversation_task_id: str = "", composer_mode: str = "", project_id: str = "", db: Session = Depends(get_db)):
    await _ensure_codex_chat_user(request, db)

    async def event_stream():
        last_signature = ""
        while True:
            if await request.is_disconnected():
                break
            payload = get_codex_chat_active_run_state(
                conversation_task_id=conversation_task_id,
                composer_mode=composer_mode,
                project_id=project_id,
            )
            signature = _codex_chat_state_signature(payload)
            if signature != last_signature:
                last_signature = signature
                yield _sse_payload("state", payload)
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/codex-chat/command")
async def codex_chat_command(request: Request, db: Session = Depends(get_db)):
    current_user = await _ensure_codex_chat_user(request, db)
    payload = await request.json()
    message = str((payload or {}).get("message") or "")
    conversation_task_id = str((payload or {}).get("conversation_task_id") or "")
    mode = str((payload or {}).get("mode") or "")
    project_id = str((payload or {}).get("project_id") or "")
    state_file = str((payload or {}).get("state_file") or "")
    preview_context = (payload or {}).get("preview_context") or {}
    try:
        return dispatch_codex_chat_active_command(
            message,
            state_file=state_file,
            actor=str(getattr(current_user, "LoginID", "") or getattr(current_user, "Name", "") or "").strip(),
            preview_context=preview_context,
            conversation_task_id=conversation_task_id,
            mode=mode,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/codex-chat/tasks/{task_id}/primary-action")
async def codex_chat_primary_action(task_id: str, request: Request, db: Session = Depends(get_db)):
    current_user = await _ensure_codex_chat_user(request, db)
    payload = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    try:
        return run_codex_chat_active_primary_action(
            task_id,
            actor=str(getattr(current_user, "LoginID", "") or getattr(current_user, "Name", "") or "").strip(),
            summary=str((payload or {}).get("summary") or ""),
            project_id=str((payload or {}).get("project_id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/codex-chat/run-state")
async def codex_chat_run_state(request: Request, conversation_task_id: str = "", composer_mode: str = "", project_id: str = "", db: Session = Depends(get_db)):
    await _ensure_codex_chat_user(request, db)
    return get_codex_chat_active_run_state(conversation_task_id=conversation_task_id, composer_mode=composer_mode, project_id=project_id)


@router.post("/api/codex-chat/projects")
async def codex_chat_create_project(request: Request, db: Session = Depends(get_db)):
    current_user = await _ensure_codex_chat_user(request, db)
    payload = await request.json()
    try:
        return create_codex_chat_active_project(
            title=str((payload or {}).get("title") or ""),
            goal=str((payload or {}).get("goal") or ""),
            actor=str(getattr(current_user, "LoginID", "") or getattr(current_user, "Name", "") or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/codex-chat/projects/{project_id}/approve")
async def codex_chat_approve_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    current_user = await _ensure_codex_chat_user(request, db)
    try:
        return approve_codex_chat_active_project(
            project_id=project_id,
            actor=str(getattr(current_user, "LoginID", "") or getattr(current_user, "Name", "") or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
