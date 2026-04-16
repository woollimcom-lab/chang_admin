import json
import math
import re
from collections import Counter
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
from services.item_master_service import upsert_master_product


K_CATEGORY_CURTAIN = "커튼"
K_CATEGORY_BLIND = "블라인드"
K_CATEGORY_OTHER = "기타"


def safe_num(val):
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except Exception:
        return 0.0


def safe_int(val):
    try:
        return int(safe_num(val))
    except Exception:
        return 0


def _normalize_supplier_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_supplier_match_key(value: Any) -> str:
    base = _normalize_supplier_name(value)
    return re.sub(r"[/,+()\[\]\-_.]+", "", base)


def _item_detail_value(item, attr_name: str, legacy_name: Optional[str] = None) -> str:
    if not item:
        return ""
    val = getattr(item, attr_name, None)
    if (val is None or val == "") and legacy_name:
        val = getattr(item, legacy_name, None)
    return str(val or "").strip()


def _compose_item_name(item) -> str:
    cate1 = _item_detail_value(item, "cate1", "ProductName")
    cate2 = _item_detail_value(item, "cate2")
    return " ".join([p for p in [cate1, cate2] if p]).strip()


def normalize_category_name(category: Optional[str]) -> str:
    cat = (category or "").strip()
    alias_map = {
        "커튼": K_CATEGORY_CURTAIN,
        "블라인드": K_CATEGORY_BLIND,
        "기타": K_CATEGORY_OTHER,
    }
    return alias_map.get(cat, cat or K_CATEGORY_OTHER)


def normalize_subcategory_name(subcategory: Optional[str], category: Optional[str] = None) -> str:
    sub = (subcategory or "").strip()
    if not sub:
        return ""

    cat = normalize_category_name(category)
    if cat == K_CATEGORY_CURTAIN:
        curtain_alias = {
            "겉지": "겉지",
            "속지": "속지",
        }
        return curtain_alias.get(sub, sub)

    if cat == K_CATEGORY_BLIND:
        blind_alias = {
            "콤비": "콤비",
            "롤": "롤",
            "우드": "우드",
            "A/L": "A/L",
            "허니콤": "허니콤",
            "홀딩": "홀딩",
            "버티칼": "버티칼",
            "트리플": "트리플",
            "ROLL": "롤",
            "WOOD": "우드",
            "HONEYCOMB": "허니콤",
            "VERTICAL": "버티칼",
            "TRIPLE": "트리플",
        }
        key = sub.upper() if sub.isascii() else sub
        return blind_alias.get(key, blind_alias.get(sub, sub))

    return sub


def item_category_mode(category: Optional[str]) -> str:
    cat = normalize_category_name(category)
    if cat == K_CATEGORY_BLIND:
        return "blind"
    if cat == K_CATEGORY_CURTAIN:
        return "curtain"
    return "generic"


def recalc_order_amounts(db: Session, order_id: int):
    total = db.query(func.sum(models.OrderItem.LineTotal)).filter(
        models.OrderItem.OrderID == order_id
    ).scalar() or 0

    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order:
        return

    discount = float(order.DiscountAmount or 0)
    base_price = float(total) - discount
    final_amt = base_price * 1.1 if order.IsVatIncluded == "Y" else base_price
    final_amt = int(round(final_amt))

    order.TotalAmount = total
    order.FinalAmount = final_amt
    db.commit()


