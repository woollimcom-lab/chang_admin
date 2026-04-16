from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services.apt_service import (
    delete_apt_complex_action,
    delete_apt_plan_action,
    delete_apt_window_action,
    get_apt_complexes_action,
    get_apt_manager_payload,
    get_apt_plans_action,
    get_apt_windows_action,
    import_apt_windows_action,
    save_apt_complex_action,
    save_apt_plan_action,
    save_apt_window_action,
)


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


@router.get("/api/apt/complexes")
def get_apt_complexes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_apt_complexes_action(db, current_user.company_id)


@router.get("/api/apt/plans/{complex_id}")
def get_apt_plans(
    complex_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_apt_plans_action(db, current_user.company_id, complex_id)


@router.get("/api/apt/windows/{plan_id}")
def get_apt_windows(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_apt_windows_action(db, current_user.company_id, plan_id)


@router.post("/api/apt/import-to-order")
async def import_apt_windows(
    request: Request,
    order_id: int = Form(...),
    window_ids: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ = current_user
    if not window_ids:
        return RedirectResponse(url=f"/view/{order_id}", status_code=303)
    window_id_list = [int(i) for i in window_ids.split(",") if i.strip()]
    form_data = await request.form()
    result = import_apt_windows_action(db, current_user.company_id, order_id, window_id_list, form_data)
    if result.get("status") == "forbidden":
        raise HTTPException(status_code=403, detail="해당 업체에서 접근할 수 없는 아파트 데이터입니다.")
    return RedirectResponse(url=f"/view/{order_id}", status_code=303)


@router.get("/apt/manager")
async def apt_manager_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    payload = get_apt_manager_payload(db, current_user.company_id, current_user.Name)
    back_to = request.query_params.get("return_to") or "/dashboard"
    if not back_to.startswith("/"):
        back_to = "/dashboard"
    back_label = "주문상세" if back_to.startswith("/view/") else "대시보드"
    return templates.TemplateResponse("apt_manager.html", {
        "request": request,
        "user_name": payload["user_name"],
        "company_name": payload["company_name"],
        "back_to": back_to,
        "back_label": back_label,
    })


@router.post("/api/apt/complex/save")
async def save_apt_complex(
    name: str = Form(...),
    id: int = Form(0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return save_apt_complex_action(db, current_user.company_id, name, id)


@router.post("/api/apt/complex/delete")
async def delete_apt_complex(
    id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return delete_apt_complex_action(db, current_user.company_id, id)


@router.post("/api/apt/plan/save")
async def save_apt_plan(
    complex_id: int = Form(...),
    name: str = Form(...),
    id: int = Form(0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return save_apt_plan_action(db, current_user.company_id, complex_id, name, id)


@router.post("/api/apt/plan/delete")
async def delete_apt_plan(
    id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return delete_apt_plan_action(db, current_user.company_id, id)


@router.post("/api/apt/window/save")
async def save_apt_window(
    plan_id: int = Form(...),
    location: str = Form(...),
    width: float = Form(0),
    height: float = Form(0),
    id: int = Form(0),
    win_type: str = Form(None),
    split_count: int = Form(1),
    box_width: float = Form(0),
    memo: str = Form(None),
    split_sizes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return save_apt_window_action(
        db, current_user.company_id, plan_id, location, width, height, id, win_type, split_count, box_width, memo, split_sizes
    )


@router.post("/api/apt/window/delete")
async def delete_apt_window(
    id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return delete_apt_window_action(db, current_user.company_id, id)
