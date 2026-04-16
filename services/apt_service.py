import math
from typing import List

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
from services.item_route_service import recalc_order_amounts


def _get_allowed_complex(db: Session, company_id: int, complex_id: int):
    return db.query(models.AptComplex).filter(
        models.AptComplex.ComplexID == complex_id,
        or_(
            models.AptComplex.CompanyID == company_id,
            models.AptComplex.CompanyID == None,
        ),
    ).first()


def _get_allowed_plan(db: Session, company_id: int, plan_id: int):
    return db.query(models.AptPlan).join(
        models.AptComplex,
        models.AptPlan.ComplexID == models.AptComplex.ComplexID,
    ).filter(
        models.AptPlan.PlanID == plan_id,
        or_(
            models.AptComplex.CompanyID == company_id,
            models.AptComplex.CompanyID == None,
        ),
    ).first()


def _get_allowed_window(db: Session, company_id: int, window_id: int):
    return db.query(models.WindowSize).join(
        models.AptPlan,
        models.WindowSize.PlanID == models.AptPlan.PlanID,
    ).join(
        models.AptComplex,
        models.AptPlan.ComplexID == models.AptComplex.ComplexID,
    ).filter(
        models.WindowSize.WindowID == window_id,
        or_(
            models.AptComplex.CompanyID == company_id,
            models.AptComplex.CompanyID == None,
        ),
    ).first()


def _get_writable_complex(db: Session, company_id: int, complex_id: int):
    return db.query(models.AptComplex).filter(
        models.AptComplex.ComplexID == complex_id,
        models.AptComplex.CompanyID == company_id,
    ).first()


def _get_writable_plan(db: Session, company_id: int, plan_id: int):
    return db.query(models.AptPlan).join(
        models.AptComplex,
        models.AptPlan.ComplexID == models.AptComplex.ComplexID,
    ).filter(
        models.AptPlan.PlanID == plan_id,
        models.AptComplex.CompanyID == company_id,
    ).first()


def _get_writable_window(db: Session, company_id: int, window_id: int):
    return db.query(models.WindowSize).join(
        models.AptPlan,
        models.WindowSize.PlanID == models.AptPlan.PlanID,
    ).join(
        models.AptComplex,
        models.AptPlan.ComplexID == models.AptComplex.ComplexID,
    ).filter(
        models.WindowSize.WindowID == window_id,
        models.AptComplex.CompanyID == company_id,
    ).first()


def get_apt_complexes_action(db: Session, company_id: int):
    complexes = db.query(models.AptComplex).filter(
        or_(
            models.AptComplex.CompanyID == company_id,
            models.AptComplex.CompanyID == None,
        )
    ).order_by(models.AptComplex.SortOrder.asc(), models.AptComplex.ComplexName.asc()).all()
    return [
        {
            "ComplexID": c.ComplexID,
            "ComplexName": c.ComplexName,
            "CompanyID": c.CompanyID,
            "is_writable": c.CompanyID == company_id,
        }
        for c in complexes
    ]


def get_apt_plans_action(db: Session, company_id: int, complex_id: int):
    complex_row = _get_allowed_complex(db, company_id, complex_id)
    if not complex_row:
        return []
    plans = db.query(models.AptPlan).filter(
        models.AptPlan.ComplexID == complex_id
    ).order_by(models.AptPlan.PlanName.asc()).all()
    is_writable = complex_row.CompanyID == company_id
    return [
        {
            "PlanID": p.PlanID,
            "ComplexID": p.ComplexID,
            "PlanName": p.PlanName,
            "is_writable": is_writable,
        }
        for p in plans
    ]


def get_apt_windows_action(db: Session, company_id: int, plan_id: int):
    plan = _get_allowed_plan(db, company_id, plan_id)
    if not plan:
        return []
    windows = db.query(models.WindowSize).filter(
        models.WindowSize.PlanID == plan_id
    ).order_by(models.WindowSize.SortOrder.asc()).all()
    is_writable = _get_writable_plan(db, company_id, plan_id) is not None

    result = []
    for w in windows:
        result.append({
            "WindowID": w.WindowID,
            "PlanID": w.PlanID,
            "LocationName": w.LocationName,
            "WinType": w.WinType,
            "Width": w.Width,
            "Height": w.Height,
            "SplitCount": w.SplitCount,
            "SplitSizes": w.SplitSizes,
            "BoxWidth": w.BoxWidth,
            "Memo": w.Memo,
            "is_writable": is_writable,
        })
    return result


