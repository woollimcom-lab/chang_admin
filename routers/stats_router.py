from collections import Counter
from datetime import datetime
import calendar
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import get_db
import models


router = APIRouter(prefix="/api/stats", tags=["Stats"])

DONE_STATUSES = ("시공완료", "작업완료")
QUOTE_STATUSES = ("견적상담", "방문상담")
PAID_STATUS = "입금완료"
CANCEL_STATUS = "취소"
CONSTRUCTION_PENDING_STATUS = "시공예정"
UNCATEGORIZED_LABEL = "미분류"
UNKNOWN_MEMBER_LABEL = "미지정"

AS_LEAKAGE_KEYWORDS = (
    "a/s",
    "as",
    "수선",
    "재단",
    "재방문",
    "수리",
    "하자",
    "교체",
)
COMMON_EXPENSE_KEYWORDS = (
    "부가세",
    "vat",
    "관리비",
    "세금",
    "공과금",
    "공통",
)
MARKETING_CHANNEL_RULES = [
    ("블로그", ("#블로그", "블로그", "blog", "네이버블로그")),
    ("지인소개", ("#지인", "지인", "소개", "추천", "지인소개")),
    ("당근", ("#당근", "당근", "당근마켓", "carrot")),
    ("워크인", ("#워크인", "워크인", "매장방문", "방문고객")),
    ("인스타", ("#인스타", "인스타", "instagram", "insta")),
    ("네이버", ("#네이버", "네이버", "naver")),
    ("카카오", ("#카카오", "카카오", "카톡", "kakao")),
]


def get_ym_str(year: int, month: int, diff: int) -> str:
    new_month = month - diff
    new_year = year
    while new_month <= 0:
        new_month += 12
        new_year -= 1
    return f"{new_year}-{new_month:02d}"


def normalize_text(value) -> str:
    return str(value or "").strip().lower()


def is_active_filter(model):
    if hasattr(model, "IsActive"):
        return or_(model.IsActive == True, model.IsActive.is_(None))
    return None


def apply_active_filter(query, model):
    active_filter = is_active_filter(model)
    if active_filter is not None:
        query = query.filter(active_filter)
    return query


def is_common_expense(category: str) -> bool:
    category_text = normalize_text(category)
    return any(keyword in category_text for keyword in COMMON_EXPENSE_KEYWORDS)


def is_as_leakage_expense(category: str, memo: str) -> bool:
    text = f"{normalize_text(category)} {normalize_text(memo)}"
    return any(keyword in text for keyword in AS_LEAKAGE_KEYWORDS)


def extract_marketing_channel(memo: str) -> str:
    text = normalize_text(memo)
    if not text:
        return UNCATEGORIZED_LABEL

    tag_match = re.search(r"#([가-힣a-zA-Z0-9_]+)", text)
    if tag_match:
        tagged = tag_match.group(1)
        for channel_name, keywords in MARKETING_CHANNEL_RULES:
            if any(keyword.replace("#", "") in tagged for keyword in keywords):
                return channel_name
        return tagged[:20]

    for channel_name, keywords in MARKETING_CHANNEL_RULES:
        if any(keyword in text for keyword in keywords):
            return channel_name
    return UNCATEGORIZED_LABEL


def month_range(year: int, month: int):
    start = datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


