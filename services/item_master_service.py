import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

import models


def normalize_supplier_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def normalize_supplier_match_key(value: str) -> str:
    base = normalize_supplier_name(value)
    return re.sub(r"[/,+()\[\]\-_.]+", "", base)


K_CATEGORY_CURTAIN = "커튼"
K_CATEGORY_BLIND = "블라인드"
K_CATEGORY_OTHER = "기타"


def normalize_category_name(category: Optional[str]) -> str:
    cat = (category or "").strip()
    alias_map = {
        K_CATEGORY_CURTAIN: K_CATEGORY_CURTAIN,
        K_CATEGORY_BLIND: K_CATEGORY_BLIND,
        K_CATEGORY_OTHER: K_CATEGORY_OTHER,
    }
    return alias_map.get(cat, cat)


def normalize_subcategory_name(subcategory: Optional[str], category: Optional[str] = None) -> str:
    sub = (subcategory or "").strip()
    if not sub:
        return ""

    cat = normalize_category_name(category)
    if cat == K_CATEGORY_CURTAIN:
        if sub in {"겉지"}:
            return "겉지"
        if sub in {"속지"}:
            return "속지"
        return sub

    if cat == K_CATEGORY_BLIND:
        blind_alias = {
            "콤비": "콤비",
            "롤": "롤",
            "우드": "우드",
            "A/L": "A/L",
            "허니콤": "허니콤",
            "홀딩": "홀딩",
            "버티컬": "버티컬",
            "트리플": "트리플",
            "ROLL": "롤",
            "WOOD": "우드",
            "HONEYCOMB": "허니콤",
            "VERTICAL": "버티컬",
            "TRIPLE": "트리플",
        }
        key = sub.upper() if sub.isascii() else sub
        return blind_alias.get(key, blind_alias.get(sub, sub))

    return sub


def is_core_fabric_category(category: Optional[str]) -> bool:
    cat = normalize_category_name(category)
    return cat in {K_CATEGORY_CURTAIN, K_CATEGORY_BLIND}


