import json
import os
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

import models
from auth import get_current_user, get_user_or_key
from database import get_db
from services.item_route_service import recalc_order_amounts
from services.view_service import (
    backfill_order_managers_for_company,
    backfill_order_managers_for_order,
    WEEK_NAMES,
    build_display_dates,
    build_view_redirect,
    build_group_map,
    build_history_list,
    build_site_check_text,
    delete_order_action,
    enrich_order,
    get_or_create_curtain_deductions,
    get_permissions_for_auth,
    get_role_name,
    get_status_class,
    history_editable,
    init_default_check_items,
    item_categories_for_ui,
    item_category_modes_for_ui,
    calc_final_price,
    save_order_info_action,
    save_signature_action,
    format_number,
    log_history,
    pick_external_target,
    safe_int,
    safe_num,
    summarize_order_items,
    list_order_manager_ids,
    list_order_manager_names,
    update_order_basic_info_action,
    update_order_date_action,
    update_order_manager_action,
    update_schedule_action,
    update_status_action,
)


router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ManagersUpdateReq(BaseModel):
    order_id: int
    manager_ids: List[int]


class ScheduleUpdate(BaseModel):
    order_id: int
    new_date: str


class DateUpdateReq(BaseModel):
    order_id: int
    target: str
    date_str: str


class SignatureReq(BaseModel):
    order_id: int
    image_data: str


def format_comma(value):
    try:
        return "{:,.0f}".format(float(value or 0))
    except Exception:
        return "0"


def format_time_pretty(dt):
    if not isinstance(dt, datetime):
        return ""
    hour = dt.hour
    minute = dt.minute
    ampm = "오후" if hour >= 12 else "오전"
    if hour > 12:
        hour -= 12
    if hour == 0:
        hour = 12
    return f"{ampm} {hour}:{minute:02d}"


def format_phone(value):
    if not value:
        return ""
    phone = str(value).replace("-", "")
    if len(phone) == 11:
        return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
    return value


def format_smart(value):
    if value is None or value == "":
        return ""
    try:
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except Exception:
        return str(value)


templates.env.globals.update(
    {
        "safe_num": safe_num,
        "safe_int": safe_int,
        "int": int,
        "calc_final_price": calc_final_price,
    }
)
templates.env.filters.update(
    {
        "format_comma": format_comma,
        "format_number": format_number,
        "format_time_pretty": format_time_pretty,
        "format_phone": format_phone,
        "format_smart": format_smart,
    }
)


