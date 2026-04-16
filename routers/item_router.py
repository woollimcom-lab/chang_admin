from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

import models
from auth import get_current_user, get_user_or_key
from database import get_db
from services.item_route_service import recalc_order_amounts, save_item as save_item_service


router = APIRouter()


@router.post("/api/item/save")
async def save_item(request: Request, db: Session = Depends(get_db)):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})
    return await save_item_service(request, db, auth)


@router.post("/api/item/delete")
async def delete_item(
    item_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    item = db.query(models.OrderItem).filter(
        models.OrderItem.ItemID == item_id,
        models.Order.CompanyID == current_user.company_id,
    ).first()

    if not item:
        return HTMLResponse("삭제할 품목을 찾을 수 없습니다.", status_code=404)

    order_id = item.OrderID
    group_id = item.GroupID

    if group_id:
        db.query(models.OrderItem).filter(models.OrderItem.GroupID == group_id).delete()
    else:
        db.delete(item)

    db.commit()
    recalc_order_amounts(db, order_id)
    return RedirectResponse(url=f"/view/{order_id}", status_code=303)


@router.get("/api/item/update-step")
def update_item_step(
    id: int,
    step: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    item = db.query(models.OrderItem).filter(models.OrderItem.ItemID == id).first()

    if not item:
        return JSONResponse(
            content={"status": "error", "msg": "해당 품목을 찾을 수 없습니다."},
            status_code=404,
        )

    item.ItemStep = step
    db.commit()
    return {"status": "ok"}


@router.post("/api/item/reorder")
async def action_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    form = await request.form()
    ids_str = form.get("ids")
    if not ids_str:
        return JSONResponse({"result": "fail"})

    ids = ids_str.split(",")
    for idx, item_id in enumerate(ids):
        if item_id.isdigit():
            db.query(models.OrderItem).filter(models.OrderItem.ItemID == int(item_id)).update(
                {"SortOrder": idx + 1}
            )

    db.commit()
    return JSONResponse({"result": "ok"})
