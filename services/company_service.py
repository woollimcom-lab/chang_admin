import uuid

from sqlalchemy.orm import Session

from auth import get_password_hash

import models


def get_company_members_action(db: Session, company_id: int):
    return db.query(models.CompanyMember).filter(
        models.CompanyMember.CompanyID == company_id
    ).all()


def add_company_member_action(
    db: Session,
    current_user_id: int,
    current_company_id: int,
    name: str,
    phone: str,
    emp_type: str,
    login_id: str | None,
    password: str | None,
    role_name: str,
    perm_revenue: bool,
    perm_expense: bool,
    perm_margin: bool,
    perm_staff: bool,
    perm_stats: bool,
    perm_schedule: bool,
    perm_total: bool,
    perm_delete: bool,
    perm_site: bool,
    perm_company: bool,
):
    name = (name or "").strip()
    phone = (phone or "").strip()
    emp_type = (emp_type or "").strip()
    login_id = (login_id or "").strip() or None
    password = (password or "").strip() or None
    role_name = (role_name or "").strip()

    admin_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user_id,
        models.CompanyMember.CompanyID == current_company_id,
    ).first()
    if not admin_member or not admin_member.Perm_ManageStaff:
        return {
            "status_code": 403,
            "content": {"msg": "직원 관리 권한이 없습니다."},
        }

    company_id = admin_member.CompanyID
    if emp_type == "external":
        access_key = str(uuid.uuid4())[:8]
        new_member = models.CompanyMember(
            CompanyID=company_id,
            UserID=None,
            Name=name,
            Phone=phone,
            Type="external",
            AccessKey=access_key,
            RoleName="외주직원",
            Perm_ViewRevenue=False,
            Perm_ViewExpense=False,
            Perm_ViewMargin=False,
            Perm_ManageStaff=False,
            Perm_ViewStats=False,
            Perm_EditSchedule=False,
            Perm_ViewTotal=False,
        )
        db.add(new_member)
        db.commit()
        return {
            "status": "ok",
            "msg": "외주직원 등록 완료",
            "link": f"http://43.202.209.122/w/{access_key}",
        }

    if not login_id or not password:
        return {
            "status_code": 400,
            "content": {"msg": "아이디와 비밀번호를 입력해주세요."},
        }

    existing = db.query(models.User).filter(models.User.LoginID == login_id).first()
    if existing:
        return {
            "status_code": 400,
            "content": {"msg": "이미 사용 중인 아이디입니다."},
        }

    hashed_pw = get_password_hash(password)
    new_user = models.User(
        LoginID=login_id,
        Password=hashed_pw,
        Name=name,
        PhoneNumber=phone,
    )
    db.add(new_user)
    db.flush()

    new_member = models.CompanyMember(
        CompanyID=company_id,
        UserID=new_user.UserID,
        Name=name,
        Phone=phone,
        Type="internal",
        RoleName=role_name,
        Perm_ViewRevenue=perm_revenue,
        Perm_ViewExpense=perm_expense,
        Perm_ViewMargin=perm_margin,
        Perm_ManageStaff=perm_staff,
        Perm_ViewStats=perm_stats,
        Perm_EditSchedule=perm_schedule,
        Perm_ViewTotal=perm_total,
        Perm_DeleteOrder=perm_delete,
        Perm_ManageSiteCheck=perm_site,
        Perm_ManageCompanyInfo=perm_company,
    )
    db.add(new_member)
    db.commit()
    return {"status": "ok", "msg": f"{name}님을 직원으로 등록했습니다."}


def update_company_member_action(
    db: Session,
    company_id: int,
    member_id: int,
    name: str,
    phone: str,
    role_name: str,
    perm_revenue: bool,
    perm_expense: bool,
    perm_margin: bool,
    perm_stats: bool,
    perm_staff: bool,
    perm_schedule: bool,
    perm_total: bool,
):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.ID == member_id,
        models.CompanyMember.CompanyID == company_id,
    ).first()
    if not member:
        return {"status_code": 404, "content": {"status": "error", "msg": "직원 정보를 찾을 수 없습니다."}}

    member.Name = name
    member.Phone = phone
    member.RoleName = role_name
    member.Perm_ViewRevenue = perm_revenue
    member.Perm_ViewExpense = perm_expense
    member.Perm_ViewMargin = perm_margin
    member.Perm_ManageStaff = perm_staff
    member.Perm_ViewStats = perm_stats
    member.Perm_EditSchedule = perm_schedule
    member.Perm_ViewTotal = perm_total
    db.commit()
    return {"status": "ok", "msg": "수정되었습니다."}


def delete_company_member_action(db: Session, company_id: int, current_user_id: int, member_id: int):
    target_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.ID == member_id,
        models.CompanyMember.CompanyID == company_id,
    ).first()
    if not target_member:
        return {"status_code": 404, "content": {"status": "error", "msg": "직원 정보를 찾을 수 없습니다."}}

    company = db.query(models.Company).filter(
        models.Company.CompanyID == company_id
    ).first()

    if company and target_member.UserID == company.OwnerID:
        return {"status_code": 400, "content": {"status": "error", "msg": "최고 관리자(소유주)는 삭제할 수 없습니다."}}
    if target_member.UserID == current_user_id:
        return {"status_code": 400, "content": {"status": "error", "msg": "본인은 삭제할 수 없습니다."}}

    db.delete(target_member)
    db.commit()
    return {"status": "ok", "msg": "삭제했습니다."}


def external_complete_action(db: Session, order_id: int, key: str):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.AccessKey == key
    ).first()
    if not member:
        return {"status": "error", "msg": "인증 실패"}

    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if order:
        order.ProgressStatus = "시공완료"
        db.commit()
        return {"status": "ok"}
    return {"status": "error"}
