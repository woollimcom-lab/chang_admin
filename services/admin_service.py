from pathlib import Path
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

import models


BASE_DIR = Path(__file__).resolve().parents[1]


def _can_manage_company_info(company: models.Company | None, member: models.CompanyMember | None, user_id: int) -> bool:
    return bool(
        (company and company.OwnerID == user_id)
        or (member and member.Perm_ManageCompanyInfo)
    )


def get_admin_page_payload(db: Session, current_user: models.User):
    my_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id,
    ).first()

    company = db.query(models.Company).filter(
        models.Company.CompanyID == current_user.company_id
    ).first()
    members = db.query(models.CompanyMember).filter(
        models.CompanyMember.CompanyID == current_user.company_id
    ).all()
    check_items = db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.CompanyID == current_user.company_id
    ).order_by(models.SiteCheckItem.SortOrder).all()

    perms = {
        "revenue": current_user.perm_revenue,
        "expense": current_user.perm_expense,
        "staff": current_user.perm_staff,
        "stats": current_user.perm_stats,
        "schedule": current_user.perm_schedule,
        "margin": current_user.perm_margin,
        "total": current_user.perm_total,
        "company": _can_manage_company_info(company, my_member, current_user.UserID),
        "site": (my_member.Perm_ManageSiteCheck if my_member else False),
        "delete_order": (my_member.Perm_DeleteOrder if my_member else False),
    }

    return {
        "company": company,
        "members": members,
        "check_items": check_items,
        "perms": perms,
        "my_member": my_member,
    }


async def save_company_info_action(
    db: Session,
    current_user: models.User,
    company_name: str,
    ceo_name: str | None,
    phone: str | None,
    biz_num: str | None,
    address: str | None,
    bank_info: str | None,
    seal_file,
):
    my_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id,
    ).first()
    company = db.query(models.Company).filter(
        models.Company.CompanyID == current_user.company_id
    ).first()
    if not company:
        return {"status_code": 404, "content": {"status": "error"}}
    if not _can_manage_company_info(company, my_member, current_user.UserID):
        return {"status_code": 403, "content": {"status": "error"}}

    company.CompanyName = (company_name or "").strip()
    company.CeoName = (ceo_name or "").strip() or None
    company.CompanyPhone = (phone or "").strip() or None
    company.BizNum = (biz_num or "").strip() or None
    company.CompanyAddress = (address or "").strip() or None
    company.BankInfo = (bank_info or "").strip() or None

    if seal_file and getattr(seal_file, "filename", None):
        upload_dir = BASE_DIR / "static" / "uploads" / "company"
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(seal_file.filename).suffix.lower() or ".bin"
        new_filename = f"seal_{company.CompanyID}_{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / new_filename
        content = await seal_file.read()
        file_path.write_bytes(content)

        old_path = getattr(company, "SealPath", None)
        if old_path and old_path.startswith("/static/uploads/company/"):
            old_file = BASE_DIR / old_path.lstrip("/")
            if old_file.exists() and old_file != file_path:
                old_file.unlink()

        company.SealPath = f"/static/uploads/company/{new_filename}"

    db.commit()
    return {"status": "ok"}


def get_curtain_deductions_action(db: Session, company_id: int):
    rows = db.query(models.CurtainHeightDeduction).filter(
        models.CurtainHeightDeduction.CompanyID == company_id,
        models.CurtainHeightDeduction.Category == "커튼",
        models.CurtainHeightDeduction.SubType.in_(["속지", "겉지"]),
    ).all()
    found = {r.SubType: float(r.DeductValue or 0) for r in rows}
    return {
        "속지": found.get("속지", 4.0),
        "겉지": found.get("겉지", 3.5),
    }


def save_curtain_deductions_action(db: Session, company_id: int, sokji: float, geotji: float):
    def upsert(subtype: str, val: float):
        row = db.query(models.CurtainHeightDeduction).filter(
            models.CurtainHeightDeduction.CompanyID == company_id,
            models.CurtainHeightDeduction.Category == "커튼",
            models.CurtainHeightDeduction.SubType == subtype,
        ).first()
        if row:
            row.DeductValue = val
        else:
            db.add(models.CurtainHeightDeduction(
                CompanyID=company_id,
                Category="커튼",
                SubType=subtype,
                DeductValue=val,
            ))

    upsert("속지", float(sokji))
    upsert("겉지", float(geotji))
    db.commit()


