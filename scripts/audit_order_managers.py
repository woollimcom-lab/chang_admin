import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from database import SessionLocal
from services.view_service import audit_order_managers_batch


def main():
    parser = argparse.ArgumentParser(description="Audit Orders <-> OrderManagers migration")
    parser.add_argument("--company-id", type=int, default=0, help="Target company id")
    parser.add_argument("--limit", type=int, default=1000, help="Orders to inspect")
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 1 when issues exist")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = audit_order_managers_batch(
            db,
            company_id=args.company_id or None,
            limit=max(1, args.limit),
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        summary = result["summary"]
        print(
            "audit_order_managers "
            f"checked={summary['checked']} "
            f"missing_links={summary['missing_links']} "
            f"shadow_mismatch={summary['shadow_mismatch']} "
            f"legacy_name_unmatched={summary['legacy_name_unmatched']}"
        )

        for issue in result["issues"][:30]:
            print(json.dumps(issue, ensure_ascii=False))
        if args.fail_on_issues and result["issues"]:
            raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