@router.get("/dashboard/trend")
def get_yearly_trend(
    year: int = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    target_year = now.year if year >= now.year else year
    target_month = now.month if year >= now.year else 12

    start_month = target_month - 23
    start_year = target_year
    while start_month <= 0:
        start_month += 12
        start_year -= 1

    scan_start_month = start_month - 12
    scan_start_year = start_year
    while scan_start_month <= 0:
        scan_start_month += 12
        scan_start_year -= 1

    start_trend = datetime(scan_start_year, scan_start_month, 1)
    end_trend = datetime(target_year, target_month, calendar.monthrange(target_year, target_month)[1], 23, 59, 59)

    orders_q = db.query(models.Order.ConstructionDate, models.Order.FinalAmount).filter(
        models.Order.CompanyID == current_user.company_id,
        models.Order.ProgressStatus.in_(DONE_STATUSES),
        models.Order.PaymentStatus == PAID_STATUS,
        models.Order.ConstructionDate >= start_trend,
        models.Order.ConstructionDate <= end_trend,
    )
    orders_q = apply_active_filter(orders_q, models.Order)

    rev_map = {}
    for row in orders_q.all():
        if row.ConstructionDate:
            ym = row.ConstructionDate.strftime("%Y-%m")
            rev_map[ym] = rev_map.get(ym, 0.0) + float(row.FinalAmount or 0)

    quote_q = db.query(
        func.coalesce(models.Order.ConstructionDate, models.Order.RequestDate).label("dt"),
        models.Order.TotalAmount,
    ).filter(
        models.Order.CompanyID == current_user.company_id,
        models.Order.ProgressStatus.in_(QUOTE_STATUSES),
        func.coalesce(models.Order.ConstructionDate, models.Order.RequestDate) >= start_trend,
        func.coalesce(models.Order.ConstructionDate, models.Order.RequestDate) <= end_trend,
    )
    quote_q = apply_active_filter(quote_q, models.Order)

    quote_map = {}
    for row in quote_q.all():
        if row.dt:
            ym = row.dt.strftime("%Y-%m")
            quote_map[ym] = quote_map.get(ym, 0.0) + float(row.TotalAmount or 0)

    expense_map = {}
    field_q = db.query(models.FieldExpense.ExpensedAt, models.FieldExpense.Amount).filter(
        models.FieldExpense.CompanyID == current_user.company_id,
        models.FieldExpense.ExpensedAt.between(start_trend, end_trend),
    )
    field_q = apply_active_filter(field_q, models.FieldExpense)
    for row in field_q.all():
        if row.ExpensedAt:
            ym = row.ExpensedAt.strftime("%Y-%m")
            expense_map[ym] = expense_map.get(ym, 0.0) + float(row.Amount or 0)

    tx_q = db.query(models.SupplierTransaction.TxDate, models.SupplierTransaction.Amount).filter(
        models.SupplierTransaction.CompanyID == current_user.company_id,
        models.SupplierTransaction.TxDate.between(start_trend, end_trend),
    )
    tx_q = apply_active_filter(tx_q, models.SupplierTransaction)
    for row in tx_q.all():
        if row.TxDate:
            ym = row.TxDate.strftime("%Y-%m")
            expense_map[ym] = expense_map.get(ym, 0.0) + float(row.Amount or 0)

    trend_data = []
    current_year, current_month = start_year, start_month
    for _ in range(24):
        ym_key = f"{current_year}-{current_month:02d}"
        cur_rev = rev_map.get(ym_key, 0.0)
        cur_exp = expense_map.get(ym_key, 0.0)
        bottleneck = quote_map.get(ym_key, 0.0)
        sum_6 = sum(rev_map.get(get_ym_str(current_year, current_month, idx), 0.0) for idx in range(6))
        sum_12 = sum(rev_map.get(get_ym_str(current_year, current_month, idx), 0.0) for idx in range(12))
        trend_data.append(
            {
                "year": current_year,
                "month": current_month,
                "label": f"{current_year}.{current_month:02d}",
                "cur_rev": cur_rev,
                "bottleneck": bottleneck,
                "avg_6_rev": sum_6 / 6.0,
                "avg_12_rev": sum_12 / 12.0,
                "net_profit": cur_rev - cur_exp,
            }
        )
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return trend_data


@router.get("/dashboard/monthly")
def get_monthly_financial_dashboard(
    year: int = Query(...),
    month: int = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date, end_date = month_range(year, month)

    base_filter = [models.Order.CompanyID == current_user.company_id]
    order_active_filter = is_active_filter(models.Order)
    if order_active_filter is not None:
        base_filter.append(order_active_filter)

    rev_res = db.query(func.sum(models.Order.FinalAmount), func.count(models.Order.OrderID)).filter(
        *base_filter,
        models.Order.ProgressStatus.in_(DONE_STATUSES),
        models.Order.PaymentStatus == PAID_STATUS,
        models.Order.ConstructionDate.between(start_date, end_date),
    ).first()
    cur_rev = float(rev_res[0] or 0)
    cur_rev_cnt = int(rev_res[1] or 0)

    recent_month_meta = []
    for diff in range(11, -1, -1):
        ym_key = get_ym_str(year, month, diff)
        ym_year, ym_month = map(int, ym_key.split("-"))
        recent_month_meta.append({"ym": ym_key, "label": f"{ym_year}.{ym_month:02d}"})
    history_start_year, history_start_month = map(int, recent_month_meta[0]["ym"].split("-"))
    history_start_date = datetime(history_start_year, history_start_month, 1)

    exp_filters = [
        models.FieldExpense.CompanyID == current_user.company_id,
        models.FieldExpense.ExpensedAt.between(start_date, end_date),
    ]
    field_active_filter = is_active_filter(models.FieldExpense)
    if field_active_filter is not None:
        exp_filters.append(field_active_filter)

    op_exps_raw = db.query(models.FieldExpense).filter(*exp_filters).order_by(models.FieldExpense.ExpensedAt.desc()).all()
    op_details = {}
    op_list = []
    expense_category_totals_map = {}
    as_expense_total = 0.0
    as_expense_count = 0
    for expense in op_exps_raw:
        category = (expense.Category or UNCATEGORIZED_LABEL).strip() or UNCATEGORIZED_LABEL
        amount = float(expense.Amount or 0)
        op_details[category] = op_details.get(category, 0.0) + amount
        if category not in expense_category_totals_map:
            expense_category_totals_map[category] = {"name": category, "amount": 0.0, "count": 0, "member_ids": set()}
        expense_category_totals_map[category]["amount"] += amount
        expense_category_totals_map[category]["count"] += 1
        member_id = int(getattr(expense, "MemberID", 0) or 0)
        if member_id > 0:
            expense_category_totals_map[category]["member_ids"].add(member_id)
        op_list.append(
            {
                "date": expense.ExpensedAt.strftime("%m/%d") if expense.ExpensedAt else "",
                "name": category,
                "amount": amount,
                "memo": expense.Memo or "",
            }
        )
        if is_as_leakage_expense(category, expense.Memo):
            as_expense_total += amount
            as_expense_count += 1
    op_exp = sum(op_details.values())

    history_filters = [
        models.FieldExpense.CompanyID == current_user.company_id,
        models.FieldExpense.ExpensedAt.between(history_start_date, end_date),
    ]
    if field_active_filter is not None:
        history_filters.append(field_active_filter)
    history_op_exps = db.query(models.FieldExpense).filter(*history_filters).all()

    member_ids = sorted({int(expense.MemberID or 0) for expense in history_op_exps if int(expense.MemberID or 0) > 0})
    member_lookup = {}
    if member_ids:
        members = db.query(models.CompanyMember).filter(
            models.CompanyMember.CompanyID == current_user.company_id,
            models.CompanyMember.ID.in_(member_ids),
        ).all()
        member_lookup = {int(member.ID): (member.Name or "").strip() for member in members}

    member_month_expense_map = {}
    expense_category_monthly_map = {}
    member_as_expense_map = {}
    for expense in history_op_exps:
        if not expense.ExpensedAt:
            continue
        member_id = int(expense.MemberID or 0)
        member_name = member_lookup.get(member_id) or UNKNOWN_MEMBER_LABEL
        bucket_key = member_id if member_id > 0 else f"unknown:{member_name}"
        ym_key = expense.ExpensedAt.strftime("%Y-%m")
        category = (expense.Category or UNCATEGORIZED_LABEL).strip() or UNCATEGORIZED_LABEL
        amount = float(expense.Amount or 0)

        expense_category_monthly_map.setdefault(ym_key, {})
        expense_category_monthly_map[ym_key][category] = expense_category_monthly_map[ym_key].get(category, 0.0) + amount

        if is_common_expense(category):
            continue

        member_month_expense_map.setdefault(bucket_key, {})
        member_month_expense_map[bucket_key].setdefault(ym_key, {"amount": 0.0, "category_amounts": {}})
        member_month_expense_map[bucket_key][ym_key]["amount"] += amount
        member_month_expense_map[bucket_key][ym_key]["category_amounts"][category] = (
            member_month_expense_map[bucket_key][ym_key]["category_amounts"].get(category, 0.0) + amount
        )

        if is_as_leakage_expense(category, expense.Memo):
            member_as_expense_map.setdefault(bucket_key, {"amount": 0.0, "count": 0, "details": []})
            member_as_expense_map[bucket_key]["amount"] += amount
            member_as_expense_map[bucket_key]["count"] += 1
            member_as_expense_map[bucket_key]["details"].append(
                {
                    "date": expense.ExpensedAt.strftime("%m/%d") if expense.ExpensedAt else "",
                    "category": category,
                    "amount": amount,
                    "memo": expense.Memo or "",
                    "order_id": int(getattr(expense, "OrderID", 0) or 0),
                }
            )

    order_manager_count_sq = db.query(
        models.OrderManager.OrderID,
        func.count(models.OrderManager.MemberID).label("manager_count"),
    ).group_by(models.OrderManager.OrderID).subquery()

    history_rev_query = db.query(
        models.OrderManager.MemberID.label("member_id"),
        models.Order.ConstructionDate.label("construction_date"),
        models.Order.FinalAmount.label("final_amount"),
        order_manager_count_sq.c.manager_count,
    ).join(
        models.Order, models.Order.OrderID == models.OrderManager.OrderID
    ).outerjoin(
        order_manager_count_sq, models.Order.OrderID == order_manager_count_sq.c.OrderID
    ).filter(
        models.Order.CompanyID == current_user.company_id,
        models.Order.ProgressStatus.in_(DONE_STATUSES),
        models.Order.PaymentStatus == PAID_STATUS,
        models.Order.ConstructionDate.between(history_start_date, end_date),
    )
    history_rev_query = apply_active_filter(history_rev_query, models.Order)

    member_month_revenue_map = {}
    for row in history_rev_query.all():
        member_id = int(getattr(row, "member_id", 0) or 0)
        construction_date = getattr(row, "construction_date", None)
        if member_id <= 0 or not construction_date:
            continue
        ym_key = construction_date.strftime("%Y-%m")
        manager_count = int(getattr(row, "manager_count", 1) or 1)
        final_amount = float(getattr(row, "final_amount", 0) or 0)
        shared_amount = final_amount / manager_count if manager_count > 0 else final_amount
        member_month_revenue_map.setdefault(member_id, {})
        member_month_revenue_map[member_id].setdefault(ym_key, {"total": 0.0, "solo": 0.0, "collab": 0.0})
        member_month_revenue_map[member_id][ym_key]["total"] += shared_amount
        if manager_count == 1:
            member_month_revenue_map[member_id][ym_key]["solo"] += shared_amount
        else:
            member_month_revenue_map[member_id][ym_key]["collab"] += shared_amount

    manager_rev_query = db.query(
        models.OrderManager.MemberID.label("member_id"),
        models.OrderManager.IsPrimary.label("is_primary"),
        models.Order.FinalAmount.label("final_amount"),
        order_manager_count_sq.c.manager_count,
    ).join(
        models.Order, models.Order.OrderID == models.OrderManager.OrderID
    ).outerjoin(
        order_manager_count_sq, models.Order.OrderID == order_manager_count_sq.c.OrderID
    ).filter(
        models.Order.CompanyID == current_user.company_id,
        models.Order.ProgressStatus.in_(DONE_STATUSES),
        models.Order.PaymentStatus == PAID_STATUS,
        models.Order.ConstructionDate.between(start_date, end_date),
    )
    manager_rev_query = apply_active_filter(manager_rev_query, models.Order)
    manager_rev_rows = manager_rev_query.all()

    member_current_rev_map = {}
    for row in manager_rev_rows:
        member_id = int(getattr(row, "member_id", 0) or 0)
        if member_id <= 0:
            continue
        manager_count = int(getattr(row, "manager_count", 1) or 1)
        final_amount = float(getattr(row, "final_amount", 0) or 0)
        shared_amount = final_amount / manager_count if manager_count > 0 else final_amount
        member_current_rev_map.setdefault(
            member_id,
            {"shared_revenue": 0.0, "primary_revenue": 0.0, "shared_count": 0, "primary_count": 0},
        )
        member_current_rev_map[member_id]["shared_revenue"] += shared_amount
        member_current_rev_map[member_id]["shared_count"] += 1
        if getattr(row, "is_primary", False):
            member_current_rev_map[member_id]["primary_revenue"] += final_amount
            member_current_rev_map[member_id]["primary_count"] += 1

    member_expense_map = {}
    expense_category_member_breakdown_map = {}
    for expense in op_exps_raw:
        member_id = int(expense.MemberID or 0)
        member_name = member_lookup.get(member_id) or UNKNOWN_MEMBER_LABEL
        bucket_key = member_id if member_id > 0 else f"unknown:{member_name}"
        category = (expense.Category or UNCATEGORIZED_LABEL).strip() or UNCATEGORIZED_LABEL
        if is_common_expense(category):
            continue
        member_expense_map.setdefault(
            bucket_key,
            {
                "member_key": bucket_key,
                "member_id": member_id,
                "member_name": member_name,
                "total_amount": 0.0,
                "count": 0,
                "categories": {},
                "details": [],
            },
        )
        amount = float(expense.Amount or 0)
        member_expense_map[bucket_key]["total_amount"] += amount
        member_expense_map[bucket_key]["count"] += 1
        member_expense_map[bucket_key]["categories"][category] = (
            member_expense_map[bucket_key]["categories"].get(category, 0.0) + amount
        )
        member_expense_map[bucket_key]["details"].append(
            {
                "date": expense.ExpensedAt.strftime("%m/%d") if expense.ExpensedAt else "",
                "category": category,
                "amount": amount,
                "memo": expense.Memo or "",
            }
        )

    for member_id, revenue_info in member_current_rev_map.items():
        member_name = member_lookup.get(member_id) or f"#{member_id}"
        member_expense_map.setdefault(
            member_id,
            {
                "member_key": member_id,
                "member_id": member_id,
                "member_name": member_name,
                "total_amount": 0.0,
                "count": 0,
                "categories": {},
                "details": [],
            },
        )
        member_expense_map[member_id]["revenue_amount"] = float(revenue_info.get("shared_revenue", 0) or 0)
        member_expense_map[member_id]["primary_revenue_amount"] = float(revenue_info.get("primary_revenue", 0) or 0)
        member_expense_map[member_id]["order_count"] = int(revenue_info.get("shared_count", 0) or 0)
        member_expense_map[member_id]["primary_order_count"] = int(revenue_info.get("primary_count", 0) or 0)

    member_expenses = []
    expense_category_names = sorted(op_details.keys())
    for bucket_key, bucket in member_expense_map.items():
        sorted_categories = sorted(bucket["categories"].items(), key=lambda item: (-item[1], item[0]))
        revenue_amount = float(bucket.get("revenue_amount", 0) or 0)
        expense_amount = float(bucket.get("total_amount", 0) or 0)
        as_bucket = member_as_expense_map.get(bucket_key, {"amount": 0.0, "count": 0, "details": []})
        as_amount = float(as_bucket.get("amount", 0) or 0)

        monthly_series = []
        month_expense_map = member_month_expense_map.get(bucket_key, {})
        month_revenue_map = member_month_revenue_map.get(int(bucket.get("member_id", 0) or 0), {})
        for meta in recent_month_meta:
            month_expense = month_expense_map.get(meta["ym"], {})
            month_revenue = month_revenue_map.get(meta["ym"], {})
            monthly_series.append(
                {
                    "ym": meta["ym"],
                    "label": meta["label"],
                    "amount": float(month_expense.get("amount", 0) or 0),
                    "revenue_amount": float(month_revenue.get("total", 0) or 0),
                    "solo_revenue": float(month_revenue.get("solo", 0) or 0),
                    "collab_revenue": float(month_revenue.get("collab", 0) or 0),
                    "category_amounts": month_expense.get("category_amounts", {}),
                }
            )

        for category_name, category_amount in sorted_categories:
            expense_category_member_breakdown_map.setdefault(category_name, [])
            expense_category_member_breakdown_map[category_name].append(
                {
                    "member_id": bucket.get("member_id", 0),
                    "member_name": bucket.get("member_name", UNKNOWN_MEMBER_LABEL),
                    "amount": float(category_amount or 0),
                    "count": sum(1 for detail in bucket["details"] if detail.get("category") == category_name),
                    "revenue_amount": revenue_amount,
                }
            )

        member_expenses.append(
            {
                "member_id": bucket.get("member_id", 0),
                "member_name": bucket.get("member_name", UNKNOWN_MEMBER_LABEL),
                "total_amount": expense_amount,
                "count": bucket.get("count", 0),
                "top_categories": [name for name, _ in sorted_categories[:2]],
                "category_amounts": {name: amount for name, amount in sorted_categories},
                "revenue_amount": revenue_amount,
                "primary_revenue_amount": float(bucket.get("primary_revenue_amount", 0) or 0),
                "order_count": int(bucket.get("order_count", 0) or 0),
                "primary_order_count": int(bucket.get("primary_order_count", 0) or 0),
                "expense_ratio": (expense_amount / revenue_amount * 100) if revenue_amount > 0 else None,
                "as_leak_amount": as_amount,
                "as_leak_count": int(as_bucket.get("count", 0) or 0),
                "as_leak_ratio": (as_amount / revenue_amount * 100) if revenue_amount > 0 else None,
                "clean_install_rate": max(0.0, ((revenue_amount - as_amount) / revenue_amount) * 100) if revenue_amount > 0 else None,
                "as_leak_details": as_bucket.get("details", [])[:8],
                "contribution_rate": (revenue_amount / cur_rev * 100) if cur_rev > 0 else 0.0,
                "details": bucket.get("details", [])[:12],
                "monthly_series": monthly_series,
            }
        )
    member_expenses.sort(key=lambda item: (-item["total_amount"], item["member_name"]))

    expense_category_totals = sorted(
        [
            {
                "name": category_name,
                "amount": float(category_bucket["amount"] or 0),
                "count": int(category_bucket["count"] or 0),
                "member_count": len(category_bucket["member_ids"]),
            }
            for category_name, category_bucket in expense_category_totals_map.items()
        ],
        key=lambda item: (-item["amount"], item["name"]),
    )
    for category_name in list(expense_category_member_breakdown_map.keys()):
        expense_category_member_breakdown_map[category_name].sort(key=lambda item: (-item["amount"], item["member_name"]))

    expense_category_monthly = []
    for meta in recent_month_meta:
        categories = expense_category_monthly_map.get(meta["ym"], {})
        expense_category_monthly.append(
            {
                "ym": meta["ym"],
                "label": meta["label"],
                "total_amount": float(sum(categories.values()) or 0),
                "categories": categories,
            }
        )

    tx_filters = [
        models.SupplierTransaction.CompanyID == current_user.company_id,
        models.SupplierTransaction.TxDate.between(start_date, end_date),
    ]
    tx_active_filter = is_active_filter(models.SupplierTransaction)
    if tx_active_filter is not None:
        tx_filters.append(tx_active_filter)
    mat_txs_raw = (
        db.query(models.SupplierTransaction)
        .options(joinedload(models.SupplierTransaction.supplier))
        .filter(*tx_filters)
        .order_by(models.SupplierTransaction.TxDate.desc())
        .all()
    )
    mat_details = {}
    mat_list = []
    for tx in mat_txs_raw:
        supplier_name = tx.supplier.SupplierName if tx.supplier else UNKNOWN_MEMBER_LABEL
        amount = float(tx.Amount or 0)
        mat_details[supplier_name] = mat_details.get(supplier_name, 0.0) + amount
        mat_list.append(
            {
                "date": tx.TxDate.strftime("%m/%d") if tx.TxDate else "",
                "name": supplier_name,
                "amount": amount,
            }
        )
    mat_exp = sum(mat_details.values())

    time_bound_or = or_(
        models.Order.ConstructionDate.between(start_date, end_date),
        models.Order.RequestDate.between(start_date, end_date),
    )

    quote_res = db.query(func.sum(models.Order.TotalAmount), func.count(models.Order.OrderID)).filter(
        *base_filter,
        models.Order.ProgressStatus.in_(QUOTE_STATUSES),
        models.Order.RequestDate.between(start_date, end_date),
    ).first()
    quote_rev = float(quote_res[0] or 0)
    quote_cnt = int(quote_res[1] or 0)

    bottleneck_res = db.query(func.sum(models.Order.TotalAmount), func.count(models.Order.OrderID)).filter(
        *base_filter,
        or_(
            models.Order.IsHold == "Y",
            models.Order.IsWaiting == "Y",
            models.Order.ProgressStatus == CONSTRUCTION_PENDING_STATUS,
        ),
        time_bound_or,
        models.Order.ProgressStatus.notin_((*DONE_STATUSES, CANCEL_STATUS)),
    ).first()
    bottleneck_rev = float(bottleneck_res[0] or 0)
    bottleneck_cnt = int(bottleneck_res[1] or 0)

    unpaid_res = db.query(
        func.sum(models.Order.FinalAmount - func.coalesce(models.Order.DepositAmount, 0)),
        func.count(models.Order.OrderID),
    ).filter(
        *base_filter,
        models.Order.ProgressStatus.in_(DONE_STATUSES),
        models.Order.PaymentStatus != PAID_STATUS,
        models.Order.ConstructionDate.between(start_date, end_date),
    ).first()
    unpaid_rev = float(unpaid_res[0] or 0)
    unpaid_cnt = int(unpaid_res[1] or 0)

    orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.items))
        .filter(*base_filter, models.Order.ProgressStatus.in_(DONE_STATUSES), time_bound_or)
        .order_by(models.Order.ConstructionDate.desc(), models.Order.RequestDate.desc())
        .all()
    )
    order_list = [
        {
            "id": order.OrderID,
            "name": order.CustomerName,
            "amt": float(order.FinalAmount or 0),
            "date": (order.ConstructionDate or order.RequestDate).strftime("%m/%d") if (order.ConstructionDate or order.RequestDate) else "",
            "item_summary": ", ".join(
                [f"{name} {count}" for name, count in Counter([item.Category1 or item.Category for item in order.items if (item.Category1 or item.Category)]).items()]
            )
            if order.items
            else "\ud56d\ubaa9\uc5c6\uc74c",
            "is_paid": order.PaymentStatus == PAID_STATUS,
        }
        for order in orders
    ]

    marketing_channel_map = {}
    marketing_total_revenue = 0.0
    for order in orders:
        amount = float(order.FinalAmount or 0)
        channel = extract_marketing_channel(getattr(order, "Memo", ""))
        marketing_channel_map.setdefault(channel, {"channel": channel, "revenue": 0.0, "count": 0, "orders": []})
        marketing_channel_map[channel]["revenue"] += amount
        marketing_channel_map[channel]["count"] += 1
        marketing_channel_map[channel]["orders"].append(
            {
                "order_id": int(order.OrderID or 0),
                "customer_name": order.CustomerName or "",
                "amount": amount,
                "memo": getattr(order, "Memo", "") or "",
            }
        )
        marketing_total_revenue += amount
    marketing_channels = sorted(
        [
            {
                "channel": row["channel"],
                "revenue": float(row["revenue"] or 0),
                "count": int(row["count"] or 0),
                "avg_revenue": (float(row["revenue"] or 0) / int(row["count"] or 1)) if row["count"] else 0.0,
                "share_rate": ((float(row["revenue"] or 0) / marketing_total_revenue) * 100) if marketing_total_revenue > 0 else 0.0,
                "sample_orders": row["orders"][:3],
            }
            for row in marketing_channel_map.values()
        ],
        key=lambda item: (-item["revenue"], -item["avg_revenue"], item["channel"]),
    )
    best_avg_channel = max(marketing_channels, key=lambda item: item["avg_revenue"], default=None)
    best_volume_channel = max(marketing_channels, key=lambda item: item["revenue"], default=None)

    return {
        "summary": {
            "total_revenue": cur_rev,
            "cur_rev_cnt": cur_rev_cnt,
            "total_expense": op_exp + mat_exp,
            "op_exp": op_exp,
            "mat_exp": mat_exp,
            "net_profit": cur_rev - (op_exp + mat_exp),
        },
        "pipeline": {
            "quote": quote_rev,
            "quote_cnt": quote_cnt,
            "bottleneck": bottleneck_rev,
            "bottleneck_cnt": bottleneck_cnt,
            "unpaid": unpaid_rev,
            "unpaid_cnt": unpaid_cnt,
        },
        "expense_details": {"op": op_details, "mat": mat_details},
        "expense_list": {"op": op_list, "mat": mat_list},
        "as_monitor": {
            "total_amount": as_expense_total,
            "count": as_expense_count,
            "ratio_vs_expense": (as_expense_total / op_exp * 100) if op_exp > 0 else 0.0,
            "ratio_vs_revenue": (as_expense_total / cur_rev * 100) if cur_rev > 0 else 0.0,
        },
        "marketing_channels": marketing_channels,
        "marketing_summary": {
            "total_revenue": marketing_total_revenue,
            "channel_count": len(marketing_channels),
            "best_avg_channel": best_avg_channel,
            "best_volume_channel": best_volume_channel,
            "unclassified_count": next((item["count"] for item in marketing_channels if item["channel"] == UNCATEGORIZED_LABEL), 0),
        },
        "member_expenses": member_expenses,
        "expense_category_names": expense_category_names,
        "expense_category_totals": expense_category_totals,
        "expense_category_member_breakdown": expense_category_member_breakdown_map,
        "expense_category_monthly": expense_category_monthly,
        "metrics": {
            "margin": ((cur_rev - (op_exp + mat_exp)) / cur_rev * 100) if cur_rev > 0 else (0 if (op_exp + mat_exp) == 0 else -100)
        },
        "order_list": order_list,
    }
