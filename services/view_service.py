import os
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

import models


K_CATEGORY_CURTAIN = "커튼"
K_CATEGORY_BLIND = "블라인드"
K_CATEGORY_OTHER = "기타"
DEFAULT_ITEM_CATEGORIES = [K_CATEGORY_CURTAIN, K_CATEGORY_BLIND, K_CATEGORY_OTHER]
WEEK_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def ensure_order_extra_info_table(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS OrderExtraInfo (
            ExtraID INT AUTO_INCREMENT PRIMARY KEY,
            OrderID INT NOT NULL UNIQUE,
            InflowRoute VARCHAR(50) NULL,
            InflowDetail VARCHAR(255) NULL,
            ASReason VARCHAR(50) NULL,
            ASResponsibility VARCHAR(50) NULL,
            ASChargeType VARCHAR(30) NULL,
            ASCost NUMERIC(18, 0) NULL DEFAULT 0,
            ASNote TEXT NULL,
            UpdatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX ix_order_extra_info_order_id (OrderID)
        )
    """))
    db.commit()


def get_order_extra_info(db: Session, order_id: int):
    extra_model = getattr(models, "OrderExtraInfo", None)
    if extra_model is None:
        return None
    ensure_order_extra_info_table(db)
    return db.query(extra_model).filter(extra_model.OrderID == int(order_id)).first()


def get_or_create_order_extra_info(db: Session, order_id: int):
    extra_model = getattr(models, "OrderExtraInfo", None)
    if extra_model is None:
        return None
    extra = get_order_extra_info(db, order_id)
    if extra:
        return extra
    extra = extra_model(OrderID=int(order_id))
    db.add(extra)
    db.commit()
    db.refresh(extra)
    return extra


def safe_num(val):
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except Exception:
        return 0.0


def safe_int(val):
    try:
        return int(safe_num(val))
    except Exception:
        return 0


def format_number(value):
    try:
        return "{:,}".format(int(float(value or 0)))
    except Exception:
        return "0"


def calc_final_price(total, discount, vat_yn):
    supply = float(total or 0) - float(discount or 0)
    val = supply + (supply * 0.1) if vat_yn == "Y" else supply
    return int(round(val))


def _item_detail_value(item, attr_name: str, legacy_name: Optional[str] = None) -> str:
    if not item:
        return ""
    val = getattr(item, attr_name, None)
    if (val is None or val == "") and legacy_name:
        val = getattr(item, legacy_name, None)
    return str(val or "").strip()


def item_slot(item, attr_name: str, legacy_name: Optional[str] = None) -> str:
    return _item_detail_value(item, attr_name, legacy_name)


def compose_item_name(item) -> str:
    cate1 = _item_detail_value(item, "cate1", "ProductName")
    cate2 = _item_detail_value(item, "cate2")
    return " ".join([p for p in [cate1, cate2] if p]).strip()


def item_category_mode(category: Optional[str]) -> str:
    cat = (category or "").strip()
    if cat == K_CATEGORY_BLIND:
        return "blind"
    if cat == K_CATEGORY_CURTAIN:
        return "curtain"
    return "generic"


def item_categories_for_ui() -> List[str]:
    raw = (os.getenv("ITEM_CATEGORIES") or "").strip()
    if not raw:
        return DEFAULT_ITEM_CATEGORIES.copy()

    categories: List[str] = []
    for token in raw.split(","):
        name = token.strip()
        if name and name not in categories:
            categories.append(name)

    if not categories:
        categories = DEFAULT_ITEM_CATEGORIES.copy()

    for fallback in DEFAULT_ITEM_CATEGORIES:
        if fallback not in categories:
            categories.append(fallback)
    return categories


def item_category_modes_for_ui(categories: Optional[List[str]] = None) -> Dict[str, str]:
    cats = categories or item_categories_for_ui()
    return {c: item_category_mode(c) for c in cats}


def get_or_create_curtain_deductions(db: Session, company_id: int):
    defaults = {"속지": 4.0, "겉지": 3.5}
    rows = db.query(models.CurtainHeightDeduction).filter(
        models.CurtainHeightDeduction.CompanyID == company_id,
        models.CurtainHeightDeduction.Category == K_CATEGORY_CURTAIN,
        models.CurtainHeightDeduction.SubType.in_(list(defaults.keys())),
    ).all()

    found = {r.SubType: float(r.DeductValue or 0) for r in rows}
    changed = False
    for key, value in defaults.items():
        if key not in found:
            db.add(
                models.CurtainHeightDeduction(
                    CompanyID=company_id,
                    Category=K_CATEGORY_CURTAIN,
                    SubType=key,
                    DeductValue=value,
                )
            )
            found[key] = value
            changed = True
    if changed:
        db.commit()
    return found


def ensure_order_managers_table(db: Session):
    models.OrderManager.__table__.create(bind=db.get_bind(), checkfirst=True)


def list_order_manager_ids(db: Session, order_id: int) -> List[int]:
    ensure_order_managers_table(db)
    rows = (
        db.query(models.OrderManager.MemberID)
        .filter(models.OrderManager.OrderID == order_id)
        .order_by(models.OrderManager.IsPrimary.desc(), models.OrderManager.ID.asc())
        .all()
    )
    ids = []
    for row in rows:
        member_id = safe_int(getattr(row, "MemberID", 0))
        if member_id and member_id not in ids:
            ids.append(member_id)
    return ids


def list_order_manager_pairs(db: Session, order_id: int) -> List[tuple[int, str]]:
    ensure_order_managers_table(db)
    rows = (
        db.query(models.OrderManager.MemberID, models.CompanyMember.Name)
        .join(models.CompanyMember, models.OrderManager.MemberID == models.CompanyMember.ID)
        .filter(models.OrderManager.OrderID == order_id)
        .order_by(models.OrderManager.IsPrimary.desc(), models.OrderManager.ID.asc())
        .all()
    )
    pairs: List[tuple[int, str]] = []
    seen_ids = set()
    for row in rows:
        member_id = safe_int(getattr(row, "MemberID", 0))
        name = str(getattr(row, "Name", "") or "").strip()
        if not member_id or member_id in seen_ids or not name:
            continue
        seen_ids.add(member_id)
        pairs.append((member_id, name))
    return pairs


def list_order_manager_names(db: Session, order_id: int) -> List[str]:
    return [name for _, name in list_order_manager_pairs(db, order_id)]


def sync_order_manager_shadow_fields(db: Session, order) -> bool:
    return False


def sync_order_managers(db: Session, order_id: int, member_ids: List[int]):
    ensure_order_managers_table(db)
    unique_ids: List[int] = []
    for raw_id in member_ids or []:
        member_id = safe_int(raw_id)
        if member_id and member_id not in unique_ids:
            unique_ids.append(member_id)

    db.query(models.OrderManager).filter(models.OrderManager.OrderID == order_id).delete()
    for index, member_id in enumerate(unique_ids):
        db.add(
            models.OrderManager(
                OrderID=order_id,
                MemberID=member_id,
                IsPrimary=(index == 0),
            )
        )


def get_company_representative_member(db: Session, company_id: int):
    if not company_id:
        return None

    representative = (
        db.query(models.CompanyMember)
        .filter(
            models.CompanyMember.CompanyID == company_id,
            models.CompanyMember.RoleName == "대표",
        )
        .order_by(models.CompanyMember.ID.asc())
        .first()
    )
    if representative:
        return representative

    company = (
        db.query(models.Company)
        .filter(models.Company.CompanyID == company_id)
        .first()
    )
    owner_user_id = safe_int(getattr(company, "OwnerID", 0))
    if owner_user_id:
        representative = (
            db.query(models.CompanyMember)
            .filter(
                models.CompanyMember.CompanyID == company_id,
                models.CompanyMember.UserID == owner_user_id,
            )
            .order_by(models.CompanyMember.ID.asc())
            .first()
        )
        if representative:
            return representative

    return (
        db.query(models.CompanyMember)
        .filter(models.CompanyMember.CompanyID == company_id)
        .order_by(models.CompanyMember.ID.asc())
        .first()
    )


def fill_unassigned_orders_with_representative(
    db: Session,
    company_id: Optional[int] = None,
    order_ids: Optional[List[int]] = None,
    limit: int = 1000,
) -> Dict[str, int]:
    ensure_order_managers_table(db)

    query = db.query(models.Order)
    if company_id:
        query = query.filter(models.Order.CompanyID == company_id)
    if order_ids:
        query = query.filter(models.Order.OrderID.in_(order_ids))

    orders = query.order_by(models.Order.OrderID.asc()).limit(max(1, limit)).all()
    representative_cache: Dict[int, int] = {}
    updated = 0
    skipped = 0

    for order in orders:
        if list_order_manager_ids(db, order.OrderID):
            skipped += 1
            continue

        target_company_id = safe_int(getattr(order, "CompanyID", 0))
        if target_company_id not in representative_cache:
            representative = get_company_representative_member(db, target_company_id)
            representative_cache[target_company_id] = safe_int(getattr(representative, "ID", 0))

        representative_id = representative_cache.get(target_company_id, 0)
        if not representative_id:
            skipped += 1
            continue

        sync_order_managers(db, order.OrderID, [representative_id])
        updated += 1

    if updated:
        db.commit()

    return {
        "checked": len(orders),
        "updated": updated,
        "skipped": skipped,
    }


def repair_order_managers_from_primary(db: Session, order) -> bool:
    return False


def backfill_order_managers_for_order(db: Session, order) -> bool:
    return False


def backfill_order_managers_for_company(db: Session, company_id: int, limit: int = 500) -> int:
    return 0


def backfill_order_managers_batch(
    db: Session,
    company_id: Optional[int] = None,
    batch_size: int = 500,
    max_batches: Optional[int] = None,
) -> int:
    return 0


def _backfill_order_managers_all_companies(db: Session, limit: int = 500) -> int:
    return 0


def _backfill_order_managers_for_company_cursor(
    db: Session,
    company_id: int,
    limit: int = 500,
    last_order_id: int = 0,
) -> tuple[int, int, int]:
    return 0, last_order_id, 0


def _backfill_order_managers_all_companies_cursor(
    db: Session,
    limit: int = 500,
    last_order_id: int = 0,
) -> tuple[int, int, int]:
    return 0, last_order_id, 0


def audit_order_managers_batch(
    db: Session,
    company_id: Optional[int] = None,
    limit: int = 1000,
) -> Dict[str, object]:
    ensure_order_managers_table(db)

    query = db.query(models.Order)
    if company_id:
        query = query.filter(models.Order.CompanyID == company_id)

    orders = query.order_by(models.Order.OrderID.asc()).limit(limit).all()

    issues: List[Dict[str, object]] = []
    summary = {
        "checked": len(orders),
        "missing_links": 0,
        "shadow_mismatch": 0,
        "legacy_name_unmatched": 0,
    }

    for order in orders:
        rows = (
            db.query(models.OrderManager)
            .filter(models.OrderManager.OrderID == order.OrderID)
            .order_by(models.OrderManager.IsPrimary.desc(), models.OrderManager.ID.asc())
            .all()
        )
        manager_pairs = list_order_manager_pairs(db, order.OrderID)
        manager_ids = [safe_int(getattr(row, "MemberID", 0)) for row in rows if safe_int(getattr(row, "MemberID", 0))]
        primary_count = sum(1 for row in rows if bool(getattr(row, "IsPrimary", False)))

        if not rows:
            summary["missing_links"] += 1
            issues.append(
                {
                    "order_id": order.OrderID,
                    "company_id": order.CompanyID,
                    "issue": "missing_links",
                }
            )
            continue

        if primary_count != 1:
            summary["shadow_mismatch"] += 1
            issues.append(
                {
                    "order_id": order.OrderID,
                    "company_id": order.CompanyID,
                    "issue": "primary_mismatch",
                    "primary_count": primary_count,
                    "manager_pairs": manager_pairs,
                }
            )

        if len(manager_ids) != len(set(manager_ids)):
            summary["legacy_name_unmatched"] += 1
            issues.append(
                {
                    "order_id": order.OrderID,
                    "company_id": order.CompanyID,
                    "issue": "duplicate_member_links",
                    "manager_pairs": manager_pairs,
                }
            )

    return {
        "summary": summary,
        "issues": issues,
    }


def enrich_order(order):
    if not order:
        return None

    stat = order.ProgressStatus
    if stat == "AS요청":
        order.EffDate = order.ASDate or order.ConstructionDate or order.RequestDate
    elif stat == "방문상담":
        order.EffDate = order.VisitDate or order.RequestDate
    elif stat in ["시공", "시공예정", "주문", "수령", "작업대기", "작업보류", "작업완료"]:
        order.EffDate = order.ConstructionDate or order.VisitDate or order.RequestDate
    else:
        order.EffDate = order.RequestDate

    if order.FinalAmount and order.FinalAmount > 0:
        order.FinalAmt = int(order.FinalAmount)
    else:
        order.FinalAmt = calc_final_price(
            order.TotalAmount, order.DiscountAmount, order.IsVatIncluded
        )

    deposit = float(order.DepositAmount or 0)
    order.BalanceAmt = int(order.FinalAmt - deposit)

    if "items" in order.__dict__:
        cats = [i.Category1 or i.Category for i in order.items if (i.Category1 or i.Category)]
        count_map = Counter(cats)
        order.ItemSummary = ", ".join([f"{k}\u00A0{v}" for k, v in count_map.items()])
    elif not hasattr(order, "ItemSummary"):
        order.ItemSummary = ""

    order.ASFlag = "Y" if (order.IsAS == "Y" and stat == "AS요청") else "N"
    order.Ord = order.IsOrdered
    order.Recv = order.IsReceived
    order.Wait = order.IsWaiting
    order.Hold = order.IsHold
    return order


def build_group_map(items) -> Dict[str, list]:
    group_map: Dict[str, list] = {}

    def clean(value):
        return str(value or "").replace("'", "\\'").replace("\r\n", " ")

    for item in items:
        grp_id = item.GroupID
        if not grp_id:
            continue
        group_map.setdefault(grp_id, []).append(
            {
                "id": item.ItemID,
                "w": safe_num(item.Width),
                "h": safe_num(item.Height),
                "q": safe_num(item.Quantity),
                "p": safe_num(item.UnitPrice),
                "prod": clean(item_slot(item, "cate1", "ProductName")),
                "color": clean(item_slot(item, "cate2")),
                "opt": clean(item_slot(item, "cate3", "OptionInfo")),
                "memo": clean(item_slot(item, "cate4", "ItemMemo")),
                "loc": clean(item.Location),
                "supplier": clean(item.Supplier),
                "supplier_id": safe_int(((item.Attributes or {}) if isinstance(item.Attributes, dict) else {}).get("supplier_id")),
                "category1": item.Category1 or "",
                "BlindSize": clean(item.BlindSize),
                "BlindQty": clean(item.BlindQty),
                "BlindCount": safe_int(item.BlindCount),
                "attributes": dict(item.Attributes) if isinstance(item.Attributes, dict) else {},
            }
        )
    return group_map


def build_display_dates(order):
    visit_date = ""
    const_date = ""
    if order.VisitDate:
        visit_date = (
            f"{order.VisitDate.strftime('%m/%d')}({WEEK_NAMES[order.VisitDate.weekday()]}) "
            f"{order.VisitDate.strftime('%H:%M')}"
        )
    if order.ConstructionDate:
        const_date = (
            f"{order.ConstructionDate.strftime('%m/%d')}({WEEK_NAMES[order.ConstructionDate.weekday()]}) "
            f"{order.ConstructionDate.strftime('%H:%M')}"
        )
    return visit_date, const_date


def init_default_check_items(db: Session, company_id: int):
    exists = db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.CompanyID == company_id
    ).first()
    if exists:
        return

    defaults = [
        ("콘크리트", "해머드릴/비트"),
        ("석고보드", "석고앙카"),
        ("스테인리스", "직결피스/기리"),
        ("대리석", "전용비트"),
        ("전동제품", "전원/모터/리모컨"),
        ("우드", "타카/못"),
        ("기사사다리", "층고확인"),
    ]
    for idx, (name, sub) in enumerate(defaults):
        db.add(
            models.SiteCheckItem(
                CompanyID=company_id,
                ItemName=name,
                SubText=sub,
                SortOrder=idx + 1,
            )
        )
    db.commit()


def log_history(db: Session, order_id: int, log_type: str, content: str, member_name: str = None):
    try:
        db.add(
            models.OrderHistory(
                OrderID=order_id,
                LogType=log_type,
                Contents=content,
                MemberName=member_name,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def get_permissions_for_auth(db: Session, auth: dict) -> Dict[str, bool]:
    perms = {
        "revenue": False,
        "staff": False,
        "schedule": False,
        "stats": False,
        "margin": False,
        "total": False,
        "site": False,
    }
    if auth["type"] == "user":
        cur_mem = db.query(models.CompanyMember).filter(
            models.CompanyMember.ID == auth["member_id"]
        ).first()
        if cur_mem:
            perms = {
                "revenue": cur_mem.RoleName == "대표",
                "staff": bool(cur_mem.Perm_ManageStaff),
                "schedule": bool(cur_mem.Perm_EditSchedule),
                "stats": bool(cur_mem.Perm_ViewStats),
                "margin": bool(cur_mem.Perm_ViewMargin),
                "total": bool(cur_mem.Perm_ViewTotal),
                "site": bool(cur_mem.Perm_ManageSiteCheck),
            }
            if cur_mem.RoleName == "대표":
                perms = {k: True for k in perms}
    else:
        perms["schedule"] = True
    return perms


def get_role_name(db: Session, auth: dict) -> str:
    if auth["type"] == "external":
        return "외주직원"
    cur_mem = db.query(models.CompanyMember).filter(
        models.CompanyMember.ID == auth["member_id"]
    ).first()
    return cur_mem.RoleName if cur_mem else ""


def history_editable(db: Session, auth: dict, history) -> bool:
    if history.MemberName == auth["name"]:
        return True
    if auth["type"] != "user":
        return False
    me = db.query(models.CompanyMember).filter(
        models.CompanyMember.ID == auth["member_id"]
    ).first()
    return bool(me and me.RoleName == "대표")


def get_status_class(status: str) -> str:
    if not status:
        return "bg-req"
    if "AS" in status:
        return "bg-as"
    if "방문" in status:
        return "bg-visit"
    if "견적" in status:
        return "bg-req"
    if any(token in status for token in ["시공", "주문", "수령"]):
        return "bg-const"
    if "완료" in status:
        return "bg-done"
    return "bg-req"


def summarize_order_items(order) -> str:
    item_txt = "품목 미기재"
    if getattr(order, "items", None):
        cats = [i.Category1 or i.Category for i in order.items if (i.Category1 or i.Category)]
        if cats:
            item_txt = ", ".join([f"{k} {v}" for k, v in Counter(cats).items()])
    return item_txt


def build_history_list(histories) -> List[str]:
    history_list = []
    for history in histories:
        date_str = history.RegDate.strftime("%Y-%m-%d") if history.RegDate else "-"
        history_list.append(f"{date_str}|{history.Contents}")
    return history_list


def build_site_check_text(order) -> str:
    site_parts = []
    if order.InstallSurface:
        site_parts.append(order.InstallSurface.replace(",", " | "))
    if order.ChecklistMemo:
        site_parts.append(order.ChecklistMemo)
    return " / ".join(site_parts)


def pick_external_target(order, start_dt: datetime, end_dt: datetime):
    if order.ConstructionDate and start_dt <= order.ConstructionDate <= end_dt:
        return order.ConstructionDate, order.ProgressStatus
    if order.VisitDate and start_dt <= order.VisitDate <= end_dt:
        return order.VisitDate, "방문상담"
    if order.ASDate and start_dt <= order.ASDate <= end_dt:
        return order.ASDate, "AS요청"
    if order.RequestDate and start_dt <= order.RequestDate <= end_dt:
        return order.RequestDate, order.ProgressStatus
    return None, order.ProgressStatus


def build_view_redirect(order_id: int, auth: dict, access_key: Optional[str] = None):
    if auth.get("type") == "external":
        key = access_key or ""
        return RedirectResponse(url=f"/w/view/{order_id}?key={key}", status_code=303)
    return RedirectResponse(url=f"/view/{order_id}", status_code=303)


def update_order_manager_action(db: Session, current_user, order_id: int, manager_ids: List[int]):
    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order:
        return JSONResponse(status_code=404, content={"msg": "주문 없음"})

    if getattr(current_user, "member_type", "internal") == "external":
        return JSONResponse(status_code=403, content={"msg": "외주팀은 담당자를 변경할 수 없습니다."})

    normalized_ids: List[int] = []
    for raw_id in manager_ids or []:
        member_id = safe_int(raw_id)
        if member_id and member_id not in normalized_ids:
            normalized_ids.append(member_id)

    if not normalized_ids:
        sync_order_managers(db, order.OrderID, [])
    else:
        selected_members = db.query(models.CompanyMember).filter(
            models.CompanyMember.ID.in_(normalized_ids),
            models.CompanyMember.CompanyID == current_user.company_id,
        ).all()
        member_map = {safe_int(m.ID): m for m in selected_members}
        ordered_members = [member_map[mid] for mid in normalized_ids if mid in member_map]
        sync_order_managers(db, order.OrderID, [m.ID for m in ordered_members])

    db.commit()
    return {"status": "ok", "msg": "담당자가 저장되었습니다."}


def update_schedule_action(db: Session, current_user, order_id: int, new_date: str):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID
    ).first()
    if not member:
        return {"status": "error"}

    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == member.CompanyID,
    ).first()

    if order:
        dt = datetime.strptime(new_date, "%Y-%m-%d")
        if order.ProgressStatus == "AS요청":
            order.ASDate = dt
        elif order.ConstructionDate:
            order.ConstructionDate = dt
        else:
            order.VisitDate = dt
        db.commit()
    return {"status": "ok"}


def update_order_date_action(db: Session, auth: dict, order_id: int, target: str, date_str: str):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return JSONResponse(content={"status": "error", "msg": "주문 없음"}, status_code=404)

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        log_msg = ""

        if "방문" in target:
            order.VisitDate = dt
            order.ProgressStatus = "방문상담"
            log_msg = f"방문일정: {date_str}"
            order.ConstructionDate = None
            order.ASDate = None
        elif "시공" in target:
            order.ConstructionDate = dt
            order.ProgressStatus = "시공예정"
            log_msg = f"시공일정: {date_str}"
            order.ASDate = None
        elif "AS" in target or "as" in target.lower():
            order.ASDate = dt
            order.IsAS = "Y"
            order.ProgressStatus = "AS요청"
            log_msg = f"AS일정: {date_str}"

        db.commit()
        if log_msg:
            log_history(db, order_id, "일정변경", log_msg, auth["name"])
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse(content={"status": "error", "msg": str(exc)}, status_code=500)


def update_status_action(
    db: Session,
    auth: dict,
    order_id: int,
    type_value: str,
    val: str,
    method: Optional[str],
    bank: Optional[str],
    depositor: Optional[str],
    access_key: Optional[str],
):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return build_view_redirect(order_id, auth, access_key)

    log_msg = ""
    log_type = "상태변경"

    if type_value == "main":
        log_msg = f"{order.ProgressStatus} → {val}"
        order.ProgressStatus = val
        if val == "견적상담":
            order.VisitDate = None
            order.ConstructionDate = None
            order.ASDate = None
        elif val == "방문상담":
            order.ConstructionDate = None
            order.ASDate = None
            if not order.VisitDate:
                order.VisitDate = datetime.now()
        elif val == "시공예정":
            order.ASDate = None
            if not order.ConstructionDate:
                order.ConstructionDate = datetime.now()
        elif val != "AS요청":
            order.ASDate = None
    elif type_value == "sub":
        if val == "order":
            new_val = "N" if order.IsOrdered == "Y" else "Y"
            order.IsOrdered = new_val
            log_msg = "제품주문 " + ("취소" if new_val == "N" else "완료")
            if new_val == "Y":
                db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).update({"ItemStep": 1})
        elif val == "receive":
            new_val = "N" if order.IsReceived == "Y" else "Y"
            order.IsReceived = new_val
            log_msg = "제품수령 " + ("취소" if new_val == "N" else "완료")
            if new_val == "Y":
                db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).update({"ItemStep": 2})
        elif val == "waiting":
            new_val = "N" if order.IsWaiting == "Y" else "Y"
            order.IsWaiting = new_val
            log_msg = "작업대기 " + ("해제" if new_val == "N" else "설정")
            if new_val == "Y":
                order.IsHold = "N"
        elif val == "hold":
            new_val = "N" if order.IsHold == "Y" else "Y"
            order.IsHold = new_val
            log_msg = "작업보류 " + ("해제" if new_val == "N" else "설정")
            if new_val == "Y":
                order.IsWaiting = "N"
        elif val == "payment":
            order.PaymentStatus = "미결제" if order.PaymentStatus == "입금완료" else "입금완료"
            log_msg = f"결제상태: {order.PaymentStatus}"
    elif type_value == "pay":
        order.PaymentStatus = val
        if method:
            order.PaymentMethod = method
        if bank:
            order.BankName = bank
        if depositor:
            order.DepositorName = depositor
        log_msg = f"결제상태: {val} ({method or ''})"
        log_type = "결제"

    db.commit()
    if log_msg:
        log_history(db, order_id, log_type, log_msg, auth["name"])
    return build_view_redirect(order_id, auth, access_key)


def save_order_info_action(
    db: Session,
    auth: dict,
    order_id: int,
    memo: Optional[str],
    inflow_route: Optional[str] = None,
    inflow_detail: Optional[str] = None,
    as_reason: Optional[str] = None,
    as_responsibility: Optional[str] = None,
    as_charge_type: Optional[str] = None,
    as_cost: Optional[str] = None,
    as_note: Optional[str] = None,
    discount: Optional[str] = None,
    deposit: Optional[str] = None,
    vat: Optional[str] = None,
    method: Optional[str] = None,
    recalc_order_amounts_fn=None,
):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return None

    changes = []
    extra = get_or_create_order_extra_info(db, order_id)

    if discount is not None:
        val = float(str(discount).replace(",", "")) if discount else 0
        if order.DiscountAmount != val:
            order.DiscountAmount = val
            changes.append(f"???({int(val):,})")
    if deposit is not None:
        val = float(str(deposit).replace(",", "")) if deposit else 0
        if order.DepositAmount != val:
            order.DepositAmount = val
            changes.append(f"???({int(val):,})")
    if vat is not None:
        val = "Y" if vat == "true" else "N"
        if order.IsVatIncluded != val:
            order.IsVatIncluded = val
            changes.append("VAT??" if val == "Y" else "VAT??")
    if method is not None and order.PaymentMethod != method:
        order.PaymentMethod = method
        changes.append(f"????({method})")
    if memo is not None and order.Memo != memo:
        order.Memo = memo
        changes.append("????")

    if extra is not None and inflow_route is not None and extra.InflowRoute != (inflow_route or None):
        extra.InflowRoute = inflow_route or None
        changes.append("????")
    if extra is not None and inflow_detail is not None and extra.InflowDetail != (inflow_detail or None):
        extra.InflowDetail = inflow_detail or None
        changes.append("????")
    if extra is not None and as_reason is not None and extra.ASReason != (as_reason or None):
        extra.ASReason = as_reason or None
        changes.append("A/S??")
    if extra is not None and as_responsibility is not None and extra.ASResponsibility != (as_responsibility or None):
        extra.ASResponsibility = as_responsibility or None
        changes.append("A/S??")
    if extra is not None and as_charge_type is not None and extra.ASChargeType != (as_charge_type or None):
        extra.ASChargeType = as_charge_type or None
        changes.append("A/S????")
    if extra is not None and as_cost is not None:
        as_cost_val = float(str(as_cost).replace(",", "")) if str(as_cost).strip() else 0
        if float(extra.ASCost or 0) != as_cost_val:
            extra.ASCost = as_cost_val
            changes.append("A/S??")
    if extra is not None and as_note is not None and extra.ASNote != (as_note or None):
        extra.ASNote = as_note or None
        changes.append("A/S??")

    db.commit()
    if callable(recalc_order_amounts_fn):
        recalc_order_amounts_fn(db, order_id)
    if changes:
        log_history(db, order_id, "????", ", ".join(changes), auth["name"])
    return "OK"


def update_order_basic_info_action(
    db: Session,
    current_user,
    order_id: int,
    customer_name: Optional[str],
    address: Optional[str],
    phone: Optional[str],
):
    order = db.query(models.Order).filter(
        models.Order.OrderID == int(order_id),
        models.Order.CompanyID == current_user.company_id,
    ).first()
    if not order:
        return None

    changes = []
    if customer_name and order.CustomerName != customer_name:
        changes.append(f"이름: {customer_name}")
        order.CustomerName = customer_name
    if phone and order.PhoneNumber != phone:
        changes.append("연락처")
        order.PhoneNumber = phone
    if address and order.Address != address:
        changes.append("주소")
        order.Address = address

    db.commit()
    if changes:
        log_history(db, order.OrderID, "정보수정", ", ".join(changes), current_user.Name)
    return RedirectResponse(url=f"/view/{order_id}", status_code=303)


def delete_order_action(db: Session, current_user, order_id: int):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == current_user.company_id,
    ).first()
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID
    ).first()
    if not member or (member.RoleName != "대표" and not member.Perm_DeleteOrder):
        return JSONResponse(
            content={"status": "error", "msg": "삭제 권한이 없습니다."},
            status_code=403,
        )

    db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).delete()
    db.query(models.OrderHistory).filter(models.OrderHistory.OrderID == order_id).delete()
    db.query(models.OrderPhoto).filter(models.OrderPhoto.OrderID == order_id).delete()
    db.delete(order)
    db.commit()
    return {"status": "ok"}


def save_signature_action(db: Session, order_id: int, image_data: str):
    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order:
        return {"status": "error", "msg": "주문을 찾을 수 없습니다."}
    if not image_data or len(image_data) < 100:
        return {"status": "error", "msg": "서명 데이터가 비어있습니다."}

    order.ClientSignature = image_data
    db.commit()
    log_history(db, order_id, "서명완료", "고객 전자 서명 (현장)", "고객")
    return {"status": "ok"}
