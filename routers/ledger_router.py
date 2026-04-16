import os
import uuid
import aiofiles
import re
from datetime import datetime,timedelta
from typing import Optional  # 변경 이유(Reason): Pydantic 422 유효성 검사 에러를 방지하기 위한 타입 모듈 추가
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session, joinedload
from database import get_db
from auth import get_current_user 
import models
from models import Supplier, SupplierTransaction, SupplierTransactionLink, FieldExpense, SupplierProduct
from sqlalchemy import text, case, func
import calendar # 파일 상단(import 영역)에 없으면 반드시 추가해주세요.

from services.item_master_service import normalize_category_name, normalize_subcategory_name
from services.item_route_service import _split_supplier_tokens

router = APIRouter(prefix="/api/ledger", tags=["Ledger"])


def _normalize_supplier_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_phone_like(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_supplier_match_key(value: str) -> str:
    base = _normalize_supplier_name(value)
    return re.sub(r"[/,+()\[\]\-_.]+", "", base)


def _normalize_expense_category_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _can_admin_ledger_view(current_user) -> bool:
    role_name = str(getattr(current_user, "role_name", "") or "").strip()
    return bool(
        role_name == "대표"
        or getattr(current_user, "perm_expense", False)
        or getattr(current_user, "perm_total", False)
        or getattr(current_user, "perm_staff", False)
    )


def _locked_expense_category_names():
    return {
        _normalize_expense_category_name("부가세"),
        _normalize_expense_category_name("vat"),
        _normalize_expense_category_name("관리비"),
        _normalize_expense_category_name("세금"),
        _normalize_expense_category_name("공과금"),
        _normalize_expense_category_name("공통"),
    }


def _is_locked_expense_category(category_name: str) -> bool:
    return _normalize_expense_category_name(category_name) in _locked_expense_category_names()


def _default_expense_categories():
    return [
        {"name": "식대", "icon": "🍚"},
        {"name": "주유", "icon": "⛽"},
        {"name": "물품구매", "icon": "🛒"},
        {"name": "교통비", "icon": "🛣️"},
        {"name": "관리비", "icon": "🧾"},
        {"name": "부가세", "icon": "🧾"},
        {"name": "세금", "icon": "💸"},
        {"name": "공과금", "icon": "🏠"},
        {"name": "공통", "icon": "📌"},
        {"name": "기타", "icon": "📦"},
    ]


def _ensure_expense_categories_table(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS erp_expense_categories (
            CategoryID INT AUTO_INCREMENT PRIMARY KEY,
            CompanyID INT NOT NULL,
            CategoryName VARCHAR(50) NOT NULL,
            Icon VARCHAR(20) NULL,
            SortOrder INT NOT NULL DEFAULT 1,
            IsActive TINYINT(1) NOT NULL DEFAULT 1,
            CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX ix_erp_expense_categories_company (CompanyID),
            INDEX ix_erp_expense_categories_active (CompanyID, IsActive)
        )
    """))
    db.commit()


def _seed_default_expense_categories(db: Session, company_id: int):
    _ensure_expense_categories_table(db)
    existing_rows = db.execute(text("""
        SELECT CategoryID, CategoryName
        FROM erp_expense_categories
        WHERE CompanyID = :company_id
    """), {"company_id": company_id}).mappings().all()
    existing_names = {
        _normalize_expense_category_name(row["CategoryName"] or "")
        for row in existing_rows
    }
    max_sort = db.execute(text("""
        SELECT COALESCE(MAX(SortOrder), 0)
        FROM erp_expense_categories
        WHERE CompanyID = :company_id
    """), {"company_id": company_id}).scalar() or 0

    for idx, item in enumerate(_default_expense_categories(), start=1):
        normalized_name = _normalize_expense_category_name(item["name"])
        if normalized_name in existing_names:
            continue
        max_sort = int(max_sort) + 1
        db.execute(text("""
            INSERT INTO erp_expense_categories
                (CompanyID, CategoryName, Icon, SortOrder, IsActive)
            VALUES
                (:company_id, :category_name, :icon, :sort_order, 1)
        """), {
            "company_id": company_id,
            "category_name": item["name"],
            "icon": item["icon"],
            "sort_order": max_sort,
        })
    db.commit()


def _ensure_supplier_tx_links_table(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS erp_supplier_transaction_links (
            LinkID INT AUTO_INCREMENT PRIMARY KEY,
            TxID INT NOT NULL,
            CompanyID INT NOT NULL,
            SupplierID INT NOT NULL,
            SortOrder INT NOT NULL DEFAULT 1,
            IsPrimary TINYINT(1) NOT NULL DEFAULT 0,
            IsActive TINYINT(1) NOT NULL DEFAULT 1,
            CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY ix_txid (TxID),
            KEY ix_company (CompanyID),
            KEY ix_supplier (SupplierID),
            KEY ix_company_tx (CompanyID, TxID)
        )
    """))
    db.commit()


def _resolve_multi_supplier_ids(db: Session, company_id: int, raw_value: str):
    tokens = _split_supplier_tokens(raw_value)
    if not tokens:
        return [], []

    suppliers = db.query(Supplier).filter(
        Supplier.CompanyID == company_id,
        Supplier.IsActive != False,
    ).all()
    by_exact = { _normalize_supplier_name(s.SupplierName): s for s in suppliers }

    resolved = []
    unresolved = []
    seen = set()
    for token in tokens:
        norm = _normalize_supplier_name(token)
        if not norm:
            continue
        sup = by_exact.get(norm)
        if not sup:
            mk = _normalize_supplier_match_key(token)
            candidates = [s for s in suppliers if _normalize_supplier_match_key(s.SupplierName) == mk]
            if len(candidates) == 1:
                sup = candidates[0]
        if not sup:
            unresolved.append(token)
            continue
        if sup.SupplierID in seen:
            continue
        seen.add(sup.SupplierID)
        resolved.append(sup)
    return resolved, unresolved


