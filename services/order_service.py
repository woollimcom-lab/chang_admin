from datetime import datetime

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import models
from services.view_service import sync_order_managers


async def create_order_action(req, db: Session, current_user: models.User):
    try:
        form = await req.form()

        c_name = form.get("CustomerName")
        r_date = form.get("RequestDate")
        r_type = form.get("RequestType")
        addr = form.get("Address")
        phone = form.get("PhoneNumber")

        print(f"[CREATE ORDER] customer={c_name} request_date={r_date} type={r_type}")

        if not c_name:
            return JSONResponse(status_code=400, content={"msg": "고객명을 입력해주세요."})

        member = db.query(models.CompanyMember).filter(
            models.CompanyMember.UserID == current_user.UserID
        ).first()
        if not member:
            return JSONResponse(status_code=403, content={"msg": "직원 정보를 찾을 수 없습니다."})

        final_date = datetime.now()
        if r_date and str(r_date).strip():
            dt_str = str(r_date).replace("T", " ")
            if len(dt_str) > 16:
                dt_str = dt_str[:19]
            try:
                final_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    final_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    final_date = datetime.now()

        new_order = models.Order(
            CompanyID=member.CompanyID,
            CustomerName=c_name,
            PhoneNumber=phone,
            Address=addr,
            RequestDate=final_date,
            ProgressStatus=(r_type if r_type else "견적상담"),
            VisitDate=(final_date if r_type == "방문상담" else None),
            PaymentStatus="미결제",
            PaymentMethod="미정",
            IsHold="N",
            IsWaiting="N",
            IsOrdered="N",
            IsReceived="N",
        )

        db.add(new_order)
        db.flush()
        sync_order_managers(db, new_order.OrderID, [member.ID])
        db.commit()

        print(f"[CREATE ORDER OK] order_id={new_order.OrderID}")
        return JSONResponse(content={"status": "ok", "mfor row in history_rev_query.all():sg": "등록되었습니다.", "order_id": new_order.OrderID})

    except Exception as e:
        db.rollback()
        print(f"[CREATE ORDER ERROR] {e}")
        return JSONResponse(status_code=500, content={"msg": f"오류: {str(e)}"})