@router.get("/view")
@router.get("/view/{id}", response_class=HTMLResponse)
async def view_order(request: Request, id: int = None, db: Session = Depends(get_db)):
    if id is None:
        id_param = request.query_params.get("id")
        id = int(id_param) if id_param and id_param.isdigit() else 0

    auth = await get_user_or_key(request, db)
    if not auth:
        return RedirectResponse(url="/login", status_code=303)

    order = db.query(models.Order).filter(
        models.Order.OrderID == id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return HTMLResponse("<h1>주문을 찾을 수 없거나 접근 권한이 없습니다.</h1>", status_code=404)

    order = enrich_order(order)
    items = db.query(models.OrderItem).filter(models.OrderItem.OrderID == id).order_by(
        models.OrderItem.SortOrder, models.OrderItem.ItemID
    ).all()
    histories = db.query(models.OrderHistory).filter(
        models.OrderHistory.OrderID == id
    ).order_by(models.OrderHistory.HistoryID.desc()).all()
    members = db.query(models.CompanyMember).filter(
        models.CompanyMember.CompanyID == auth["company_id"]
    ).all()

    perms = get_permissions_for_auth(db, auth)
    group_map = build_group_map(items)
    visit_date, const_date = build_display_dates(order)

    init_default_check_items(db, auth["company_id"])
    check_items = db.query(models.SiteCheckItem).filter(
        models.SiteCheckItem.CompanyID == auth["company_id"]
    ).order_by(models.SiteCheckItem.SortOrder).all()

    my_role = get_role_name(db, auth)
    ded_map = get_or_create_curtain_deductions(db, auth["company_id"])
    item_categories = item_categories_for_ui()
    item_category_modes = item_category_modes_for_ui(item_categories)
    is_external = auth["type"] == "external"
    access_key = request.query_params.get("key") if is_external else ""
    company = order.company
    company_name = (company.CompanyName if company and company.CompanyName else "").strip()
    company_bank_info = (company.BankInfo if company and company.BankInfo else "").strip()
    if backfill_order_managers_for_order(db, order):
        db.commit()
    selected_manager_ids = list_order_manager_ids(db, order.OrderID)
    manager_names = list_order_manager_names(db, order.OrderID)
    display_manager_name = ", ".join(manager_names)

    return templates.TemplateResponse(
        "view.html",
        {
            "request": request,
            "order": order,
            "items": items,
            "histories": histories,
            "members": members,
            "perms": perms,
            "curtain_deduct_sokji": ded_map.get("속지", 4.0),
            "curtain_deduct_geotji": ded_map.get("겉지", 3.5),
            "current_user_id": auth["member_id"],
            "current_user_name": auth["name"],
            "current_user_role": my_role,
            "check_items": check_items,
            "g_json_str": json.dumps(group_map, ensure_ascii=False),
            "visit_date": visit_date,
            "visit_time": order.VisitDate.strftime("%H:%M") if order.VisitDate else "",
            "const_date": const_date,
            "const_time": order.ConstructionDate.strftime("%H:%M") if order.ConstructionDate else "",
            "item_categories": item_categories,
            "item_categories_json": json.dumps(item_categories, ensure_ascii=False),
            "item_category_modes_json": json.dumps(item_category_modes, ensure_ascii=False),
            "current_member_type": auth["type"],
            "is_external": is_external,
            "access_key": access_key,
            "company_name": company_name,
            "company_bank_info": company_bank_info,
            "selected_manager_ids": selected_manager_ids,
            "display_manager_name": display_manager_name,
        },
    )


@router.get("/w/{access_key}", response_class=HTMLResponse)
async def external_view(
    request: Request,
    access_key: str,
    search_date: str = Query(None),
    db: Session = Depends(get_db),
):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.AccessKey == access_key
    ).first()
    if not member:
        return HTMLResponse("<h1>유효하지 않은 링크입니다.</h1>", status_code=404)

    company = db.query(models.Company).filter(
        models.Company.CompanyID == member.CompanyID
    ).first()
    company_name = company.CompanyName if company else "미지정"

    backfill_order_managers_for_company(db, member.CompanyID)
    search_list = []
    if search_date:
        try:
            target_dt = datetime.strptime(search_date, "%Y-%m-%d").date()
            s_start = datetime.combine(target_dt, datetime.min.time())
            s_end = datetime.combine(target_dt, datetime.max.time())
            manager_order_ids = db.query(models.OrderManager.OrderID).filter(
                models.OrderManager.MemberID == member.ID
            )

            search_orders = db.query(models.Order).options(joinedload(models.Order.items)).filter(
                models.Order.CompanyID == member.CompanyID,
                models.Order.OrderID.in_(manager_order_ids),
                models.Order.ProgressStatus != "취소",
                or_(
                    models.Order.ConstructionDate.between(s_start, s_end),
                    models.Order.VisitDate.between(s_start, s_end),
                    models.Order.ASDate.between(s_start, s_end),
                    models.Order.RequestDate.between(s_start, s_end),
                ),
            ).all()

            for order in search_orders:
                target_date, display_type = pick_external_target(order, s_start, s_end)
                if not target_date:
                    continue

                recent_memos = db.query(models.OrderHistory).filter(
                    models.OrderHistory.OrderID == order.OrderID,
                    models.OrderHistory.LogType == "메모",
                ).order_by(models.OrderHistory.HistoryID.desc()).limit(10).all()

                search_list.append(
                    {
                        "order_id": order.OrderID,
                        "date_str": f"{target_date.month}/{target_date.day} (검색)",
                        "time_str": target_date.strftime("%H:%M"),
                        "type": display_type,
                        "type_class": get_status_class(display_type),
                        "name": order.CustomerName,
                        "addr": order.Address,
                        "phone": order.PhoneNumber,
                        "item_summary": summarize_order_items(order),
                        "memo": order.Memo,
                        "site_check": build_site_check_text(order),
                        "history_list": build_history_list(recent_memos),
                        "is_ordered": order.IsOrdered,
                        "is_received": order.IsReceived,
                        "is_waiting": order.IsWaiting,
                        "is_hold": order.IsHold,
                        "pay_stat": order.PaymentStatus,
                        "total_amount": f"{int(float(order.TotalAmount or 0)):,}" if member.Perm_ViewRevenue else "",
                    }
                )
        except Exception as exc:
            print(f"Search Error: {exc}")

    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=7), datetime.min.time())
    end_dt = datetime.combine(today + timedelta(days=60), datetime.min.time())
    exclude_stats = ["작업완료", "취소"]

    manager_order_ids = db.query(models.OrderManager.OrderID).filter(
        models.OrderManager.MemberID == member.ID
    )

    base_orders = db.query(models.Order).options(joinedload(models.Order.items)).filter(
        models.Order.CompanyID == member.CompanyID,
        models.Order.OrderID.in_(manager_order_ids),
        models.Order.ProgressStatus.notin_(exclude_stats),
        or_(
            models.Order.ConstructionDate.between(start_dt, end_dt),
            models.Order.VisitDate.between(start_dt, end_dt),
            models.Order.ASDate.between(start_dt, end_dt),
            models.Order.RequestDate.between(start_dt, end_dt),
        ),
    ).all()

    schedule_list = []
    for order in base_orders:
        target_date = order.ConstructionDate or order.ASDate or order.VisitDate or order.RequestDate
        if not target_date:
            continue

        recent_memos = db.query(models.OrderHistory).filter(
            models.OrderHistory.OrderID == order.OrderID,
            models.OrderHistory.LogType == "메모",
        ).order_by(models.OrderHistory.HistoryID.desc()).limit(10).all()

        schedule_list.append(
            {
                "order_id": order.OrderID,
                "date_str": f"{target_date.month}/{target_date.day} ({WEEK_NAMES[target_date.weekday()]})",
                "time_str": target_date.strftime("%H:%M"),
                "sort_key": target_date,
                "type": order.ProgressStatus,
                "type_class": get_status_class(order.ProgressStatus),
                "name": order.CustomerName,
                "addr": order.Address,
                "phone": order.PhoneNumber,
                "item_summary": summarize_order_items(order),
                "memo": order.Memo,
                "site_check": build_site_check_text(order),
                "history_list": build_history_list(recent_memos),
                "is_ordered": order.IsOrdered,
                "is_received": order.IsReceived,
                "is_waiting": order.IsWaiting,
                "is_hold": order.IsHold,
                "pay_stat": order.PaymentStatus,
            }
        )

    schedule_list.sort(key=lambda x: x["sort_key"])

    return templates.TemplateResponse(
        "external_view.html",
        {
            "request": request,
            "member": member,
            "company_name": company_name,
            "schedules": schedule_list,
            "search_schedules": search_list,
            "access_key": access_key,
            "search_date": search_date,
        },
    )


