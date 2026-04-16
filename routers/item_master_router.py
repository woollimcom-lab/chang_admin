from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import get_user_or_key
from database import get_db
from services.item_master_service import (
    list_master_products,
    list_supplier_product_attrs,
    normalize_category_name,
    normalize_subcategory_name,
    soft_delete_master_product,
    upsert_master_product,
)


router = APIRouter()


@router.get("/api/supplier/smart-db")
async def get_supplier_smart_db(request: Request, db: Session = Depends(get_db)):
    auth = await get_user_or_key(request, db)
    if not auth or auth.get("type") != "user":
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})
    return list_master_products(db, auth["company_id"])


@router.get("/api/item/master/attrs")
async def get_supplier_product_attrs(
    request: Request,
    product_id: int = 0,
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth or auth.get("type") != "user":
        return JSONResponse(status_code=403, content={"msg": "沅뚰븳???놁뒿?덈떎."})
    return list_supplier_product_attrs(db, auth["company_id"], product_id)


@router.post("/api/item/master/update")
async def update_master_price(
    request: Request,
    ProductID: int = Form(0),
    Category: str = Form(""),
    SubCategory: str = Form(""),
    ProductName: str = Form(...),
    Color: str = Form(""),
    Option: str = Form(""),
    Note: str = Form(""),
    SupplierID: int = Form(0),
    SupplierName: str = Form(""),
    CostPrice: float = Form(0),
    SellingPrice: float = Form(0),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth or auth.get("type") != "user":
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})

    Category = normalize_category_name(Category)
    SubCategory = normalize_subcategory_name(SubCategory, Category)
    ProductName = ProductName.strip()
    SupplierName = SupplierName.strip()

    print(
        "[MASTER UPDATE DEBUG] "
        f"pid={ProductID} category={Category!r} subcategory={SubCategory!r} "
        f"product={ProductName!r} supplier={SupplierName!r} cost={CostPrice} sell={SellingPrice}"
    )

    ok, payload = upsert_master_product(
        db=db,
        company_id=auth["company_id"],
        product_id=ProductID,
        category=Category,
        subcategory=SubCategory,
        product_name=ProductName,
        color=Color,
        option=Option,
        note=Note,
        supplier_id=SupplierID,
        supplier_name=SupplierName,
        cost_price=CostPrice,
        selling_price=SellingPrice,
    )
    if not ok:
        return JSONResponse(status_code=payload["status_code"], content={"msg": payload["msg"]})
    return payload


@router.post("/api/item/master/delete")
async def delete_master_price(
    request: Request,
    ProductID: int = Form(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth or auth.get("type") != "user":
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})

    ok, payload = soft_delete_master_product(db, auth["company_id"], ProductID)
    if not ok:
        return JSONResponse(status_code=payload["status_code"], content={"msg": payload["msg"]})
    return payload
