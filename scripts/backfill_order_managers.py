import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from database import SessionLocal
from services.view_service import audit_order_managers_batch, backfill_order_managers_batch


def main():
    parser = argparse.ArgumentParser(description="Backfill Orders -> OrderManagers")
    parser.add_argument("--company-id", type=int, default=0, help="Target company id")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per batch")
    parser.add_argument("--max-batches", type=int, default=0, help="Stop after N batches")
    parser.add_argument("--audit-after", action="store_true", help="Run audit after backfill")
    parser.add_argument("--audit-limit", type=int, default=1000, help="Audit sample size after backfill")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        changed = backfill_order_managers_batch(
            db,
            company_id=args.company_id or None,
            batch_size=max(1, args.batch_size),
            max_batches=(args.max_batches or None),
        )
        print(f"backfill_order_managers changed={changed} (includes shadow sync)")
        if args.audit_after:
            result = audit_order_managers_batch(
                db,
                company_id=args.company_id or None,
                limit=max(1, args.audit_limit),
            )
            summary = result["summary"]
            print(
                "audit_after "
                f"checked={summary['checked']} "
                f"missing_links={summary['missing_links']} "
                f"shadow_mismatch={summary['shadow_mismatch']} "
                f"legacy_name_unmatched={summary['legacy_name_unmatched']}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
