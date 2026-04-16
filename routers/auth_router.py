from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import (
    check_duplication_action,
    login_for_access_token_action,
    logout_action,
    register_saas_action,
    root_redirect_action,
    send_verification_code_action,
    verify_code_action,
)


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()


class PhoneReq(BaseModel):
    phone: str


class VerifyReq(BaseModel):
    phone: str
    code: str


class CheckDupReq(BaseModel):
    type: str
    value: str


@router.get("/")
async def root(request: Request):
    return root_redirect_action(request.cookies.get("access_token"))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@router.post("/api/auth/send-code")
async def send_verification_code(req: PhoneReq):
    return send_verification_code_action(req.phone)


@router.post("/api/auth/verify-code")
async def verify_code(req: VerifyReq):
    return verify_code_action(req.phone, req.code)


@router.get("/logout")
def logout():
    return logout_action()


@router.post("/api/auth/check-dup")
async def check_duplication(req: CheckDupReq, db: Session = Depends(get_db)):
    return check_duplication_action(db, req.type, req.value)


@router.post("/api/auth/register")
def register_saas(
    company_name: str = Form(...),
    owner_name: str = Form(...),
    mobile_no: str = Form(...),
    company_addr: str = Form(...),
    user_id: str = Form(...),
    password: str = Form(...),
    company_phone: str = Form(None),
    db: Session = Depends(get_db),
):
    result = register_saas_action(
        db=db,
        company_name=company_name,
        owner_name=owner_name,
        mobile_no=mobile_no,
        company_addr=company_addr,
        user_id=user_id,
        password=password,
        company_phone=company_phone,
    )
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.post("/api/auth/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    result = login_for_access_token_action(db, form_data.username, form_data.password)
    if "status_code" in result:
        return JSONResponse(status_code=result["status_code"], content=result["content"])
    return result


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