def _get_or_create_supplier(db: Session, company_id: int, supplier_name: str):
    normalized_name = _normalize_supplier_name(supplier_name)
    if not normalized_name:
        return None

    supplier = db.query(Supplier).filter(
        Supplier.CompanyID == company_id,
        Supplier.SupplierName == normalized_name,
        Supplier.IsActive != False,
    ).first()
    if supplier:
        return supplier

    supplier = Supplier(
        CompanyID=company_id,
        SupplierName=normalized_name,
    )
    if hasattr(supplier, "IsActive"):
        supplier.IsActive = True
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def _sync_supplier_tx_links(
    db: Session,
    tx_id: int,
    company_id: int,
    supplier_ids: list[int],
    primary_supplier_id: int,
):
    _ensure_supplier_tx_links_table(db)
    db.query(SupplierTransactionLink).filter(
        SupplierTransactionLink.TxID == tx_id,
        SupplierTransactionLink.CompanyID == company_id,
    ).delete(synchronize_session=False)

    unique_ids = []
    seen = set()
    for sid in supplier_ids:
        sid = int(sid or 0)
        if sid <= 0 or sid in seen:
            continue
        seen.add(sid)
        unique_ids.append(sid)

    if not unique_ids and primary_supplier_id:
        unique_ids = [int(primary_supplier_id)]

    for idx, sid in enumerate(unique_ids, start=1):
        db.add(SupplierTransactionLink(
            TxID=tx_id,
            CompanyID=company_id,
            SupplierID=sid,
            SortOrder=idx,
            IsPrimary=(sid == int(primary_supplier_id or 0)),
            IsActive=True
        ))
    db.commit()

