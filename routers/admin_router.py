from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user, get_password_hash
from database import get_db
from services.admin_service import (
    add_check_item_action,
    delete_admin_member_action,
    delete_check_item_action,
    get_admin_page_payload,
    get_curtain_deductions_action,
    list_check_items_action,
    save_curtain_deductions_action,
    save_company_info_action,
    update_admin_member_action,
    update_check_item_action,
)


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


class CurtainDeductPayload(BaseModel):
    sokji: float
    geotji: float


def _has_site_manage_permission(db: Session, current_user: models.User) -> bool:
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id,
    ).first()
    return bool(member and (member.RoleName == "대표" or member.Perm_ManageSiteCheck))


@router.get("/admin")
async def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    payload = get_admin_page_payload(db, current_user)
    perms = payload["perms"]
    if not (perms["staff"] or perms["company"] or perms["site"]):
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "company": payload["company"],
        "members": payload["members"],
        "check_items": payload["check_items"],
        "user": current_user,
        "perms": perms,
    })


@router.get("/api/admin/curtain-deductions")
def get_curtain_deductions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return {"ok": True, "data": get_curtain_deductions_action(db, current_user.company_id)}


@router.get("/api/admin/checkitems")
def get_check_items(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not _has_site_manage_permission(db, current_user):
        return JSONResponse(status_code=403, content={"status": "error", "msg": "현장체크 관리 권한이 없습니다."})
    return {"status": "ok", "items": list_check_items_action(db, current_user.company_id)}


@router.post("/api/admin/curtain-deductions")
def save_curtain_deductions(
    payload: CurtainDeductPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        save_curtain_deductions_action(db, current_user.company_id, payload.sokji, payload.geotji)
        return {"ok": True}
    except Exception as e:
        db.rollback()
        return {"ok": False, "msg": str(e)}


@router.post("/api/admin/company/save")
async def save_admin_company(
    company_name: str = Form(...),
    ceo_name: str = Form(None),
    phone: str = Form(None),
    biz_num: str = Form(None),
    address: str = Form(None),
    bank_info: str = Form(None),
    seal_file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = await save_company_info_action(
        db=db,
        current_user=current_user,
        company_name=company_name,
        ceo_name=ceo_name,
        phone=phone,
        biz_num=biz_num,
        address=address,
        bank_info=bank_info,
        seal_file=seal_file,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/api/admin/member/delete")
async def delete_admin_member(
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return delete_admin_member_action(db, current_user.company_id, user_id)


@router.post("/api/admin/member/update")
async def update_admin_member(
    member_id: int = Form(..., alias="user_id"),
    real_user_id: str = Form(None, alias="user_id"),
    name: str = Form(...),
    phone: str = Form(...),
    role_name: str = Form(None),
    login_id: str = Form(None),
    password: str = Form(None),
    perm_revenue: bool = Form(False),
    perm_expense: bool = Form(False),
    perm_margin: bool = Form(False),
    perm_total: bool = Form(False),
    perm_staff: bool = Form(False),
    perm_stats: bool = Form(False),
    perm_schedule: bool = Form(False),
    perm_delete: bool = Form(False),
    perm_site: bool = Form(False),
    perm_company: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ = real_user_id
    result = update_admin_member_action(
        db=db,
        current_user=current_user,
        member_id=member_id,
        name=name,
        phone=phone,
        role_name=role_name,
        login_id=login_id,
        password=password,
        perm_revenue=perm_revenue,
        perm_expense=perm_expense,
        perm_margin=perm_margin,
        perm_total=perm_total,
        perm_staff=perm_staff,
        perm_stats=perm_stats,
        perm_schedule=perm_schedule,
        perm_delete=perm_delete,
        perm_site=perm_site,
        perm_company=perm_company,
        get_password_hash=get_password_hash,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.post("/api/admin/checkitem/add")
async def add_check_item(
    name: str = Form(...),
    sub: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not _has_site_manage_permission(db, current_user):
        return JSONResponse(status_code=403, content={"status": "error", "msg": "현장체크 관리 권한이 없습니다."})
    return add_check_item_action(db, current_user.company_id, name, sub)


@router.post("/api/admin/checkitem/delete")
async def delete_check_item(
    item_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not _has_site_manage_permission(db, current_user):
        return JSONResponse(status_code=403, content={"status": "error", "msg": "현장체크 관리 권한이 없습니다."})
    return delete_check_item_action(db, current_user.company_id, item_id)


@router.post("/api/admin/checkitem/update")
async def update_check_item(
    item_id: int = Form(...),
    name: str = Form(...),
    sub: str = Form(""),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not _has_site_manage_permission(db, current_user):
        return JSONResponse(status_code=403, content={"status": "error", "msg": "현장체크 관리 권한이 없습니다."})
    return update_check_item_action(db, current_user.company_id, item_id, name, sub)