def delete_admin_member_action(db: Session, company_id: int, user_id: int):
    target = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == user_id,
        models.CompanyMember.CompanyID == company_id,
    ).first()
    if target:
        db.delete(target)
        db.commit()
        return {"status": "ok"}
    return {"status": "error", "msg": "삭제 실패"}


def update_admin_member_action(
    db: Session,
    current_user: models.User,
    member_id: int,
    name: str,
    phone: str,
    role_name: str,
    login_id: str,
    password: str,
    perm_revenue: bool,
    perm_expense: bool,
    perm_margin: bool,
    perm_total: bool,
    perm_staff: bool,
    perm_stats: bool,
    perm_schedule: bool,
    perm_delete: bool,
    perm_site: bool,
    perm_company: bool,
    get_password_hash,
):
    admin_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID
    ).first()
    if not admin_member or not admin_member.Perm_ManageStaff:
        return {"status_code": 403, "content": {"msg": "수정 권한이 없습니다."}}

    target_member = db.query(models.CompanyMember).filter(
        models.CompanyMember.ID == member_id,
        models.CompanyMember.CompanyID == admin_member.CompanyID,
    ).first()
    if not target_member:
        return {"status_code": 404, "content": {"msg": "직원을 찾을 수 없습니다."}}

    target_member.Name = name
    target_member.Phone = phone
    target_member.RoleName = role_name
    target_member.Perm_ViewRevenue = perm_revenue
    target_member.Perm_ViewExpense = perm_expense
    target_member.Perm_ViewMargin = perm_margin
    target_member.Perm_ViewTotal = perm_total
    target_member.Perm_ManageStaff = perm_staff
    target_member.Perm_ViewStats = perm_stats
    target_member.Perm_DeleteOrder = perm_delete
    target_member.Perm_ManageSiteCheck = perm_site
    target_member.Perm_ManageCompanyInfo = perm_company
    target_member.Perm_EditSchedule = perm_schedule

    if target_member.Type == "internal" and target_member.UserID:
        user_acc = db.query(models.User).filter(
            models.User.UserID == target_member.UserID
        ).first()
        if user_acc:
            user_acc.Name = name
            user_acc.PhoneNumber = phone
            if login_id and user_acc.LoginID != login_id:
                exist = db.query(models.User).filter(
                    models.User.LoginID == login_id
                ).first()
                if exist:
                    return {"status_code": 400, "content": {"msg": "이미 존재하는 아이디입니다."}}
                user_acc.LoginID = login_id
            if password and password.strip():
                user_acc.Password = get_password_hash(password)

    db.commit()
    return {"status": "ok", "msg": "수정되었습니다."}


def add_check_item_action(db: Session, company_id: int, name: str, sub: str):
    max_sort = db.query(func.max(models.SiteCheckItem.SortOrder)).filter(
        models.SiteCheckItem.CompanyID == company_id
    ).scalar() or 0
    db.add(models.SiteCheckItem(
        CompanyID=company_id,
        ItemName=name,
        SubText=sub,
        SortOrder=max_sort + 1,
    ))
    db.commit()
    return {"status": "ok"}


def list_check_items_action(db: Session, company_id: int):
    items = db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.CompanyID == company_id,
    ).order_by(models.SiteCheckItem.SortOrder, models.SiteCheckItem.ItemID).all()
    return [
        {
            "item_id": item.ItemID,
            "item_name": item.ItemName or "",
            "sub_text": item.SubText or "",
        }
        for item in items
    ]


def delete_check_item_action(db: Session, company_id: int, item_id: int):
    db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.ItemID == item_id,
        models.SiteCheckItem.CompanyID == company_id,
    ).delete()
    db.commit()
    return {"status": "ok"}


def update_check_item_action(db: Session, company_id: int, item_id: int, name: str, sub: str):
    item = db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.ItemID == item_id,
        models.SiteCheckItem.CompanyID == company_id,
    ).first()
    if item:
        item.ItemName = name
        item.SubText = sub
        db.commit()
        return {"status": "ok"}
    return {"status": "error", "msg": "항목을 찾을 수 없습니다."}
