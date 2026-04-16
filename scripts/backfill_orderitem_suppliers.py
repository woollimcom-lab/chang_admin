import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from database import SessionLocal
from services.item_route_service import backfill_order_item_supplier_links, safe_int


def _parse_order_ids(raw: str | None):
    if not raw:
        return []
    return [safe_int(x) for x in str(raw).split(",") if safe_int(x)]


def main():
    parser = argparse.ArgumentParser(description="Backfill OrderItems supplier_id inside Attributes")
    parser.add_argument("--company-id", type=int, default=0, help="Target company id")
    parser.add_argument("--order-ids", type=str, default="", help="Comma separated OrderID list")
    parser.add_argument("--limit", type=int, default=1000, help="Max items to inspect")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = backfill_order_item_supplier_links(
            db,
            company_id=(args.company_id or None),
            order_ids=_parse_order_ids(args.order_ids) or None,
            limit=max(1, args.limit),
        )
        print(
            "backfill_orderitem_suppliers "
            f"checked={result.get('checked', 0)} "
            f"updated={result.get('updated', 0)} "
            f"skipped={result.get('skipped', 0)}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
