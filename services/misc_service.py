from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


def debug_index_force_action(db: Session):
    try:
        inspector = inspect(db.bind)
        with db.bind.begin() as conn:
            if "IsActive" not in [c["name"] for c in inspector.get_columns("erp_supplier_transactions")]:
                conn.execute(text("ALTER TABLE erp_supplier_transactions ADD COLUMN IsActive BOOLEAN DEFAULT 1"))

            if "IsActive" not in [c["name"] for c in inspector.get_columns("field_expenses")]:
                conn.execute(text("ALTER TABLE field_expenses ADD COLUMN IsActive BOOLEAN DEFAULT 1"))

            if "IsActive" not in [c["name"] for c in inspector.get_columns("erp_suppliers")]:
                conn.execute(text("ALTER TABLE erp_suppliers ADD COLUMN IsActive BOOLEAN DEFAULT 1"))

        return {"status": "성공", "msg": "DB 컬럼 생성 및 최적화가 완료되었습니다. 이제 API가 정상 동작합니다."}
    except Exception as e:
        return {"status": "실패", "msg": str(e)}