def get_apt_manager_payload(db: Session, company_id: int, user_name: str):
    company = db.query(models.Company).filter(
        models.Company.CompanyID == company_id
    ).first()
    return {
        "user_name": user_name,
        "company_name": company.CompanyName if company else "미지정 회사",
    }


def save_apt_complex_action(db: Session, company_id: int, name: str, complex_id: int):
    if complex_id > 0:
        target = _get_writable_complex(db, company_id, complex_id)
        if target:
            target.ComplexName = name
        else:
            return {"status": "forbidden"}
    else:
        max_sort = db.query(func.max(models.AptComplex.SortOrder)).filter(
            models.AptComplex.CompanyID == company_id
        ).scalar() or 0
        db.add(models.AptComplex(
            ComplexName=name,
            SortOrder=max_sort + 1,
            CompanyID=company_id,
        ))
    db.commit()
    return {"status": "ok"}


def delete_apt_complex_action(db: Session, company_id: int, complex_id: int):
    target = _get_allowed_complex(db, company_id, complex_id)
    if not target or target.CompanyID != company_id:
        return {"status": "forbidden"}
    plans = db.query(models.AptPlan).filter(
        models.AptPlan.ComplexID == complex_id
    ).all()
    for p in plans:
        db.query(models.WindowSize).filter(models.WindowSize.PlanID == p.PlanID).delete()
    db.query(models.AptPlan).filter(models.AptPlan.ComplexID == complex_id).delete()
    db.query(models.AptComplex).filter(models.AptComplex.ComplexID == complex_id).delete()
    db.commit()
    return {"status": "ok"}


def save_apt_plan_action(db: Session, company_id: int, complex_id: int, name: str, plan_id: int):
    if plan_id > 0:
        if not _get_writable_plan(db, company_id, plan_id):
            return {"status": "forbidden"}
        db.query(models.AptPlan).filter(models.AptPlan.PlanID == plan_id).update({"PlanName": name})
    else:
        if not _get_writable_complex(db, company_id, complex_id):
            return {"status": "forbidden"}
        max_sort = db.query(func.max(models.AptPlan.SortOrder)).filter(
            models.AptPlan.ComplexID == complex_id
        ).scalar() or 0
        db.add(models.AptPlan(ComplexID=complex_id, PlanName=name, SortOrder=max_sort + 1))
    db.commit()
    return {"status": "ok"}


def delete_apt_plan_action(db: Session, company_id: int, plan_id: int):
    if not _get_writable_plan(db, company_id, plan_id):
        return {"status": "forbidden"}
    db.query(models.WindowSize).filter(models.WindowSize.PlanID == plan_id).delete()
    db.query(models.AptPlan).filter(models.AptPlan.PlanID == plan_id).delete()
    db.commit()
    return {"status": "ok"}


def save_apt_window_action(
    db: Session,
    company_id: int,
    plan_id: int,
    location: str,
    width: float,
    height: float,
    window_id: int,
    win_type: str,
    split_count: int,
    box_width: float,
    memo: str,
    split_sizes: str,
):
    if not _get_writable_plan(db, company_id, plan_id):
        return {"status": "forbidden"}
    data = {
        "LocationName": location,
        "Width": width,
        "Height": height,
        "WinType": win_type,
        "SplitCount": split_count,
        "SplitSizes": split_sizes,
        "BoxWidth": box_width,
        "Memo": memo,
    }

    if window_id > 0:
        if not _get_writable_window(db, company_id, window_id):
            return {"status": "forbidden"}
        db.query(models.WindowSize).filter(models.WindowSize.WindowID == window_id).update(data)
    else:
        max_sort = db.query(func.max(models.WindowSize.SortOrder)).filter(
            models.WindowSize.PlanID == plan_id
        ).scalar() or 0
        db.add(models.WindowSize(
            PlanID=plan_id,
            LocationName=location,
            Width=width,
            Height=height,
            WinType=win_type,
            SplitCount=split_count,
            SplitSizes=split_sizes,
            BoxWidth=box_width,
            Memo=memo,
            SortOrder=max_sort + 1,
        ))
    db.commit()
    return {"status": "ok"}