@router.get("/w/view/{order_id}", response_class=HTMLResponse)
async def external_order_detail(
    request: Request,
    order_id: int,
    key: str,
    db: Session = Depends(get_db),
):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.AccessKey == key
    ).first()
    if not member:
        return HTMLResponse("잘못된 접근입니다.", status_code=403)

    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order or order.CompanyID != member.CompanyID:
        return HTMLResponse("주문 정보를 찾을 수 없습니다.", status_code=404)

    items = db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).order_by(
        models.OrderItem.SortOrder.asc()
    ).all()
    histories = db.query(models.OrderHistory).filter(
        models.OrderHistory.OrderID == order_id
    ).order_by(models.OrderHistory.HistoryID.desc()).all()

    group_map = build_group_map(items)
    item_categories = item_categories_for_ui()
    item_category_modes = item_category_modes_for_ui(item_categories)
    company = order.company
    company_name = (company.CompanyName if company and company.CompanyName else "").strip()
    company_bank_info = (company.BankInfo if company and company.BankInfo else "").strip()

    visit_date = ""
    const_date = ""
    if order.VisitDate:
        visit_date = (
            f"{order.VisitDate.strftime('%y-%m-%d')}({WEEK_NAMES[order.VisitDate.weekday()]}) "
            f"{order.VisitDate.strftime('%H:%M')}"
        )
    if order.ConstructionDate:
        const_date = (
            f"{order.ConstructionDate.strftime('%y-%m-%d')}({WEEK_NAMES[order.ConstructionDate.weekday()]}) "
            f"{order.ConstructionDate.strftime('%H:%M')}"
        )

    return templates.TemplateResponse(
        "view.html",
        {
            "request": request,
            "order": order,
            "items": items,
            "histories": histories,
            "members": [],
            "perms": {
                "revenue": False,
                "staff": True,
                "schedule": True,
                "stats": False,
                "margin": False,
                "total": False,
            },
            "current_user_id": 0,
            "g_json_str": json.dumps(group_map, ensure_ascii=False),
            "visit_date": visit_date,
            "visit_time": "",
            "const_date": const_date,
            "const_time": "",
            "item_categories": item_categories,
            "item_categories_json": json.dumps(item_categories, ensure_ascii=False),
            "item_category_modes_json": json.dumps(item_category_modes, ensure_ascii=False),
            "is_external": True,
            "access_key": key,
            "company_name": company_name,
            "company_bank_info": company_bank_info,
        },
    )


