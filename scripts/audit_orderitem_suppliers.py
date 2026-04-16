import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from database import SessionLocal
from services.item_route_service import audit_order_item_supplier_links, safe_int


def _parse_order_ids(raw: str | None):
    if not raw:
        return []
    return [safe_int(x) for x in str(raw).split(",") if safe_int(x)]


def main():
    parser = argparse.ArgumentParser(description="Audit OrderItems supplier links")
    parser.add_argument("--company-id", type=int, default=0, help="Target company id")
    parser.add_argument("--order-ids", type=str, default="", help="Comma separated OrderID list")
    parser.add_argument("--limit", type=int, default=1000, help="Max items to inspect")
    parser.add_argument("--json", action="store_true", help="Print issue rows as JSON")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = audit_order_item_supplier_links(
            db,
            company_id=(args.company_id or None),
            order_ids=_parse_order_ids(args.order_ids) or None,
            limit=max(1, args.limit),
        )
        summary = result.get("summary", {})
        issues = result.get("issues", [])
        unresolved_top = result.get("unresolved_top", [])
        print(
            "audit_orderitem_suppliers "
            f"checked={summary.get('checked', 0)} "
            f"missing_supplier_id={summary.get('missing_supplier_id', 0)} "
            f"multi_supplier={summary.get('multi_supplier', 0)} "
            f"unresolved_tokens={summary.get('unresolved_tokens', 0)}"
        )
        if unresolved_top:
            print(
                "unresolved_top="
                + ", ".join(f"{name}:{count}" for name, count in unresolved_top[:10])
            )
        if args.json:
            for row in issues[:100]:
                print(json.dumps(row, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
