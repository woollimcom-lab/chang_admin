import random
import traceback
from typing import Dict

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

import models
from auth import create_access_token, verify_password


VERIFICATION_STORE: Dict[str, str] = {}


def root_redirect_action(token: str | None):
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


def send_verification_code_action(phone: str):
    clean_phone = (phone or "").replace("-", "").replace(" ", "").strip()
    code = str(random.randint(100000, 999999))
    VERIFICATION_STORE[clean_phone] = code
    print(f"[AUTH] verification_code={code}")
    return {
        "status": "ok",
        "msg": "인증번호가 발송되었습니다.",
        "debug_code": code,
    }


def verify_code_action(phone: str, code: str):
    clean_phone = (phone or "").replace("-", "").replace(" ", "").strip()
    saved_code = VERIFICATION_STORE.get(clean_phone)
    if not saved_code:
        return {"status": "error", "msg": "인증번호 요청을 먼저 해주세요."}
    if saved_code == code:
        del VERIFICATION_STORE[clean_phone]
        return {"status": "ok", "msg": "인증되었습니다."}
    return {"status": "error", "msg": "인증번호가 일치하지 않습니다."}


def logout_action():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    return response


def check_duplication_action(db: Session, req_type: str, value: str):
    val = (value or "").strip()
    if not val:
        return {"status": "empty", "msg": ""}

    if req_type == "id":
        exists = db.query(models.User).filter(models.User.LoginID == val).first()
        if exists:
            return {"status": "duplicate", "msg": "이미 사용 중인 아이디입니다."}
        return {"status": "ok", "msg": "사용 가능한 아이디입니다."}

    return {"status": "ok", "msg": ""}


def register_saas_action(
    db: Session,
    company_name: str,
    owner_name: str,
    mobile_no: str,
    company_addr: str,
    user_id: str,
    password: str,
    company_phone: str | None,
):
    try:
        if db.query(models.User).filter(models.User.LoginID == user_id).first():
            return {
                "status_code": 400,
                "content": {"msg": "이미 사용 중인 아이디입니다."},
            }

        new_company = models.Company(
            CompanyName=company_name,
            CompanyPhone=company_phone,
            CompanyAddress=company_addr,
            PlanType="trial",
        )
        db.add(new_company)
        db.flush()

        new_user = models.User(
            LoginID=user_id,
            Password=password,
            Name=owner_name,
            PhoneNumber=mobile_no,
        )
        db.add(new_user)
        db.flush()

        new_member = models.CompanyMember(
            UserID=new_user.UserID,
            CompanyID=new_company.CompanyID,
            Name=owner_name,
            Phone=mobile_no,
            Type="internal",
            RoleName="대표",
            Perm_ViewRevenue=True,
            Perm_ViewExpense=True,
            Perm_ViewMargin=True,
            Perm_ManageStaff=True,
            Perm_ViewStats=True,
            Perm_EditSchedule=True,
        )
        db.add(new_member)

        new_company.OwnerID = new_user.UserID
        db.commit()
        return {"status": "ok", "msg": "가입이 완료되었습니다. 로그인해주세요."}
    except Exception as e:
        db.rollback()
        print(f"[AUTH REGISTER ERROR] {e}")
        print(traceback.format_exc())
        return {
            "status_code": 500,
            "content": {"msg": f"서버 내부 오류: {str(e)}"},
        }


def login_for_access_token_action(db: Session, username: str, password: str):
    user = db.query(models.User).filter(models.User.LoginID == username).first()
    if not user or not verify_password(password, user.Password):
        return {
            "status_code": 400,
            "content": {"detail": "아이디 또는 비밀번호가 일치하지 않습니다."},
        }

    access_token = create_access_token(
        data={
            "sub": user.LoginID,
            "uid": user.UserID,
            "name": user.Name,
        }
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_name": user.Name,
    }
