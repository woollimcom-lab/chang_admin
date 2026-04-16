from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services.misc_service import debug_index_force_action


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


def _get_member(db: Session, current_user):
    if not current_user:
        return None
    return db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id,
    ).first()


@router.get("/expense")
async def view_expense_page(request: Request, db: Session = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    member = _get_member(db, current_user)
    return templates.TemplateResponse(
        "expense.html",
        {
            "request": request,
            "user_name": current_user.Name,
            "user_role": (member.RoleName if member else "직원"),
        },
    )


@router.get("/debug/index")
def debug_index_force(db: Session = Depends(get_db)):
    return debug_index_force_action(db)


@router.get("/ledger")
async def view_unified_ledger(request: Request, db: Session = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    member = _get_member(db, current_user)
    can_admin_view = bool(
        member and (
            member.RoleName == "대표"
            or bool(member.Perm_ViewExpense)
            or bool(member.Perm_ViewTotal)
            or bool(member.Perm_ManageStaff)
        )
    )
    return templates.TemplateResponse(
        "unified_ledger.html",
        {
            "request": request,
            "user_name": current_user.Name,
            "user_role": (member.RoleName if member else "직원"),
            "initial_ledger_role": "admin" if can_admin_view else "staff",
            "can_admin_ledger_view": can_admin_view,
        },
    )


@router.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_probe():
    return {}