def delete_apt_window_action(db: Session, company_id: int, window_id: int):
    if not _get_writable_window(db, company_id, window_id):
        return {"status": "forbidden"}
    db.query(models.WindowSize).filter(models.WindowSize.WindowID == window_id).delete()
    db.commit()
    return {"status": "ok"}


def import_apt_windows_action(
    db: Session,
    company_id: int,
    order_id: int,
    window_ids: List[int],
    form_data,
):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == company_id,
    ).first()
    if not order:
        return {"status": "forbidden"}

    windows = []
    for window_id in window_ids:
        allowed = _get_allowed_window(db, company_id, window_id)
        if allowed:
            windows.append(allowed)

    if len(windows) != len(window_ids):
        return {"status": "forbidden"}

    for w in windows:
        use_outer = form_data.get(f"CT_Outer_{w.WindowID}")
        use_inner = form_data.get(f"CT_Inner_{w.WindowID}")
        win_type = w.WinType or "블라인드"
        clean_memo = w.Memo if w.Memo else ""
        clean_loc = w.LocationName if w.LocationName else ""
        group_id = None
        width_val = float(w.Width or 0)
        height_val = float(w.Height or 0)

        if "블라인드" in win_type:
            cat = "블라인드"
            sub_cat = "콤비"
            min_qty = 1.50
            b_count = w.SplitCount if (w.SplitCount and w.SplitCount > 0) else 1
            w_split_list = []

            if w.SplitSizes:
                w_split_list = [float(x.strip()) for x in w.SplitSizes.split(",") if x.strip()]
            else:
                if b_count > 1 and width_val > 0:
                    w_split_list = [round(width_val / b_count, 1)] * b_count
                else:
                    w_split_list = [width_val]

            size_str_list = []
            qty_str_list = []
            total_area_qty = 0.0
            calc_height = 150.0 if height_val < 150 else height_val

            for each_w in w_split_list:
                size_str_list.append(f"{each_w}x{height_val}")
                each_qty = round((each_w * calc_height) / 10000, 2)
                qty_str_list.append(f"{each_qty:.2f}")
                total_area_qty += each_qty

            if total_area_qty < min_qty:
                total_area_qty = min_qty

            db.add(models.OrderItem(
                OrderID=order_id,
                GroupID=group_id,
                Location=clean_loc,
                Category=cat,
                Category1=sub_cat,
                cate1="",
                cate2="",
                cate3="",
                cate4=clean_memo,
                Width=width_val,
                Height=height_val,
                Quantity=total_area_qty,
                BlindSize=", ".join(size_str_list),
                BlindCount=b_count,
                BlindQty=", ".join(qty_str_list),
                Supplier="",
            ))
        else:
            if not use_outer and not use_inner:
                use_outer = "Y"

            if use_outer:
                calc_qty = math.ceil((width_val * 1.5) / 150) if width_val > 0 else 1
                db.add(models.OrderItem(
                    OrderID=order_id,
                    GroupID=group_id,
                    Location=clean_loc,
                    Category="커튼",
                    Category1="겉지",
                    cate1="",
                    cate2="",
                    cate3="정식(기본)",
                    Width=width_val,
                    Height=height_val,
                    Quantity=calc_qty,
                    cate4=clean_memo,
                    Supplier="",
                ))

            if use_inner:
                calc_qty = math.ceil((width_val * 2.0) / 150) if width_val > 0 else 1
                db.add(models.OrderItem(
                    OrderID=order_id,
                    GroupID=group_id,
                    Location=clean_loc,
                    Category="커튼",
                    Category1="속지",
                    cate1="",
                    cate2="",
                    cate3="나비주름(2배)",
                    Width=width_val,
                    Height=height_val,
                    Quantity=calc_qty,
                    cate4=clean_memo,
                    Supplier="",
                ))

    db.commit()
    recalc_order_amounts(db, order_id)
    return {"status": "ok"}
