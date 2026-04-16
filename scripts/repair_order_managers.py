import argparse
import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import models
from database import SessionLocal
from services.view_service import (
    fill_unassigned_orders_with_representative,
    get_company_representative_member,
    list_order_manager_pairs,
    safe_int,
)


def _parse_dt(value: str | None):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    raise ValueError(f"invalid datetime: {value}")


def _parse_order_ids(raw: str | None):
    if not raw:
        return []
    return [safe_int(x) for x in str(raw).split(",") if safe_int(x)]


def main():
    parser = argparse.ArgumentParser(description="Fill unassigned orders with company representative")
    parser.add_argument("--company-id", type=int, default=0, help="Target company id")
    parser.add_argument("--order-ids", type=str, default="", help="Comma separated OrderID list")
    parser.add_argument("--regdate-from", type=str, default="", help="Filter OrderManagers.RegDate from")
    parser.add_argument("--regdate-to", type=str, default="", help="Filter OrderManagers.RegDate to")
    parser.add_argument("--limit", type=int, default=500, help="Max orders to inspect")
    parser.add_argument("--apply", action="store_true", help="Actually fill matched orders")
    args = parser.parse_args()

    order_ids = _parse_order_ids(args.order_ids)
    regdate_from = _parse_dt(args.regdate_from or None)
    regdate_to = _parse_dt(args.regdate_to or None)

    db = SessionLocal()
    try:
        query = db.query(models.Order)
        if args.company_id:
            query = query.filter(models.Order.CompanyID == args.company_id)
        if order_ids:
            query = query.filter(models.Order.OrderID.in_(order_ids))
        if regdate_from or regdate_to:
            reg_order_ids = db.query(models.OrderManager.OrderID)
            if regdate_from:
                reg_order_ids = reg_order_ids.filter(models.OrderManager.RegDate >= regdate_from)
            if regdate_to:
                reg_order_ids = reg_order_ids.filter(models.OrderManager.RegDate <= regdate_to)
            query = query.filter(models.Order.OrderID.in_(reg_order_ids))

        orders = query.order_by(models.Order.OrderID.asc()).limit(max(1, args.limit)).all()

        candidates = []
        for order in orders:
            manager_pairs = list_order_manager_pairs(db, order.OrderID)
            if manager_pairs:
                continue

            representative = get_company_representative_member(db, safe_int(getattr(order, "CompanyID", 0)))
            representative_id = safe_int(getattr(representative, "ID", 0))
            representative_name = str(getattr(representative, "Name", "") or "").strip()
            if not representative_id:
                continue

            row = {
                "order_id": order.OrderID,
                "company_id": order.CompanyID,
                "customer_name": order.CustomerName,
                "current_manager_id": 0,
                "current_order_managers": manager_pairs,
                "target_order_managers": [[representative_id, representative_name]],
            }
            candidates.append(row)

        repaired = 0
        if args.apply:
            result = fill_unassigned_orders_with_representative(
                db,
                company_id=(args.company_id or None),
                order_ids=order_ids or None,
                limit=max(1, args.limit),
            )
            repaired = safe_int(result.get("updated", 0))

        print(
            f"repair_order_managers candidates={len(candidates)} "
            f"repaired={repaired} apply={'Y' if args.apply else 'N'}"
        )
        for row in candidates[:50]:
            print(json.dumps(row, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