def log_history(db: Session, order_id: int, log_type: str, content: str, member_name: str = None):
    try:
        db.add(
            models.OrderHistory(
                OrderID=order_id,
                LogType=log_type,
                Contents=content,
                MemberName=member_name,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _safe_form_num(val):
    raw = str(val or "").replace(",", "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _parse_attr_dict(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _resolve_supplier_ref(
    db: Session,
    company_id: int,
    supplier_id_raw: Any,
    supplier_name_raw: Any,
) -> tuple[int, str]:
    supplier_id = safe_int(supplier_id_raw)
    supplier_name = _normalize_supplier_name(supplier_name_raw)

    if supplier_id > 0:
        supplier = db.query(models.Supplier).filter(
            models.Supplier.CompanyID == company_id,
            models.Supplier.SupplierID == supplier_id,
        ).first()
        if supplier:
            supplier_name = str(supplier.SupplierName or "").strip()
            if getattr(supplier, "IsActive", True) is not False:
                return supplier.SupplierID, supplier_name

    if supplier_name:
        supplier = db.query(models.Supplier).filter(
            models.Supplier.CompanyID == company_id,
            models.Supplier.SupplierName == supplier_name,
            or_(models.Supplier.IsActive == None, models.Supplier.IsActive == True),
        ).order_by(models.Supplier.SupplierID.asc()).first()
        if supplier:
            return supplier.SupplierID, str(supplier.SupplierName or "").strip()

        match_key = _normalize_supplier_match_key(supplier_name)
        if match_key:
            candidates = (
                db.query(models.Supplier)
                .filter(
                    models.Supplier.CompanyID == company_id,
                    or_(models.Supplier.IsActive == None, models.Supplier.IsActive == True),
                )
                .order_by(models.Supplier.SupplierID.asc())
                .all()
            )
            matched = [
                s for s in candidates
                if _normalize_supplier_match_key(getattr(s, "SupplierName", "")) == match_key
            ]
            if len(matched) == 1:
                supplier = matched[0]
                return supplier.SupplierID, str(supplier.SupplierName or "").strip()

    return 0, supplier_name


def _split_supplier_tokens(raw_value: Any) -> list[str]:
    raw = _normalize_supplier_name(raw_value)
    if not raw:
        return []
    tokens = [t.strip() for t in re.split(r"\s*[/,+]\s*", raw) if t.strip()]
    return tokens or [raw]


def _is_invalid_supplier_token(value: Any) -> bool:
    token = _normalize_supplier_name(value)
    if not token:
        return True
    if token.isdigit():
        return True
    if token in {"고객", "고객사"}:
        return True
    return False


def _compose_supplier_display_name(links: list[dict[str, Any]], fallback_raw: Any = "") -> str:
    names: list[str] = []
    seen: set[str] = set()
    for link in links or []:
        name = str((link or {}).get("name") or "").strip()
        normalized = _normalize_supplier_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(name)
    if names:
        return "/".join(names)
    return str(fallback_raw or "").strip()


def _resolve_supplier_links(
    db: Session,
    company_id: int,
    supplier_id_raw: Any,
    supplier_name_raw: Any,
) -> tuple[int, str, list[dict[str, Any]]]:
    raw_name = str(supplier_name_raw or "").strip()
    has_multi_delimiter = bool(re.search(r"[/,+]", raw_name))
    if not has_multi_delimiter:
        supplier_id, canonical_name = _resolve_supplier_ref(db, company_id, supplier_id_raw, raw_name)
        if supplier_id > 0:
            return supplier_id, canonical_name, [{"name": canonical_name, "supplier_id": supplier_id}]

    links: list[dict[str, Any]] = []
    primary_id = 0
    seen_keys: set[str] = set()
    for token in _split_supplier_tokens(raw_name):
        if _is_invalid_supplier_token(token):
            continue
        token_id, token_name = _resolve_supplier_ref(db, company_id, 0, token)
        resolved_name = token_name or token
        dedupe_key = f"{token_id}:{resolved_name.lower()}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        links.append({"name": resolved_name, "supplier_id": token_id})
        if primary_id <= 0 and token_id > 0:
            primary_id = token_id

    if len(links) == 1 and primary_id > 0:
        return primary_id, links[0]["name"], links
    return primary_id, _compose_supplier_display_name(links, raw_name), links


def _redirect_view(order_id: int, access_key: Optional[str]):
    key_param = f"?key={access_key}" if access_key else ""
    url = f"/w/view/{order_id}{key_param}" if access_key else f"/view/{order_id}"
    return RedirectResponse(url=url, status_code=303)


def backfill_order_item_supplier_links(
    db: Session,
    company_id: Optional[int] = None,
    order_ids: Optional[list[int]] = None,
    limit: int = 1000,
) -> Dict[str, int]:
    query = (
        db.query(models.OrderItem, models.Order.CompanyID)
        .join(models.Order, models.Order.OrderID == models.OrderItem.OrderID)
        .filter(models.OrderItem.Supplier.isnot(None))
    )
    if company_id:
        query = query.filter(models.Order.CompanyID == company_id)
    if order_ids:
        query = query.filter(models.OrderItem.OrderID.in_(order_ids))

    rows = (
        query.order_by(models.OrderItem.ItemID.asc())
        .limit(max(1, limit))
        .all()
    )

    checked = 0
    updated = 0
    skipped = 0

    for item, row_company_id in rows:
        checked += 1
        supplier_name = str(getattr(item, "Supplier", "") or "").strip()
        attrs = dict(item.Attributes) if isinstance(item.Attributes, dict) else {}
        current_supplier_id = safe_int(attrs.get("supplier_id"))
        resolved_supplier_id, display_supplier_name, supplier_links = _resolve_supplier_links(
            db,
            safe_int(row_company_id),
            current_supplier_id,
            supplier_name,
        )

        if resolved_supplier_id <= 0 and not supplier_links:
            skipped += 1
            continue

        changed = False
        if current_supplier_id != resolved_supplier_id:
            attrs["supplier_id"] = resolved_supplier_id
            changed = True
        if supplier_links != (attrs.get("supplier_links") if isinstance(attrs.get("supplier_links"), list) else None):
            attrs["supplier_links"] = supplier_links
            changed = True
        if display_supplier_name and supplier_name != display_supplier_name:
            item.Supplier = display_supplier_name
            changed = True
        if changed:
            item.Attributes = attrs
            updated += 1
        else:
            skipped += 1

    if updated:
        db.commit()

    return {
        "checked": checked,
        "updated": updated,
        "skipped": skipped,
    }


def audit_order_item_supplier_links(
    db: Session,
    company_id: Optional[int] = None,
    order_ids: Optional[list[int]] = None,
    limit: int = 1000,
) -> Dict[str, Any]:
    query = (
        db.query(models.OrderItem, models.Order.CompanyID)
        .join(models.Order, models.Order.OrderID == models.OrderItem.OrderID)
        .filter(models.OrderItem.Supplier.isnot(None))
        .filter(models.OrderItem.Supplier != "")
    )
    if company_id:
        query = query.filter(models.Order.CompanyID == company_id)
    if order_ids:
        query = query.filter(models.OrderItem.OrderID.in_(order_ids))

    rows = (
        query.order_by(models.OrderItem.ItemID.desc())
        .limit(max(1, limit))
        .all()
    )

    summary = {
        "checked": 0,
        "missing_supplier_id": 0,
        "multi_supplier": 0,
        "unresolved_tokens": 0,
    }
    unresolved_counter: Counter[str] = Counter()
    issues: list[dict[str, Any]] = []

    for item, row_company_id in rows:
        summary["checked"] += 1
        supplier_name = str(getattr(item, "Supplier", "") or "").strip()
        attrs = dict(item.Attributes) if isinstance(item.Attributes, dict) else {}
        current_supplier_id = safe_int(attrs.get("supplier_id"))
        _, _, supplier_links = _resolve_supplier_links(
            db,
            safe_int(row_company_id),
            current_supplier_id,
            supplier_name,
        )
        unresolved = [link.get("name") for link in supplier_links if safe_int(link.get("supplier_id")) <= 0]
        for token in unresolved:
            token_name = str(token or "").strip()
            if token_name:
                unresolved_counter[token_name] += 1

        has_issue = False
        issue = {
            "item_id": item.ItemID,
            "order_id": item.OrderID,
            "company_id": safe_int(row_company_id),
            "cate1": str(getattr(item, "cate1", "") or "").strip(),
            "supplier": supplier_name,
            "supplier_id": current_supplier_id,
            "supplier_links": supplier_links,
            "unresolved_tokens": unresolved,
        }

        if current_supplier_id <= 0:
            summary["missing_supplier_id"] += 1
            has_issue = True
        if len(supplier_links) > 1:
            summary["multi_supplier"] += 1
            has_issue = True
        if unresolved:
            summary["unresolved_tokens"] += 1
            has_issue = True

        if has_issue:
            issues.append(issue)

    return {
        "summary": summary,
        "unresolved_top": unresolved_counter.most_common(20),
        "issues": issues,
    }


async def save_item(request: Request, db: Session, auth: Dict[str, Any]):
    form = await request.form()
    order_id = safe_int(form.get("OrderID"))

    check_order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not check_order:
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})

    mode = form.get("mode")
    access_key = form.get("access_key")

    if mode == "del":
        t_id = safe_int(form.get("id"))
        item = db.query(models.OrderItem).filter(models.OrderItem.ItemID == t_id).first()
        if item:
            del_info = f"{item.Category1 or item.Category} {_compose_item_name(item)} {item.Width}x{item.Height}"
            if item.Category == K_CATEGORY_BLIND:
                del_info = f"{item.Category1} {_compose_item_name(item)} {item.BlindSize}".strip()

            log_history(db, order_id, "품목삭제", del_info, auth["name"])

            if item.GroupID:
                db.query(models.OrderItem).filter(models.OrderItem.GroupID == item.GroupID).delete()
            else:
                db.delete(item)

            db.commit()
            total = db.query(func.sum(models.OrderItem.LineTotal)).filter(
                models.OrderItem.OrderID == order_id
            ).scalar() or 0
            db.query(models.Order).filter(models.Order.OrderID == order_id).update(
                {"TotalAmount": total}
            )
            db.commit()

        return _redirect_view(order_id, access_key)

    row_indices = sorted(list(set(form.getlist("RowIdx"))), key=int)
    if not row_indices:
        return JSONResponse(status_code=400, content={"msg": "저장할 품목이 없습니다."})

    cat = normalize_category_name((form.get("Category") or "").strip() or K_CATEGORY_OTHER)
    cat_mode = item_category_mode(cat)
    grp_id = form.get("GroupID") or None
    max_sort = db.query(func.max(models.OrderItem.SortOrder)).filter(
        models.OrderItem.OrderID == order_id
    ).scalar() or 0

    canonical_payload = {}
    canonical_raw = form.get("CanonicalPayload")
    if canonical_raw:
        try:
            parsed_payload = json.loads(canonical_raw)
            if isinstance(parsed_payload, dict):
                canonical_payload = parsed_payload
        except Exception:
            canonical_payload = {}
    blind_meta = (
        canonical_payload.get("blindMeta")
        if isinstance(canonical_payload.get("blindMeta"), dict)
        else {}
    )
    print(
        "[ITEM SAVE DEBUG] "
        f"order_id={order_id} cat={cat!r} mode={cat_mode!r} rows={row_indices} "
        f"raw_sub={form.get('SubCategory')!r} blind_meta_sub={blind_meta.get('subCategory')!r}"
    )

    log_msgs = []
    log_type = "품목추가"
    master_sync_rows = []
    canonical_location = canonical_payload.get("location") if isinstance(canonical_payload, dict) else None
    location_value = (
        (str(canonical_location).strip() if canonical_location is not None else "")
        or (form.get("inpLocation") if form.get("Location") == "direct" else form.get("Location"))
        or ""
    )

    if cat_mode == "blind":
        idx1 = row_indices[0]
        item_id = safe_int(form.get(f"ItemID_{idx1}"))
        blind_sub_raw = (
            form.get(f"SubCat_{idx1}")
            or form.get("SubCategory")
            or blind_meta.get("subCategory")
            or ""
        )
        sub_cat = normalize_subcategory_name(blind_sub_raw, cat)
        raw_prod = (
            form.get(f"ProdName_{idx1}")
            or form.get("Master_Prod")
            or blind_meta.get("itemName")
            or ""
        ).strip()
        prod = raw_prod or sub_cat

        form_blind_size = form.get("BlindSize")
        form_blind_qty = form.get("BlindQty")
        total_qty = sum(safe_num(form.get(f"Qty_{idx}")) for idx in row_indices)
        h_val = safe_num(form.get(f"H_{idx1}"))

        if form_blind_size:
            blind_size = form_blind_size
        else:
            w_list = [str(form.get(f"W_{idx}")) for idx in row_indices if form.get(f"W_{idx}")]
            blind_size = f"{', '.join(w_list)} x {h_val}"

        price = safe_num(form.get(f"Price_{idx1}") or blind_meta.get("price"))
        attr_dict = _parse_attr_dict(form.get(f"Attributes_{idx1}"))
        supplier_id, supplier_name, supplier_links = _resolve_supplier_links(
            db,
            auth["company_id"],
            form.get("Master_SupplierID") or form.get("SupplierID") or attr_dict.get("supplier_id"),
            form.get("Master_Supplier") or form.get("Supplier") or blind_meta.get("supplier"),
        )
        if supplier_id > 0:
            attr_dict["supplier_id"] = supplier_id
        else:
            attr_dict.pop("supplier_id", None)
        if supplier_links:
            attr_dict["supplier_links"] = supplier_links
        else:
            attr_dict.pop("supplier_links", None)

        data = {
            "OrderID": order_id,
            "Location": location_value,
            "Category": cat,
            "Category1": sub_cat,
            "cate1": prod,
            "cate2": form.get(f"Color_{idx1}"),
            "cate3": form.get(f"Option_{idx1}"),
            "Width": 0,
            "Height": h_val,
            "Quantity": total_qty,
            "UnitPrice": price,
            "LineTotal": math.floor(total_qty * price),
            "cate4": form.get(f"Memo_{idx1}"),
            "Supplier": supplier_name,
            "BlindSize": blind_size,
            "BlindCount": len(row_indices),
            "BlindQty": form_blind_qty,
            "Attributes": attr_dict,
        }

        blind_desc = " / ".join(
            [x for x in [prod, form.get(f"Color_{idx1}"), form.get(f"Option_{idx1}")] if x]
        )
        log_msg = f"{sub_cat} {blind_desc} {blind_size} ({len(row_indices)}창".strip()

        if item_id > 0:
            db.query(models.OrderItem).filter(models.OrderItem.ItemID == item_id).update(data)
            log_type = "품목수정"
        else:
            max_sort += 1
            data["SortOrder"] = max_sort
            db.add(models.OrderItem(**data))
        log_msgs.append(log_msg)

        if raw_prod:
            master_sync_rows.append(
                {
                    "product_id": attr_dict.get("product_id") or blind_meta.get("productId") or 0,
                    "supplier_id": supplier_id,
                    "supplier": supplier_name,
                    "product_name": raw_prod,
                    "category": cat,
                    "subcategory": sub_cat,
                    "color": form.get(f"Color_{idx1}"),
                    "option": form.get(f"Option_{idx1}"),
                    "note": form.get(f"Memo_{idx1}"),
                    "cost_price": form.get("Master_CostPrice")
                    or blind_meta.get("costPrice")
                    or attr_dict.get("cost_price")
                    or 0,
                    # Keep order-level price changes out of the master DB.
                    "selling_price": 0,
                }
            )
    else:
        for idx in row_indices:
            item_id = safe_int(form.get(f"ItemID_{idx}"))
            sub_cat = normalize_subcategory_name(form.get(f"SubCat_{idx}"), cat)
            raw_prod = (form.get(f"ProdName_{idx}") or "").strip()
            prod = raw_prod or sub_cat
            if not prod and not sub_cat:
                continue

            w = safe_num(form.get(f"W_{idx}"))
            h = safe_num(form.get(f"H_{idx}"))
            qty = safe_num(form.get(f"Qty_{idx}"))
            price = safe_num(form.get(f"Price_{idx}"))
            attr_dict = _parse_attr_dict(form.get(f"Attributes_{idx}"))
            supplier_id, supplier_name, supplier_links = _resolve_supplier_links(
                db,
                auth["company_id"],
                form.get(f"SupplierID_{idx}") or form.get("SupplierID") or attr_dict.get("supplier_id"),
                form.get(f"Supplier_{idx}") or form.get("Supplier"),
            )
            if supplier_id > 0:
                attr_dict["supplier_id"] = supplier_id
            else:
                attr_dict.pop("supplier_id", None)
            if supplier_links:
                attr_dict["supplier_links"] = supplier_links
            else:
                attr_dict.pop("supplier_links", None)

            data = {
                "OrderID": order_id,
                "Location": location_value,
                "Category": cat,
                "Category1": sub_cat,
                "cate1": prod,
                "cate2": form.get(f"Color_{idx}"),
                "cate3": form.get(f"Option_{idx}"),
                "Width": w,
                "Height": h,
                "Quantity": qty,
                "UnitPrice": price,
                "LineTotal": qty * price,
                "cate4": form.get(f"Memo_{idx}"),
                "Supplier": supplier_name,
                "GroupID": grp_id,
                "Attributes": attr_dict,
            }

            if item_id > 0:
                log_type = "품목수정"
                db.query(models.OrderItem).filter(models.OrderItem.ItemID == item_id).update(data)
            else:
                max_sort += 1
                data["SortOrder"] = max_sort
                db.add(models.OrderItem(**data))

            color_txt = f" [{data['cate2']}]" if data["cate2"] else ""
            opt_txt = f" ({data['cate3']})" if data["cate3"] else ""
            log_msgs.append(f"{sub_cat} {prod}{color_txt} {w}x{h}{opt_txt}")

            if raw_prod:
                master_sync_rows.append(
                    {
                        "product_id": attr_dict.get("product_id"),
                        "supplier_id": supplier_id,
                        "supplier": data["Supplier"],
                        "product_name": raw_prod,
                        "category": cat,
                        "subcategory": sub_cat,
                        "color": form.get(f"Color_{idx}"),
                        "option": form.get(f"Option_{idx}"),
                        "note": form.get(f"Memo_{idx}"),
                        "cost_price": form.get(f"CostPrice_{idx}") or attr_dict.get("cost_price") or 0,
                        # Only the explicit price-save button should persist unit prices.
                        "selling_price": 0,
                    }
                )

    try:
        if any(safe_num(form.get(f"H_{i}")) >= 270 for i in row_indices):
            db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    except Exception:
        pass

    # 주문 품목 저장은 먼저 확정하고, ERP 마스터 동기화 실패가 현장 입력을 막지 않게 분리한다.
    db.commit()

    print(f"[ERP SYNC QUEUE] {master_sync_rows}")
    for sync_row in master_sync_rows:
        print(
            "[ERP SYNC TRY] "
            f"pid={safe_int(sync_row.get('product_id'))} supplier={sync_row.get('supplier')!r} "
            f"product={sync_row.get('product_name')!r} category={sync_row.get('category')!r} "
            f"subcategory={sync_row.get('subcategory')!r} cost={_safe_form_num(sync_row.get('cost_price'))} "
            f"sell={_safe_form_num(sync_row.get('selling_price'))}"
        )
        try:
            ok, result = upsert_master_product(
                db=db,
                company_id=auth["company_id"],
                product_id=safe_int(sync_row.get("product_id")),
                category=sync_row.get("category") or "",
                subcategory=sync_row.get("subcategory") or "",
                product_name=(sync_row.get("product_name") or "").strip(),
                color=sync_row.get("color") or "",
                option=sync_row.get("option") or "",
                note=sync_row.get("note") or "",
                supplier_id=safe_int(sync_row.get("supplier_id")),
                supplier_name=sync_row.get("supplier") or "",
                cost_price=_safe_form_num(sync_row.get("cost_price")),
                selling_price=_safe_form_num(sync_row.get("selling_price")),
            )
        except Exception as exc:
            db.rollback()
            print(f"[ERP SYNC ERROR] {exc}")
            continue
        if ok:
            print(
                "[ERP SYNC UPDATE] "
                f"product={sync_row.get('product_name')!r} category={sync_row.get('category')!r} "
                f"subcategory={sync_row.get('subcategory')!r}"
            )
        else:
            print(f"[ERP SYNC SKIP] {result}")

    db.commit()

    if log_msgs:
        full_content = "\n".join(log_msgs)
        log_history(db, order_id, log_type, full_content, auth["name"])

    recalc_order_amounts(db, order_id)
    return _redirect_view(order_id, access_key)