def ensure_supplier_product_attrs_table(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS erp_supplier_product_attrs (
            AttrID INT AUTO_INCREMENT PRIMARY KEY,
            CompanyID INT NOT NULL,
            ProductID INT NOT NULL,
            AttrType VARCHAR(20) NOT NULL,
            AttrValue VARCHAR(255) NOT NULL,
            ExtraPrice DECIMAL(18, 0) NOT NULL DEFAULT 0,
            UseCount INT NOT NULL DEFAULT 1,
            IsActive TINYINT(1) NOT NULL DEFAULT 1,
            LastUsedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_supplier_product_attr (CompanyID, ProductID, AttrType, AttrValue),
            KEY ix_supplier_product_attr_lookup (CompanyID, ProductID, AttrType, UseCount, LastUsedAt)
        )
    """))


def save_supplier_product_attrs(
    db: Session,
    company_id: int,
    product_id: int,
    category1: str = "",
    category2: str = "",
    category3: str = "",
):
    product_id = int(product_id or 0)
    if product_id <= 0:
        return

    ensure_supplier_product_attrs_table(db)
    value_map = {
        "category1": (category1 or "").strip(),
        "category2": (category2 or "").strip(),
        "category3": (category3 or "").strip(),
    }
    for attr_type, attr_value in value_map.items():
        if not attr_value:
            continue
        db.execute(text("""
            INSERT INTO erp_supplier_product_attrs (
                CompanyID, ProductID, AttrType, AttrValue, ExtraPrice, UseCount, IsActive, LastUsedAt
            )
            VALUES (
                :company_id, :product_id, :attr_type, :attr_value, 0, 1, 1, CURRENT_TIMESTAMP
            )
            ON DUPLICATE KEY UPDATE
                IsActive = 1,
                UseCount = UseCount + 1,
                LastUsedAt = CURRENT_TIMESTAMP
        """), {
            "company_id": company_id,
            "product_id": product_id,
            "attr_type": attr_type,
            "attr_value": attr_value,
        })


def list_supplier_product_attrs(db: Session, company_id: int, product_id: int):
    product_id = int(product_id or 0)
    if product_id <= 0:
        return {"category1": [], "category2": [], "category3": []}

    ensure_supplier_product_attrs_table(db)
    grouped = {"category1": [], "category2": [], "category3": []}

    rows = db.execute(text("""
        SELECT AttrType, AttrValue, COALESCE(ExtraPrice, 0) AS ExtraPrice, COALESCE(UseCount, 0) AS UseCount
        FROM erp_supplier_product_attrs
        WHERE CompanyID = :company_id
          AND ProductID = :product_id
          AND (IsActive IS NULL OR IsActive = 1)
        ORDER BY AttrType ASC, UseCount DESC, LastUsedAt DESC, AttrValue ASC
    """), {
        "company_id": company_id,
        "product_id": product_id,
    }).mappings().all()

    seen = {"category1": set(), "category2": set(), "category3": set()}
    for row in rows:
        attr_type = (row["AttrType"] or "").strip()
        attr_value = (row["AttrValue"] or "").strip()
        if attr_type not in grouped or not attr_value or attr_value in seen[attr_type]:
            continue
        grouped[attr_type].append({
            "value": attr_value,
            "extra_price": float(row["ExtraPrice"] or 0),
            "use_count": int(row["UseCount"] or 0),
        })
        seen[attr_type].add(attr_value)

    return grouped


def list_master_products(db: Session, company_id: int):
    ensure_supplier_product_attrs_table(db)
    rows = db.execute(text("""
        SELECT
            p.ProductID,
            p.SupplierID,
            COALESCE(p.Category, '') AS Category,
            COALESCE(p.SubCategory, '') AS SubCategory,
            COALESCE(p.ProductName, '') AS ProductName,
            COALESCE((
                SELECT spa.AttrValue
                FROM erp_supplier_product_attrs spa
                WHERE spa.CompanyID = p.CompanyID
                  AND spa.ProductID = p.ProductID
                  AND spa.AttrType = 'category1'
                  AND (spa.IsActive IS NULL OR spa.IsActive = 1)
                ORDER BY spa.UseCount DESC, spa.LastUsedAt DESC, spa.AttrValue ASC
                LIMIT 1
            ), '') AS Color,
            COALESCE((
                SELECT spa.AttrValue
                FROM erp_supplier_product_attrs spa
                WHERE spa.CompanyID = p.CompanyID
                  AND spa.ProductID = p.ProductID
                  AND spa.AttrType = 'category2'
                  AND (spa.IsActive IS NULL OR spa.IsActive = 1)
                ORDER BY spa.UseCount DESC, spa.LastUsedAt DESC, spa.AttrValue ASC
                LIMIT 1
            ), '') AS `Option`,
            COALESCE((
                SELECT spa.AttrValue
                FROM erp_supplier_product_attrs spa
                WHERE spa.CompanyID = p.CompanyID
                  AND spa.ProductID = p.ProductID
                  AND spa.AttrType = 'category3'
                  AND (spa.IsActive IS NULL OR spa.IsActive = 1)
                ORDER BY spa.UseCount DESC, spa.LastUsedAt DESC, spa.AttrValue ASC
                LIMIT 1
            ), '') AS Note,
            COALESCE(p.CostPrice, 0) AS CostPrice,
            COALESCE(p.SellingPrice, 0) AS SellingPrice,
            COALESCE(s.SupplierName, '') AS SupplierName
        FROM erp_supplier_products p
        LEFT JOIN erp_suppliers s ON s.SupplierID = p.SupplierID
        WHERE p.CompanyID = :company_id
          AND (p.IsActive IS NULL OR p.IsActive = 1)
        ORDER BY
            COALESCE(p.Category, '') ASC,
            COALESCE(p.SubCategory, '') ASC,
            COALESCE(s.SupplierName, '') ASC,
            COALESCE(p.ProductName, '') ASC
    """), {"company_id": company_id}).mappings().all()

    return [
        {
            "product_id": int(r["ProductID"] or 0),
            "supplier_id": int(r["SupplierID"] or 0),
            "category": r["Category"] or "",
            "subcategory": r["SubCategory"] or "",
            "name": r["ProductName"] or "",
            "color": r["Color"] or "",
            "option": r["Option"] or "",
            "note": r["Note"] or "",
            "cost": float(r["CostPrice"] or 0),
            "price": float(r["SellingPrice"] or 0),
            "supplier": r["SupplierName"] or "",
        }
        for r in rows
    ]


def upsert_master_product(
    db: Session,
    company_id: int,
    product_id: int,
    category: str,
    subcategory: str,
    product_name: str,
    color: str,
    option: str,
    note: str,
    supplier_id: int,
    supplier_name: str,
    cost_price: float,
    selling_price: float,
):
    category = normalize_category_name(category)
    subcategory = normalize_subcategory_name(subcategory, category)
    product_name = product_name.strip()
    supplier_name = normalize_supplier_name(supplier_name)

    if not product_name:
        return False, {"status_code": 400, "msg": "제품명을 입력해주세요."}

    sup_id = int(supplier_id or 0)
    if sup_id > 0:
        sup = db.query(models.Supplier).filter(
            models.Supplier.CompanyID == company_id,
            models.Supplier.SupplierID == sup_id,
        ).order_by(models.Supplier.SupplierID.asc()).first()
        if sup:
            supplier_name = (sup.SupplierName or "").strip()
            if getattr(sup, "IsActive", True) is False:
                sup_id = 0
        else:
            sup_id = 0

    if not sup_id and supplier_name:
        sup = db.query(models.Supplier).filter(
            models.Supplier.CompanyID == company_id,
            models.Supplier.SupplierName == supplier_name,
            (models.Supplier.IsActive == None) | (models.Supplier.IsActive == True),
        ).order_by(models.Supplier.SupplierID.asc()).first()
        if not sup:
            match_key = normalize_supplier_match_key(supplier_name)
            if match_key:
                candidates = db.query(models.Supplier).filter(
                    models.Supplier.CompanyID == company_id,
                    (models.Supplier.IsActive == None) | (models.Supplier.IsActive == True),
                ).order_by(models.Supplier.SupplierID.asc()).all()
                matched = [
                    s for s in candidates
                    if normalize_supplier_match_key(getattr(s, "SupplierName", "")) == match_key
                ]
                if len(matched) == 1:
                    sup = matched[0]
        if not sup:
            sup = models.Supplier(CompanyID=company_id, SupplierName=supplier_name, IsActive=True)
            db.add(sup)
            db.flush()
        sup_id = sup.SupplierID

    sp_model = models.SupplierProduct
    has_sp_category = hasattr(sp_model, "Category")
    has_sp_subcategory = hasattr(sp_model, "SubCategory")
    has_sp_selling = hasattr(sp_model, "SellingPrice")

    prod = None
    if product_id and int(product_id) > 0:
        prod = db.query(sp_model).filter(
            sp_model.CompanyID == company_id,
            sp_model.ProductID == product_id,
        ).first()

    if not prod:
        if has_sp_category and has_sp_subcategory:
            query = db.query(sp_model).filter(
                sp_model.CompanyID == company_id,
                sp_model.ProductName == product_name,
            )
            if sup_id:
                query = query.filter(sp_model.SupplierID == sup_id)
            if category:
                query = query.filter(sp_model.Category == category)
            if subcategory:
                query = query.filter(sp_model.SubCategory == subcategory)
            prod = query.first()
        else:
            row = db.execute(text("""
                SELECT ProductID
                FROM erp_supplier_products
                WHERE CompanyID = :company_id
                  AND ProductName = :product_name
                  AND (:supplier_id = 0 OR SupplierID = :supplier_id)
                  AND (:category = '' OR Category = :category)
                  AND (:subcategory = '' OR SubCategory = :subcategory)
                LIMIT 1
            """), {
                "company_id": company_id,
                "product_name": product_name,
                "supplier_id": sup_id or 0,
                "category": category or "",
                "subcategory": subcategory or "",
            }).mappings().first()
            if row and row.get("ProductID"):
                prod = db.query(sp_model).filter(
                    sp_model.CompanyID == company_id,
                    sp_model.ProductID == int(row["ProductID"]),
                ).first()

    if not prod:
        create_kwargs = {
            "CompanyID": company_id,
            "SupplierID": sup_id,
            "ProductName": product_name,
            "CostPrice": cost_price,
        }
        if has_sp_category:
            create_kwargs["Category"] = category or None
        if has_sp_subcategory:
            create_kwargs["SubCategory"] = subcategory or None
        if has_sp_selling:
            create_kwargs["SellingPrice"] = selling_price
        prod = sp_model(**create_kwargs)
        db.add(prod)
        db.flush()
        db.execute(text("""
            UPDATE erp_supplier_products
            SET SupplierID = :supplier_id,
                ProductName = :product_name,
                Category = :category,
                SubCategory = :subcategory,
                CostPrice = :cost_price,
                SellingPrice = :selling_price
            WHERE ProductID = :product_id
        """), {
            "supplier_id": sup_id,
            "product_name": product_name,
            "category": category or None,
            "subcategory": subcategory or None,
            "cost_price": cost_price or 0,
            "selling_price": selling_price or 0,
            "product_id": getattr(prod, "ProductID", 0),
        })
    else:
        prod.ProductName = product_name
        if has_sp_category:
            prod.Category = category or None
        if has_sp_subcategory:
            prod.SubCategory = subcategory or None
        if cost_price > 0:
            prod.CostPrice = cost_price
        if has_sp_selling and selling_price > 0:
            prod.SellingPrice = selling_price
        if sup_id:
            prod.SupplierID = sup_id
        db.flush()
        db.execute(text("""
            UPDATE erp_supplier_products
            SET SupplierID = :supplier_id,
                ProductName = :product_name,
                Category = :category,
                SubCategory = :subcategory,
                CostPrice = CASE WHEN :cost_price > 0 THEN :cost_price ELSE CostPrice END,
                SellingPrice = CASE WHEN :selling_price > 0 THEN :selling_price ELSE SellingPrice END
            WHERE ProductID = :product_id
        """), {
            "supplier_id": sup_id,
            "product_name": product_name,
            "category": category or None,
            "subcategory": subcategory or None,
            "cost_price": cost_price or 0,
            "selling_price": selling_price or 0,
            "product_id": getattr(prod, "ProductID", 0),
        })

    saved_product_id = int(getattr(prod, "ProductID", 0) or 0)
    save_supplier_product_attrs(
        db,
        company_id=company_id,
        product_id=saved_product_id,
        category1=color or "",
        category2=option or "",
        category3=note or "",
    )
    db.commit()

    saved_supplier_id = int(getattr(prod, "SupplierID", 0) or 0)
    saved_cost = float(getattr(prod, "CostPrice", 0) or 0)
    saved_selling = float(getattr(prod, "SellingPrice", 0) or 0)

    print(
        "[MASTER UPDATE SAVED] "
        f"pid={saved_product_id} supplier_id={saved_supplier_id} "
        f"cost={saved_cost} sell={saved_selling}"
    )

    return True, {
        "status": "ok",
        "product_id": saved_product_id,
        "supplier_id": saved_supplier_id,
        "category": category,
        "subcategory": subcategory,
        "product_name": product_name,
        "supplier_name": supplier_name,
        "color": color or "",
        "option": option or "",
        "note": note or "",
        "cost_price": saved_cost,
        "selling_price": saved_selling,
    }


def soft_delete_master_product(db: Session, company_id: int, product_id: int):
    row = db.execute(text("""
        SELECT ProductID
        FROM erp_supplier_products
        WHERE ProductID = :product_id
          AND CompanyID = :company_id
        LIMIT 1
    """), {
        "product_id": product_id,
        "company_id": company_id,
    }).mappings().first()

    if not row:
        return False, {"status_code": 404, "msg": "제품을 찾을 수 없습니다."}

    db.execute(text("""
        UPDATE erp_supplier_products
        SET IsActive = 0
        WHERE ProductID = :product_id
          AND CompanyID = :company_id
    """), {
        "product_id": product_id,
        "company_id": company_id,
    })
    db.commit()
    return True, {"status": "ok"}
