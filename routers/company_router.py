from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services.company_service import (
    add_company_member_action,
    delete_company_member_action,
    external_complete_action,
    get_company_members_action,
    update_company_member_action,
)


router = APIRouter()


class MemberCreateReq(BaseModel):
    name: str
    phone: str
    emp_type: str
    login_id: str = None
    password: str = None
    role_name: str = "직원"
    perm_revenue: bool = False
    perm_expense: bool = False
    perm_margin: bool = False
    perm_staff: bool = False
    perm_stats: bool = False
    perm_schedule: bool = True
    perm_total: bool = False
    perm_delete: bool = False
    perm_site: bool = False
    perm_company: bool = False


class MemberUpdateReq(BaseModel):
    member_id: int
    name: str
    phone: str
    role_name: str = None
    perm_revenue: bool
    perm_expense: bool
    perm_margin: bool
    perm_stats: bool
    perm_staff: bool
    perm_schedule: bool
    perm_total: bool = False


@router.get("/api/company/check-login-id")
def check_company_login_id(
    login_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    normalized = (login_id or "").strip()
    if not normalized:
        return {"status": "error", "msg": "아이디를 입력하세요."}
    exists = db.query(models.User).filter(models.User.LoginID == normalized).first()
    return {"status": "ok", "available": not bool(exists)}


@router.post("/api/company/add-member")
def add_company_member(
    req: MemberCreateReq,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = add_company_member_action(
        db=db,
        current_user_id=current_user.UserID,
        current_company_id=current_user.company_id,
        name=req.name,
        phone=req.phone,
        emp_type=req.emp_type,
        login_id=req.login_id,
        password=req.password,
        role_name=req.role_name,
        perm_revenue=req.perm_revenue,
        perm_expense=req.perm_expense,
        perm_margin=req.perm_margin,
        perm_staff=req.perm_staff,
        perm_stats=req.perm_stats,
        perm_schedule=req.perm_schedule,
        perm_total=req.perm_total,
        perm_delete=req.perm_delete,
        perm_site=req.perm_site,
        perm_company=req.perm_company,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.get("/api/company/members")
def get_my_members(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_company_members_action(db, current_user.company_id)


@router.post("/api/company/member/update")
def update_member_info(
    req: MemberUpdateReq,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = update_company_member_action(
        db=db,
        company_id=current_user.company_id,
        member_id=req.member_id,
        name=req.name,
        phone=req.phone,
        role_name=req.role_name,
        perm_revenue=req.perm_revenue,
        perm_expense=req.perm_expense,
        perm_margin=req.perm_margin,
        perm_stats=req.perm_stats,
        perm_staff=req.perm_staff,
        perm_schedule=req.perm_schedule,
        perm_total=req.perm_total,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.post("/api/company/member/delete")
async def delete_member(
    member_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = delete_company_member_action(
        db=db,
        company_id=current_user.company_id,
        current_user_id=current_user.UserID,
        member_id=member_id,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.post("/api/external/complete")
async def external_complete(
    order_id: int = Form(...),
    key: str = Form(...),
    db: Session = Depends(get_db),
):
    return external_complete_action(db, order_id, key)