@router.post("/api/order/update-manager")
def update_order_manager(
    req: ManagersUpdateReq,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return update_order_manager_action(db, current_user, req.order_id, req.manager_ids)


@router.post("/api/schedule/update")
async def update_schedule(
    data: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return update_schedule_action(db, current_user, data.order_id, data.new_date)


@router.post("/api/order/update-date")
async def update_order_date(
    request: Request,
    data: DateUpdateReq,
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(content={"status": "error", "msg": "권한 없음"}, status_code=403)
    return update_order_date_action(db, auth, data.order_id, data.target, data.date_str)


@router.get("/api/status/update")
async def update_status_api(
    request: Request,
    id: int,
    type: str,
    val: str,
    method: str = Query(None),
    bank: str = Query(None),
    depositor: str = Query(None),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return RedirectResponse(url=f"/view/{id}", status_code=303)
    return update_status_action(
        db,
        auth,
        id,
        type,
        val,
        method,
        bank,
        depositor,
        request.query_params.get("access_key"),
    )


@router.post("/api/order/save-info")
async def save_order_info(request: Request, db: Session = Depends(get_db)):
    auth = await get_user_or_key(request, db)
    if not auth:
        return Response(content="Unauthorized", status_code=403)

    form = await request.form()
    order_id = int(form.get("id"))
    memo = form.get("memo")
    discount = form.get("discount")
    deposit = form.get("deposit")
    vat = form.get("vat")
    method = form.get("method")

    result = save_order_info_action(
        db=db,
        auth=auth,
        order_id=order_id,
        memo=memo,
        discount=discount,
        deposit=deposit,
        vat=vat,
        method=method,
        recalc_order_amounts_fn=recalc_order_amounts,
    )
    if result is None:
        return Response(content="Order not found", status_code=404)
    return result


@router.post("/api/order/update-info")
async def update_order_basic_info(
    req: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        form = await req.form()
        order_id = form.get("order_id") or form.get("OrderID")
        c_name = form.get("customer_name") or form.get("CustomerName")
        addr = form.get("address") or form.get("Address")
        phone = form.get("phone") or form.get("PhoneNumber")

        if not order_id:
            return JSONResponse(status_code=400, content={"msg": "주문 번호 없음"})
        result = update_order_basic_info_action(
            db,
            current_user,
            order_id,
            c_name,
            addr,
            phone,
        )
        if result is None:
            return JSONResponse(status_code=404, content={"msg": "주문 없음"})
        return result
    except Exception as exc:
        return JSONResponse(status_code=500, content={"msg": str(exc)})


@router.post("/api/order/delete")
async def delete_order(
    order_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        return delete_order_action(db, current_user, order_id)
    except Exception as exc:
        db.rollback()
        print(f"삭제 에러: {exc}")
        return JSONResponse(content={"status": "error", "msg": str(exc)}, status_code=500)


@router.post("/api/order/save-signature")
async def save_signature(
    request: Request,
    req: SignatureReq,
    db: Session = Depends(get_db),
):
    try:
        return save_signature_action(db, req.order_id, req.image_data)
    except Exception as exc:
        print(f"[DEBUG] 서명 저장 에러: {exc}")
        return {"status": "error", "msg": str(exc)}


@router.get("/view-print/{order_id}", response_class=HTMLResponse)
async def view_print(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order:
        return HTMLResponse("주문을 찾을 수 없습니다.")

    items = db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).order_by(
        models.OrderItem.SortOrder, models.OrderItem.ItemID
    ).all()
    company = db.query(models.Company).filter(
        models.Company.CompanyID == order.CompanyID
    ).first()

    return templates.TemplateResponse(
        "view_print.html",
        {"request": request, "order": order, "items": items, "company": company, "today": date.today()},
    )


@router.post("/api/history/add")
async def add_history(
    request: Request,
    order_id: int = Form(...),
    log_type: str = Form(...),
    contents: str = Form(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return Response("Unauthorized", status_code=403)

    log_history(db, order_id, log_type, contents, auth["name"])
    form = await request.form()
    key = form.get("access_key") or ""
    url = f"/w/view/{order_id}?key={key}" if key else f"/view/{order_id}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/api/order/update-site-info")
async def update_site_info(request: Request, db: Session = Depends(get_db)):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse({"status": "error", "msg": "권한이 없습니다."}, status_code=403)

    form = await request.form()
    order_id = int(form.get("order_id"))
    new_surface = form.get("surface") or ""
    new_checklist = form.get("checklist") or ""

    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return JSONResponse({"status": "error", "msg": "주문이 없습니다."}, status_code=404)

    changes = []
    if (order.InstallSurface or "") != new_surface:
        changes.append(f"설치면 {new_surface}")
    if (order.ChecklistMemo or "") != new_checklist:
        short_check = (new_checklist[:30] + "..") if len(new_checklist) > 30 else new_checklist
        changes.append(f"체크리스트 {short_check}")

    order.InstallSurface = new_surface
    order.ChecklistMemo = new_checklist
    db.commit()

    if changes:
        log_history(db, order_id, "현장체크", " / ".join(changes), auth["name"])
    return {"status": "ok"}


@router.post("/api/history/delete")
async def delete_history(
    request: Request,
    history_id: int = Form(...),
    order_id: int = Form(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return Response("Unauthorized", status_code=403)

    history = db.query(models.OrderHistory).filter(
        models.OrderHistory.HistoryID == history_id
    ).first()
    if not history:
        return Response("Not Found", status_code=404)

    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order or order.CompanyID != auth["company_id"]:
        return Response("Unauthorized", status_code=403)

    if not history_editable(db, auth, history):
        return HTMLResponse(
            "<script>alert('삭제 권한이 없습니다.\\n본인이 작성한 글만 삭제할 수 있습니다.'); history.back();</script>"
        )

    db.delete(history)
    db.commit()

    form = await request.form()
    key = form.get("access_key") or ""
    url = f"/w/view/{order_id}?key={key}" if key else f"/view/{order_id}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/api/history/update")
async def update_history(
    request: Request,
    history_id: int = Form(...),
    order_id: int = Form(...),
    contents: str = Form(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return Response("Unauthorized", status_code=403)

    history = db.query(models.OrderHistory).filter(
        models.OrderHistory.HistoryID == history_id
    ).first()
    if not history:
        return Response("Not Found", status_code=404)

    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order or order.CompanyID != auth["company_id"]:
        return Response("Unauthorized", status_code=403)

    if not history_editable(db, auth, history):
        return HTMLResponse(
            "<script>alert('수정 권한이 없습니다.\\n본인이 작성한 글만 수정할 수 있습니다.'); history.back();</script>"
        )

    history.Contents = contents
    db.commit()

    form = await request.form()
    key = form.get("access_key") or ""
    url = f"/w/view/{order_id}?key={key}" if key else f"/view/{order_id}"
    return RedirectResponse(url=url, status_code=303)