# ==========================================
# 1. 매입/지급 원장 (Supplier Transactions)
# ==========================================
@router.get("/transactions")
def get_transactions(
    supplier_id: Optional[int] = None,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(SupplierTransaction).filter(SupplierTransaction.CompanyID == current_user.company_id)
    if not _can_admin_ledger_view(current_user):
        member_id = int(getattr(current_user, "member_id", 0) or 0)
        if member_id > 0 and hasattr(SupplierTransaction, "MemberID"):
            query = query.filter(SupplierTransaction.MemberID == member_id)
        else:
            return []
    if hasattr(SupplierTransaction, 'IsActive'): query = query.filter(SupplierTransaction.IsActive == True)
    if supplier_id: query = query.filter(SupplierTransaction.SupplierID == supplier_id)
        
    if year and month:
        start_date = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = datetime(year, month, last_day, 23, 59, 59)
        query = query.filter(SupplierTransaction.TxDate.between(start_date, end_date))
        
    transactions = query.options(joinedload(SupplierTransaction.supplier)).order_by(SupplierTransaction.TxDate.desc()).all()
    tx_ids = [int(t.TxID) for t in transactions if getattr(t, "TxID", None)]

    link_map = {}
    if tx_ids:
        try:
            _ensure_supplier_tx_links_table(db)
            links = db.query(SupplierTransactionLink).options(
                joinedload(SupplierTransactionLink.supplier)
            ).filter(
                SupplierTransactionLink.CompanyID == current_user.company_id,
                SupplierTransactionLink.IsActive == True,
                SupplierTransactionLink.TxID.in_(tx_ids)
            ).order_by(
                SupplierTransactionLink.TxID.asc(),
                SupplierTransactionLink.SortOrder.asc(),
                SupplierTransactionLink.LinkID.asc()
            ).all()
            for ln in links:
                txid = int(ln.TxID or 0)
                if txid <= 0:
                    continue
                if txid not in link_map:
                    link_map[txid] = []
                link_map[txid].append({
                    "SupplierID": int(ln.SupplierID or 0),
                    "SupplierName": (ln.supplier.SupplierName if ln.supplier else ""),
                    "IsPrimary": bool(getattr(ln, "IsPrimary", False)),
                    "SortOrder": int(getattr(ln, "SortOrder", 0) or 0),
                })
        except Exception:
            link_map = {}
    
    try:
        raw_ispaid = db.execute(text(f"SELECT TxID, IsPaid FROM erp_supplier_transactions WHERE CompanyID={current_user.company_id}")).fetchall()
        paid_map = {r[0]: bool(r[1]) for r in raw_ispaid}
    except:
        paid_map = {}
        
    res = []
    for t in transactions:
        tx_link_rows = link_map.get(int(t.TxID), [])
        tx_link_names = [str(x.get("SupplierName") or "").strip() for x in tx_link_rows if str(x.get("SupplierName") or "").strip()]
        supplier_name = "/".join(tx_link_names) if tx_link_names else (t.supplier.SupplierName if t.supplier else '誘몄긽')
        res.append({
            "TxID": t.TxID, "TxDate": t.TxDate, "TxType": t.TxType,
            "Amount": t.Amount, "Memo": t.Memo, "ReceiptPath": t.ReceiptPath,
            "IsPaid": paid_map.get(t.TxID, False),
            "SupplierName": supplier_name,
            # 변경 이유(Reason): [데이터 페칭] 프론트엔드 수정 연동을 위한 식별자(ID) 추가 송출
            "SupplierID": t.SupplierID,
            "SupplierLinks": tx_link_rows
        })
    return res

@router.post("/transactions")
async def create_or_update_transaction(
    tx_id: Optional[int] = Form(None),
    supplier_id: int = Form(0),
    supplier_links_raw: Optional[str] = Form(""),
    tx_type: str = Form(...),
    amount: float = Form(...),
    memo: Optional[str] = Form(""),
    is_paid: bool = Form(False),
    date: Optional[str] = Form(None), # 변경 이유(Reason): 프론트엔드에서 보낸 날짜 수신
    receipt: Optional[UploadFile] = File(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # (이미지 업로드 로직은 기존과 동일)
    receipt_path = None
    if receipt and getattr(receipt, "filename", None):
        UPLOAD_DIR = "static/uploads/receipts"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = receipt.filename.split(".")[-1]
        new_filename = f"tx_{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(UPLOAD_DIR, new_filename)
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await receipt.read()
            await out_file.write(content)
        receipt_path = f"/{file_path}"

    # 날짜 파싱 로직 추가
    target_date = datetime.now()
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            pass

    resolved_suppliers, unresolved_tokens = _resolve_multi_supplier_ids(
        db, current_user.company_id, supplier_links_raw or ""
    )
    raw_tokens = _split_supplier_tokens(supplier_links_raw or "")
    selected_supplier_id = int(supplier_id or 0)
    if unresolved_tokens and (len(raw_tokens) >= 2 or (selected_supplier_id <= 0 and len(raw_tokens) == 1)):
        for token in unresolved_tokens:
            _get_or_create_supplier(db, current_user.company_id, token)
        resolved_suppliers, unresolved_tokens = _resolve_multi_supplier_ids(
            db, current_user.company_id, supplier_links_raw or ""
        )
    if (supplier_links_raw or "").strip() and unresolved_tokens:
        raise HTTPException(
            status_code=400,
            detail=f"미등록 거래처: {', '.join(unresolved_tokens)}"
        )

    resolved_ids = [int(s.SupplierID) for s in resolved_suppliers]
    primary_supplier_id = selected_supplier_id
    if len(raw_tokens) >= 2 and resolved_ids:
        primary_supplier_id = resolved_ids[0]
    elif primary_supplier_id <= 0:
        primary_supplier_id = resolved_ids[0] if resolved_ids else 0
    if primary_supplier_id <= 0:
        raise HTTPException(status_code=400, detail="거래처를 선택해주세요.")
    if not resolved_ids:
        resolved_ids = [primary_supplier_id]
    elif primary_supplier_id not in resolved_ids:
        resolved_ids.insert(0, primary_supplier_id)

    if tx_id:
        tx = db.query(SupplierTransaction).filter(SupplierTransaction.TxID == tx_id, SupplierTransaction.CompanyID == current_user.company_id).first()
        if not tx: raise HTTPException(status_code=404)
        tx.SupplierID = primary_supplier_id
        tx.Amount = amount
        tx.Memo = memo
        tx.TxDate = target_date # 수정 시 날짜 반영
        if receipt_path: tx.ReceiptPath = receipt_path
        db.commit()
        target_id = tx_id
    else:
        new_tx = SupplierTransaction(
            CompanyID=current_user.company_id, SupplierID=primary_supplier_id, TxType=tx_type, Amount=amount, Memo=memo, ReceiptPath=receipt_path
        )
        new_tx.TxDate = target_date # 신규 생성 시 날짜 반영
        if hasattr(new_tx, 'MemberID'): new_tx.MemberID = getattr(current_user, "member_id", None)
        if hasattr(new_tx, 'IsActive'): new_tx.IsActive = True
        db.add(new_tx)
        db.commit()
        db.refresh(new_tx)
        target_id = new_tx.TxID

    # 동적 컬럼(IsPaid) 처리 부분 (이전과 동일)
    try:
        db.execute(text("ALTER TABLE erp_supplier_transactions ADD COLUMN IsPaid BOOLEAN DEFAULT 0"))
        db.commit()
    except: pass
    
    db.execute(text(f"UPDATE erp_supplier_transactions SET IsPaid = {int(is_paid)} WHERE TxID = {target_id}"))
    db.commit()
    _sync_supplier_tx_links(
        db=db,
        tx_id=int(target_id),
        company_id=int(current_user.company_id),
        supplier_ids=resolved_ids,
        primary_supplier_id=primary_supplier_id,
    )
    
    return {"status": "ok"}

@router.delete("/transactions/{tx_id}")
def delete_transaction(
    tx_id: int, 
    current_user = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    tx = db.query(SupplierTransaction).filter(
        SupplierTransaction.TxID == tx_id, 
        SupplierTransaction.CompanyID == current_user.company_id
    ).first()
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # 변경 이유(Reason): [데이터 페칭] 상태 플래그가 있으면 논리 삭제, 없으면 물리 삭제로 유연한 폴백(Fallback) 처리
    if hasattr(tx, 'IsActive'):
        tx.IsActive = False 
        db.commit()
    else:
        db.delete(tx)
        db.commit()

    try:
        _ensure_supplier_tx_links_table(db)
        db.query(SupplierTransactionLink).filter(
            SupplierTransactionLink.CompanyID == current_user.company_id,
            SupplierTransactionLink.TxID == tx_id
        ).update({"IsActive": False}, synchronize_session=False)
        db.commit()
    except Exception:
        pass
        
    return {"msg": "Transaction deleted"}


# ==========================================
# 2. 현장 지출 관리 (Field Expenses)
# ==========================================

@router.get("/expense-categories")
def get_expense_categories(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _seed_default_expense_categories(db, current_user.company_id)
    rows = db.execute(text("""
        SELECT
            CategoryID,
            CategoryName,
            COALESCE(Icon, '') AS Icon,
            COALESCE(SortOrder, 0) AS SortOrder
        FROM erp_expense_categories
        WHERE CompanyID = :company_id
          AND COALESCE(IsActive, 1) = 1
        ORDER BY SortOrder ASC, CategoryID ASC
    """), {"company_id": current_user.company_id}).mappings().all()
    return [{
        "CategoryID": int(row["CategoryID"] or 0),
        "CategoryName": row["CategoryName"] or "",
        "Icon": row["Icon"] or "",
        "SortOrder": int(row["SortOrder"] or 0),
        "IsLocked": _is_locked_expense_category(row["CategoryName"] or ""),
    } for row in rows]


@router.post("/expense-categories")
def create_or_update_expense_category(
    category_id: Optional[int] = Form(None),
    category_name: str = Form(...),
    icon: Optional[str] = Form(""),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _seed_default_expense_categories(db, current_user.company_id)
    normalized_name = _normalize_expense_category_name(category_name)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="항목명을 입력해주세요.")

    duplicate = db.execute(text("""
        SELECT CategoryID
        FROM erp_expense_categories
        WHERE CompanyID = :company_id
          AND COALESCE(IsActive, 1) = 1
          AND REPLACE(COALESCE(CategoryName, ''), ' ', '') = :normalized_name
          AND (:category_id IS NULL OR CategoryID <> :category_id)
        LIMIT 1
    """), {
        "company_id": current_user.company_id,
        "normalized_name": normalized_name,
        "category_id": category_id,
    }).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="같은 지출 항목이 이미 있습니다.")

    icon_text = str(icon or "").strip()
    if category_id:
        row = db.execute(text("""
            SELECT CategoryID, CategoryName
            FROM erp_expense_categories
            WHERE CategoryID = :category_id
              AND CompanyID = :company_id
            LIMIT 1
        """), {
            "category_id": category_id,
            "company_id": current_user.company_id,
        }).first()
        if not row:
            raise HTTPException(status_code=404, detail="지출 항목을 찾을 수 없습니다.")
        if _is_locked_expense_category(row.CategoryName or ""):
            raise HTTPException(status_code=400, detail="고정 공통비 카테고리는 이름을 변경할 수 없습니다.")
        db.execute(text("""
            UPDATE erp_expense_categories
            SET CategoryName = :category_name,
                Icon = :icon
            WHERE CategoryID = :category_id
              AND CompanyID = :company_id
        """), {
            "category_name": normalized_name,
            "icon": icon_text,
            "category_id": category_id,
            "company_id": current_user.company_id,
        })
        db.commit()
        return {"CategoryID": category_id, "CategoryName": normalized_name, "Icon": icon_text}

    max_sort = db.execute(text("""
        SELECT COALESCE(MAX(SortOrder), 0) AS max_sort
        FROM erp_expense_categories
        WHERE CompanyID = :company_id
    """), {"company_id": current_user.company_id}).scalar() or 0
    db.execute(text("""
        INSERT INTO erp_expense_categories
            (CompanyID, CategoryName, Icon, SortOrder, IsActive)
        VALUES
            (:company_id, :category_name, :icon, :sort_order, 1)
    """), {
        "company_id": current_user.company_id,
        "category_name": normalized_name,
        "icon": icon_text,
        "sort_order": int(max_sort) + 1,
    })
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {"CategoryID": int(new_id or 0), "CategoryName": normalized_name, "Icon": icon_text}


@router.delete("/expense-categories/{category_id}")
def delete_expense_category(
    category_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    row = db.execute(text("""
        SELECT CategoryID, CategoryName
        FROM erp_expense_categories
        WHERE CategoryID = :category_id
          AND CompanyID = :company_id
        LIMIT 1
    """), {
        "category_id": category_id,
        "company_id": current_user.company_id,
    }).first()
    if not row:
        raise HTTPException(status_code=404, detail="지출 항목을 찾을 수 없습니다.")
    if _is_locked_expense_category(row.CategoryName or ""):
        raise HTTPException(status_code=400, detail="고정 공통비 카테고리는 삭제할 수 없습니다.")

    db.execute(text("""
        UPDATE erp_expense_categories
        SET IsActive = 0
        WHERE CategoryID = :category_id
          AND CompanyID = :company_id
    """), {
        "category_id": category_id,
        "company_id": current_user.company_id,
    })
    db.commit()
    return {"msg": "Expense category deleted"}


@router.get("/expenses")
def get_expenses(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(FieldExpense).options(
        joinedload(FieldExpense.member), joinedload(FieldExpense.order)
    ).filter(FieldExpense.CompanyID == current_user.company_id)
    if not _can_admin_ledger_view(current_user):
        member_id = int(getattr(current_user, "member_id", 0) or 0)
        if member_id > 0:
            query = query.filter(FieldExpense.MemberID == member_id)
        else:
            return []
    
    if hasattr(FieldExpense, 'IsActive'): query = query.filter(FieldExpense.IsActive == True)
    
    if year and month:
        start_date = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = datetime(year, month, last_day, 23, 59, 59)
        query = query.filter(FieldExpense.ExpensedAt.between(start_date, end_date))
        
    if hasattr(FieldExpense, 'ExpensedAt'): query = query.order_by(FieldExpense.ExpensedAt.desc())

    rows = query.all()
    result = []
    for e in rows:
        member_name = ""
        if getattr(e, "member", None):
            member_name = str(getattr(e.member, "Name", "") or "").strip()
        result.append({
            "ExpenseID": e.ExpenseID,
            "CompanyID": e.CompanyID,
            "MemberID": e.MemberID,
            "MemberName": member_name,
            "OrderID": e.OrderID,
            "Category": e.Category,
            "Amount": e.Amount,
            "Memo": e.Memo,
            "ReceiptPath": e.ReceiptPath,
            "ExpensedAt": e.ExpensedAt,
            "IsActive": bool(getattr(e, "IsActive", True)),
        })
    return result

@router.post("/expenses")
async def create_or_update_expense(
    expense_id: Optional[int] = Form(None),
    category: str = Form(...),
    amount: float = Form(...),
    memo: Optional[str] = Form(""),
    order_id: Optional[int] = Form(None),
    date: Optional[str] = Form(None), # 변경 이유(Reason): 프론트엔드에서 보낸 날짜 수신
    receipt: Optional[UploadFile] = File(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    receipt_path = None
    if receipt and getattr(receipt, "filename", None):
        UPLOAD_DIR = "static/uploads/expenses"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = receipt.filename.split(".")[-1]
        new_filename = f"exp_{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(UPLOAD_DIR, new_filename)
        
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await receipt.read()
            await out_file.write(content)
            
        receipt_path = f"/{file_path}"

    # 날짜 파싱 로직 추가
    target_date = datetime.now()
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            pass

    if expense_id:
        expense = db.query(FieldExpense).filter(
            FieldExpense.ExpenseID == expense_id,
            FieldExpense.CompanyID == current_user.company_id
        ).first()
        
        if not expense: raise HTTPException(status_code=404, detail="지출 내역을 찾을 수 없습니다.")
        
        expense.Category = category
        expense.Amount = amount
        expense.Memo = memo
        expense.ExpensedAt = target_date # 수정 시 날짜 반영
        if order_id is not None: expense.OrderID = order_id
        if receipt_path: expense.ReceiptPath = receipt_path 
        
        db.commit()
        return expense
        
    else:
        new_expense = FieldExpense(
            CompanyID=current_user.company_id,
            Category=category,
            Amount=amount,
            Memo=memo,
            ReceiptPath=receipt_path
        )
        
        new_expense.ExpensedAt = target_date # 신규 생성 시 날짜 반영
        if hasattr(new_expense, 'MemberID'): new_expense.MemberID = getattr(current_user, "member_id", None)
        if hasattr(new_expense, 'OrderID'): new_expense.OrderID = order_id
        if hasattr(new_expense, 'IsActive'): new_expense.IsActive = True
        
        db.add(new_expense)
        db.commit()
        db.refresh(new_expense)
        return new_expense

@router.delete("/expenses/{expense_id}")
def delete_expense(
    expense_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    expense = db.query(FieldExpense).filter(
        FieldExpense.ExpenseID == expense_id, 
        FieldExpense.CompanyID == current_user.company_id
    ).first()
    
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    
    if hasattr(expense, 'IsActive'):
        expense.IsActive = False
        db.commit()
    else:
        db.delete(expense)
        db.commit()
        
    return {"msg": "Expense deleted"}

# ==========================================
# 3. 거래처 연동 API
# ==========================================

@router.get("/suppliers")
def get_active_suppliers(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(
        func.min(Supplier.SupplierID).label("SupplierID"),
        Supplier.SupplierName
    ).filter(
        Supplier.CompanyID == current_user.company_id
    )
    
    if hasattr(Supplier, 'IsActive'):
        query = query.filter(Supplier.IsActive != False)
        
    suppliers = query.group_by(Supplier.SupplierName).order_by(Supplier.SupplierName.asc()).all()
    
    return [{"SupplierID": s.SupplierID, "SupplierName": s.SupplierName} for s in suppliers]


@router.get("/suppliers/{supplier_id}")
def get_supplier_info(
    supplier_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Reason: [데이터 페칭] 렌더링에 필요한 업체 상세 정보만 단일 페칭
    supplier = db.query(Supplier).filter(
        Supplier.SupplierID == supplier_id,
        Supplier.CompanyID == current_user.company_id
    ).first()
    
    if not supplier: raise HTTPException(status_code=404, detail="업체 정보를 찾을 수 없습니다.")
    return {
        "SupplierID": supplier.SupplierID,
        "SupplierName": supplier.SupplierName or "",
        "ContactName": supplier.ContactName or "",
        "Phone": supplier.Phone or "",
        "Mobile": supplier.Mobile or "",
        "AccountInfo": supplier.AccountInfo or "",
        "MainItems": supplier.MainItems or "",
        "IsActive": bool(getattr(supplier, "IsActive", True)),
    }

@router.post("/suppliers/{supplier_id}")
async def update_supplier_info(
    supplier_id: int,
    SupplierName: str = Form(...),
    ContactName: str = Form(""),
    Phone: str = Form(""),
    Mobile: str = Form(""),
    AccountInfo: str = Form(""),
    MainItems: str = Form(""),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    normalized_name = _normalize_supplier_name(SupplierName)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="거래처명을 입력해주세요.")

    supplier = db.query(Supplier).filter(
        Supplier.SupplierID == supplier_id,
        Supplier.CompanyID == current_user.company_id
    ).first()
    
    if not supplier: raise HTTPException(status_code=404, detail="업체 정보를 찾을 수 없습니다.")
    
    # Reason: [안전성] 전달받은 폼 데이터로 업체 정보 업데이트
    source_supplier_name = (supplier.SupplierName or "").strip()

    duplicate = db.query(Supplier).filter(
        Supplier.CompanyID == current_user.company_id,
        Supplier.SupplierID != supplier_id,
        Supplier.SupplierName == normalized_name,
        Supplier.IsActive != False
    ).first()
    if duplicate:
        duplicate.ContactName = (ContactName or "").strip() or (duplicate.ContactName or "").strip() or (supplier.ContactName or "").strip()
        duplicate.Phone = _normalize_phone_like(Phone) or _normalize_phone_like(duplicate.Phone) or _normalize_phone_like(supplier.Phone)
        duplicate.Mobile = _normalize_phone_like(Mobile) or _normalize_phone_like(duplicate.Mobile) or _normalize_phone_like(supplier.Mobile)
        duplicate.AccountInfo = _normalize_phone_like(AccountInfo) or _normalize_phone_like(duplicate.AccountInfo) or _normalize_phone_like(supplier.AccountInfo)
        duplicate.MainItems = (MainItems or "").strip() or (duplicate.MainItems or "").strip() or (supplier.MainItems or "").strip()

        db.query(SupplierTransaction).filter(
            SupplierTransaction.CompanyID == current_user.company_id,
            SupplierTransaction.SupplierID == supplier_id
        ).update({"SupplierID": duplicate.SupplierID}, synchronize_session=False)
        try:
            _ensure_supplier_tx_links_table(db)
            db.query(SupplierTransactionLink).filter(
                SupplierTransactionLink.CompanyID == current_user.company_id,
                SupplierTransactionLink.SupplierID == supplier_id
            ).update({"SupplierID": duplicate.SupplierID}, synchronize_session=False)
        except Exception:
            pass
        db.query(SupplierProduct).filter(
            SupplierProduct.CompanyID == current_user.company_id,
            SupplierProduct.SupplierID == supplier_id
        ).update({"SupplierID": duplicate.SupplierID}, synchronize_session=False)

        affected_items = (
            db.query(models.OrderItem)
            .join(models.Order, models.Order.OrderID == models.OrderItem.OrderID)
            .filter(
                models.Order.CompanyID == current_user.company_id,
                models.OrderItem.Supplier.isnot(None),
            )
            .all()
        )
        normalized_source = _normalize_supplier_name(source_supplier_name)
        for item in affected_items:
            attrs = dict(item.Attributes) if isinstance(item.Attributes, dict) else {}
            raw_tokens = _split_supplier_tokens(item.Supplier)
            existing_links = attrs.get("supplier_links") if isinstance(attrs.get("supplier_links"), list) else []
            has_source_token = any(_normalize_supplier_name(token) == normalized_source for token in raw_tokens)
            has_source_link = any(
                _normalize_supplier_name((link or {}).get("name") or "") == normalized_source
                or int((link or {}).get("supplier_id") or 0) == supplier_id
                for link in existing_links
            )
            if not has_source_token and not has_source_link:
                continue
            replaced_tokens = [
                duplicate.SupplierName if _normalize_supplier_name(token) == normalized_source else token
                for token in raw_tokens
            ]
            item.Supplier = "/".join(replaced_tokens) if len(replaced_tokens) > 1 else duplicate.SupplierName
            attrs["supplier_id"] = duplicate.SupplierID
            updated_links = []
            seen_link_keys = set()
            for link in existing_links:
                link_name = str((link or {}).get("name") or "").strip()
                link_id = int((link or {}).get("supplier_id") or 0)
                if _normalize_supplier_name(link_name) == normalized_source or link_id == supplier_id:
                    link_name = duplicate.SupplierName
                    link_id = duplicate.SupplierID
                key = f"{link_id}:{link_name.lower()}"
                if not link_name or key in seen_link_keys:
                    continue
                seen_link_keys.add(key)
                updated_links.append({"name": link_name, "supplier_id": link_id})
            if not updated_links:
                for token in replaced_tokens:
                    token_name = str(token).strip()
                    if not token_name:
                        continue
                    token_id = duplicate.SupplierID if _normalize_supplier_name(token_name) == _normalize_supplier_name(duplicate.SupplierName) else 0
                    key = f"{token_id}:{token_name.lower()}"
                    if key in seen_link_keys:
                        continue
                    seen_link_keys.add(key)
                    updated_links.append({"name": token_name, "supplier_id": token_id})
            attrs["supplier_links"] = updated_links
            item.Attributes = attrs

        if hasattr(supplier, 'IsActive'):
            supplier.IsActive = False

        db.commit()
        return {
            "msg": "업체 정보가 수정되었습니다.",
            "merged": True,
            "SupplierID": duplicate.SupplierID,
            "SupplierName": duplicate.SupplierName
        }
        raise HTTPException(status_code=400, detail="이미 같은 이름의 거래처가 있습니다.")

    supplier.SupplierName = normalized_name
    supplier.ContactName = (ContactName or "").strip()
    supplier.Phone = _normalize_phone_like(Phone)
    supplier.Mobile = _normalize_phone_like(Mobile)
    supplier.AccountInfo = _normalize_phone_like(AccountInfo)
    supplier.MainItems = (MainItems or "").strip()
    
    db.commit()
    return {"msg": "업체 정보가 수정되었습니다."}

@router.post("/suppliers")
async def create_supplier(
    SupplierName: str = Form(...),
    ContactName: str = Form(""),
    Phone: str = Form(""),
    Mobile: str = Form(""),
    AccountInfo: str = Form(""),
    MainItems: str = Form(""),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 중복 업체명 방지
    existing = db.query(Supplier).filter(
        Supplier.CompanyID == current_user.company_id,
        Supplier.SupplierName == _normalize_supplier_name(SupplierName),
        Supplier.IsActive != False
    ).first()
    
    if existing: raise HTTPException(status_code=400, detail="이미 존재하는 거래처입니다.")

    # 변경 이유(Reason): [안전성] 제공된 DB 스키마(image_041064.png)에 맞추어 모든 컬럼을 수집 및 저장
    new_supplier = Supplier(
        CompanyID=current_user.company_id,
        SupplierName=_normalize_supplier_name(SupplierName),
        ContactName=(ContactName or "").strip(),
        Phone=_normalize_phone_like(Phone),
        Mobile=_normalize_phone_like(Mobile),
        AccountInfo=_normalize_phone_like(AccountInfo),
        MainItems=(MainItems or "").strip()
    )
    if hasattr(new_supplier, 'IsActive'): new_supplier.IsActive = True
        
    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)
    
    return {"status": "ok", "SupplierID": new_supplier.SupplierID, "SupplierName": new_supplier.SupplierName}


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    supplier = db.query(Supplier).filter(
        Supplier.SupplierID == supplier_id,
        Supplier.CompanyID == current_user.company_id
    ).first()

    if not supplier:
        raise HTTPException(status_code=404, detail="거래처 정보를 찾을 수 없습니다.")

    if hasattr(supplier, "IsActive"):
        supplier.IsActive = False
        db.commit()
    else:
        db.delete(supplier)
        db.commit()

    return {"status": "ok"}

@router.post("/transactions/{tx_id}/toggle-paid")
def toggle_transaction_payment(
    tx_id: int, 
    current_user = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    # Reason: [상태 머신] 입금/미입금 상태 반전 (DB 스키마 자동 복구 기능 포함)
    tx = db.query(SupplierTransaction).filter(
        SupplierTransaction.TxID == tx_id, 
        SupplierTransaction.CompanyID == current_user.company_id
    ).first()
    
    if not tx: raise HTTPException(status_code=404)
    
    try:
        # IsPaid 컬럼이 없으면 강제 생성 (Self-Healing)
        db.execute(text("ALTER TABLE erp_supplier_transactions ADD COLUMN IsPaid BOOLEAN DEFAULT 0"))
        db.commit()
    except: pass # 이미 존재하면 패스

    # 현재 상태 반전
    current_state = getattr(tx, 'IsPaid', False)
    db.execute(text(f"UPDATE erp_supplier_transactions SET IsPaid = {int(not current_state)} WHERE TxID = {tx_id}"))
    db.commit()
    
    return {"status": "ok", "is_paid": not current_state}

@router.get("/suppliers/{supplier_id}/stats")
def get_supplier_monthly_stats(
    supplier_id: int, 
    current_user = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    # Reason: [데이터 페칭] 그래프 렌더링을 위해 최근 6개월 청구액을 YYYY-MM 형태로 그룹화
    six_months_ago = datetime.now() - timedelta(days=180)
    
    txs = db.query(SupplierTransaction).filter(
        SupplierTransaction.CompanyID == current_user.company_id,
        SupplierTransaction.SupplierID == supplier_id,
        SupplierTransaction.TxDate >= six_months_ago
    ).all()
    
    stats_map = {}
    for t in txs:
        if not t.TxDate or getattr(t, 'IsActive', True) == False: continue
        ym = t.TxDate.strftime("%Y-%m")
        stats_map[ym] = stats_map.get(ym, 0) + float(t.Amount or 0)
        
    return [{"month": k, "amount": v} for k, v in sorted(stats_map.items())]

# ==========================================
# 4. 시계열 통계 전용 API (대시보드 공통 로직)
# ==========================================
from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import joinedload

# 날짜 연산 헬퍼 함수 (최대 12개월 전까지의 YYYY-MM 문자열 반환)
def get_ym_str_local(y, m, diff):
    nm = m - diff
    ny = y
    while nm <= 0: 
        nm += 12; ny -= 1
    return f"{ny}-{nm:02d}"

# [1] 현장 지출(/expense) 1년 추이 및 카테고리 비중 API
@router.get("/expenses/trend")
def get_expense_trend(
    year: int = Query(...), current_user = Depends(get_current_user), db: Session = Depends(get_db)
):
    start_trend = datetime(year - 2, 7, 1) 
    end_trend = datetime(year, 12, 31, 23, 59, 59)
    
    # Reason: 카테고리(Category) 필드를 추가로 Select하여 파이 차트용 데이터 추출
    query = db.query(FieldExpense.ExpensedAt, FieldExpense.Amount, FieldExpense.Category).filter(
        FieldExpense.CompanyID == current_user.company_id,
        FieldExpense.ExpensedAt >= start_trend, FieldExpense.ExpensedAt <= end_trend
    )
    if hasattr(FieldExpense, 'IsActive'): query = query.filter(FieldExpense.IsActive == True)
    
    exp_map = {}
    category_map = {}
    
    for e in query.all():
        if e.ExpensedAt:
            ym = e.ExpensedAt.strftime("%Y-%m")
            amt = float(e.Amount or 0)
            exp_map[ym] = exp_map.get(ym, 0) + amt
            
            # 변경 이유(Reason): [데이터 페칭] 선택된 해당 연도의 데이터만 카테고리에 합산하여 % 도출
            if e.ExpensedAt.year == year:
                cat = e.Category or '미분류'
                category_map[cat] = category_map.get(cat, 0) + amt
            
    trend_data = []
    for m in range(1, 13):
        cur_ym = f"{year}-{m:02d}"
        prev_ym = f"{year-1}-{m:02d}"
        sum_6 = sum(exp_map.get(get_ym_str_local(year, m, i), 0) for i in range(6))
        trend_data.append({ "month": m, "cur_val": exp_map.get(cur_ym, 0), "prev_val": exp_map.get(prev_ym, 0), "avg_6_val": sum_6 / 6.0 })
        
    return { "trend": trend_data, "categories": category_map }


# [2] 매입 원장(/ledger_admin) 1년 추이 및 거래처별 비중 API
@router.get("/trend_overall")
def get_ledger_trend_overall(
    year: int = Query(...), current_user = Depends(get_current_user), db: Session = Depends(get_db)
):
    start_trend = datetime(year - 2, 7, 1) 
    end_trend = datetime(year, 12, 31, 23, 59, 59)
    
    # Reason: 업체 이름(SupplierName)을 가져오기 위해 joinedload 사용
    query = db.query(SupplierTransaction).options(joinedload(SupplierTransaction.supplier)).filter(
        SupplierTransaction.CompanyID == current_user.company_id,
        SupplierTransaction.TxType == '청구',
        SupplierTransaction.TxDate >= start_trend, SupplierTransaction.TxDate <= end_trend
    )
    if hasattr(SupplierTransaction, 'IsActive'): query = query.filter(SupplierTransaction.IsActive == True)
    
    tx_map = {}
    supplier_map = {}
    
    for t in query.all():
        if t.TxDate:
            ym = t.TxDate.strftime("%Y-%m")
            amt = float(t.Amount or 0)
            tx_map[ym] = tx_map.get(ym, 0) + amt
            
            # 변경 이유(Reason): [데이터 페칭] 어느 업체에 자재비를 많이 외상했는지 집계
            if t.TxDate.year == year:
                sup_name = t.supplier.SupplierName if t.supplier else '미상'
                supplier_map[sup_name] = supplier_map.get(sup_name, 0) + amt
            
    trend_data = []
    for m in range(1, 13):
        cur_ym = f"{year}-{m:02d}"
        prev_ym = f"{year-1}-{m:02d}"
        sum_6 = sum(tx_map.get(get_ym_str_local(year, m, i), 0) for i in range(6))
        trend_data.append({ "month": m, "cur_val": tx_map.get(cur_ym, 0), "prev_val": tx_map.get(prev_ym, 0), "avg_6_val": sum_6 / 6.0 })
        
    return { "trend": trend_data, "categories": supplier_map }


# 1. 거래처(Supplier) 목록 조회 (업체명 드롭다운용)
@router.get("/suppliers")
def get_all_suppliers(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    suppliers = db.query(
        func.min(Supplier.SupplierID).label("SupplierID"),
        Supplier.SupplierName
    ).filter(
        Supplier.CompanyID == current_user.company_id
    )
    if hasattr(Supplier, 'IsActive'):
        suppliers = suppliers.filter(Supplier.IsActive != False)
    suppliers = suppliers.group_by(Supplier.SupplierName).order_by(Supplier.SupplierName.asc()).all()
    # 프론트가 기대하는 JSON 배열 형태로 응답
    return [{"SupplierID": s.SupplierID, "SupplierName": s.SupplierName} for s in suppliers]

# 2. 제품명 자동완성 및 원가 연동 검색 API (에러 방어벽 탑재)
@router.get("/products/search")
def search_supplier_products(
    q: str = Query(...),
    category: Optional[str] = Query(None),
    subcategory: Optional[str] = Query(None),
    supplier: Optional[str] = Query(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        category = normalize_category_name((category or '').strip())
        subcategory = normalize_subcategory_name((subcategory or '').strip(), category)
        supplier = (supplier or '').strip()
        query_text = (q or '').strip()

        print(
            "[PRODUCT SEARCH DEBUG] "
            f"company={current_user.company_id} q={query_text!r} "
            f"category={category!r} subcategory={subcategory!r} supplier={supplier!r}"
        )
        sql = text("""
            SELECT
                p.ProductID,
                p.SupplierID,
                COALESCE(p.Category, '') AS Category,
                COALESCE(p.SubCategory, '') AS SubCategory,
                COALESCE(p.ProductName, '') AS ProdName,
                COALESCE(s.SupplierName, '') AS SupplierName,
                COALESCE(p.CostPrice, 0) AS CostPrice,
                COALESCE(p.SellingPrice, 0) AS SellingPrice,
                COALESCE(p.Color, '') AS Color,
                COALESCE(p.`Option`, '') AS `Option`,
                COALESCE(p.Note, '') AS Note
            FROM erp_supplier_products p
            LEFT JOIN erp_suppliers s ON s.SupplierID = p.SupplierID
            WHERE p.CompanyID = :company_id
              AND COALESCE(p.ProductName, '') LIKE :like_q
              AND COALESCE(p.IsActive, 1) = 1
              AND (:category = '' OR COALESCE(p.Category, '') = :category)
              AND (:subcategory = '' OR COALESCE(p.SubCategory, '') = :subcategory)
            ORDER BY
              CASE
                WHEN :supplier = '' THEN 0
                WHEN COALESCE(s.SupplierName, '') = :supplier THEN 0
                WHEN COALESCE(s.SupplierName, '') LIKE :supplier_prefix THEN 1
                WHEN COALESCE(s.SupplierName, '') LIKE :supplier_like THEN 2
                ELSE 3
              END,
              CASE
                WHEN COALESCE(p.ProductName, '') = :query_text THEN 0
                WHEN COALESCE(p.ProductName, '') LIKE :query_prefix THEN 1
                WHEN COALESCE(p.ProductName, '') LIKE :like_q THEN 2
                ELSE 3
              END,
              COALESCE(s.SupplierName, '') ASC,
              COALESCE(p.ProductName, '') ASC
            LIMIT 20
        """)

        sql_params = {
            "company_id": current_user.company_id,
            "query_text": query_text,
            "query_prefix": f"{query_text}%",
            "like_q": f"%{query_text}%",
            "category": category,
            "subcategory": subcategory,
            "supplier": supplier,
            "supplier_prefix": f"{supplier}%",
            "supplier_like": f"%{supplier}%",
        }

        print("[PRODUCT SEARCH DEBUG] sql(raw)=erp_supplier_products direct query")
        print("[PRODUCT SEARCH DEBUG] sql_params=" + repr(sql_params))

        rows = db.execute(sql, sql_params).mappings().all()

        print(
            "[PRODUCT SEARCH DEBUG] raw_top="
            + repr([
                {
                    "id": int(row["ProductID"] or 0),
                    "category": row["Category"] or "",
                    "subcategory": row["SubCategory"] or "",
                    "supplier": row["SupplierName"] or "",
                    "name": row["ProdName"] or "",
                }
                for row in rows[:5]
            ])
        )

        return [
            {
                "ProductID": int(row["ProductID"] or 0),
                "SupplierID": int(row["SupplierID"] or 0),
                "Category": row["Category"] or "",
                "SubCategory": row["SubCategory"] or "",
                "ProdName": row["ProdName"] or "",
                "SupplierName": row["SupplierName"] or "미상",
                "CostPrice": float(row["CostPrice"] or 0),
                "SellingPrice": float(row["SellingPrice"] or 0),
                "Color": row["Color"] or "",
                "Option": row["Option"] or "",
                "Note": row["Note"] or ""
            }
            for row in rows
        ]
    except Exception as e:
        print(f"[Search API 오류 발생] 원인: {str(e)}")
        return []
