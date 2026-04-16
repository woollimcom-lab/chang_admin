from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from auth import get_current_user
import json
from datetime import datetime, timedelta
import re
import os
import models
from services.view_service import sync_order_managers

router = APIRouter(prefix="/api/voice", tags=["Voice"])


class VoiceDraftCreateRequest(BaseModel):
    pageContext: str
    rawText: str
    context: dict = {}


class VoiceApplyRequest(BaseModel):
    draftId: int
    applySelections: dict


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_datetime_candidate(value: str | None) -> datetime | None:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def _current_member(db: Session, current_user):
    member = (
        db.query(models.CompanyMember)
        .filter(
            models.CompanyMember.CompanyID == current_user.company_id,
            models.CompanyMember.UserID == getattr(current_user, "UserID", None),
        )
        .first()
    )
    if member:
        return member

    member_id = getattr(current_user, "member_id", None)
    if member_id:
        member = (
            db.query(models.CompanyMember)
            .filter(
                models.CompanyMember.CompanyID == current_user.company_id,
                models.CompanyMember.ID == member_id,
            )
            .first()
        )
        if member:
            return member

    raise HTTPException(status_code=403, detail="직원 정보를 찾을 수 없습니다.")


def _append_order_history(db: Session, order_id: int, log_type: str, contents: str, member_name: str | None = None):
    db.add(
        models.OrderHistory(
            OrderID=order_id,
            LogType=log_type,
            Contents=contents,
            MemberName=member_name,
        )
    )


def _next_sort_order(db: Session, order_id: int) -> int:
    max_sort = (
        db.query(models.OrderItem.SortOrder)
        .filter(models.OrderItem.OrderID == order_id)
        .order_by(models.OrderItem.SortOrder.desc())
        .first()
    )
    return _safe_int(max_sort[0] if max_sort else 0, 0) + 1


def _ensure_voice_tables(db: Session):
    db.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS voice_capture_drafts (
            DraftID INT AUTO_INCREMENT PRIMARY KEY,
            CompanyID INT NOT NULL,
            MemberID INT NULL,
            PageContext VARCHAR(30) NOT NULL,
            RawText TEXT NULL,
            NormalizedText TEXT NULL,
            IntentType VARCHAR(50) NULL,
            ActionType VARCHAR(50) NULL,
            MatchedOrderID INT NULL,
            MatchedCustomerID INT NULL,
            ConfidenceScore DECIMAL(6,3) NULL,
            DraftJSON LONGTEXT NULL,
            Status VARCHAR(20) NOT NULL DEFAULT 'pending',
            CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            AppliedAt DATETIME NULL,
            INDEX idx_voice_drafts_company_status (CompanyID, Status),
            INDEX idx_voice_drafts_page (PageContext)
        )
    """
        )
    )
    db.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS voice_apply_logs (
            ApplyLogID INT AUTO_INCREMENT PRIMARY KEY,
            DraftID INT NOT NULL,
            CompanyID INT NOT NULL,
            AppliedByMemberID INT NULL,
            TargetType VARCHAR(50) NOT NULL,
            TargetID INT NULL,
            AppliedJSON LONGTEXT NULL,
            CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_voice_apply_company (CompanyID),
            INDEX idx_voice_apply_draft (DraftID)
        )
    """
        )
    )
    db.commit()


def _infer_item_category(product_name: str) -> str:
    name = (product_name or "").strip().lower()
    if not name:
        return "음성초안"
    if "블라인드" in name or "롤스크린" in name or "허니콤" in name:
        return "블라인드"
    if "커튼" in name or "차르르" in name or "쉬폰" in name:
        return "커튼"
    return "음성초안"


def _detect_view_schedule_field(text_norm: str, action_type: str) -> str:
    if action_type == "AS_REQUEST" or any(x in text_norm for x in ["AS", "A/S", "수선", "고장"]):
        return "as_datetime"
    if any(x in text_norm for x in ["시공", "작업", "설치", "완료"]):
        return "construction_datetime"
    return "visit_datetime"


def _save_dashboard_lead(
    db: Session,
    current_user,
    member,
    draft_json: dict,
    proposals: dict,
    sels: dict,
):
    raw_text = draft_json.get("rawText", "")
    context = draft_json.get("context") or {}

    schedule_idxs = [idx for idx in (sels.get("scheduleUpdates") or []) if isinstance(idx, int)]
    item_idxs = [idx for idx in (sels.get("itemAdds") or []) if isinstance(idx, int)]
    memo_idxs = [idx for idx in (sels.get("memoAdds") or []) if isinstance(idx, int)]

    schedule_items = proposals.get("scheduleUpdates") or []
    item_items = proposals.get("itemAdds") or []
    memo_items = proposals.get("memoAdds") or []

    selected_schedule = [schedule_items[i] for i in schedule_idxs if 0 <= i < len(schedule_items)]
    selected_items = [item_items[i] for i in item_idxs if 0 <= i < len(item_items)]
    selected_memos = [memo_items[i] for i in memo_idxs if 0 <= i < len(memo_items)]
    if not selected_schedule and not selected_items:
        raise HTTPException(
            status_code=400,
            detail="Dashboard apply requires at least one selected schedule or item proposal",
        )

    consult_candidates = proposals.get("consultTypeCandidates") or []
    consult_type = consult_candidates[0] if consult_candidates else draft_json.get("actionType", "QUOTE_REQUEST")
    status_map = {
        "QUOTE_REQUEST": "견적상담",
        "VISIT_REQUEST": "방문상담",
        "PRODUCT_INQUIRY": "견적상담",
        "CALLBACK_REQUEST": "견적상담",
        "PENDING_CALLBACK": "견적상담",
    }
    progress_status = status_map.get(consult_type, "견적상담")

    customer_name = (context.get("customerName") or "신규상담").strip()
    address_parts = []
    site_candidates = proposals.get("siteCandidates") or []
    dong_ho_candidates = proposals.get("dongHoCandidates") or []
    if site_candidates:
        address_parts.append(site_candidates[0])
    if dong_ho_candidates:
        address_parts.append(dong_ho_candidates[0].get("text") or "")
    address = " ".join([x for x in address_parts if x]).strip()
    if not address:
        address = context.get("address") or ""

    visit_dt = None
    if selected_schedule:
        visit_dt = _parse_datetime_candidate(selected_schedule[0].get("proposedValue"))

    new_order = models.Order(
        CompanyID=current_user.company_id,
        CustomerName=customer_name,
        PhoneNumber=context.get("phoneNumber") or "",
        Address=address,
        RequestDate=datetime.now(),
        ProgressStatus=progress_status,
        VisitDate=visit_dt if progress_status == "방문상담" else None,
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

    sort_order = _next_sort_order(db, new_order.OrderID)
    for item in selected_items:
        location = (item.get("location") or "").strip()
        product = (item.get("product") or "").strip()
        if not product:
            continue
        db.add(
            models.OrderItem(
                OrderID=new_order.OrderID,
                SortOrder=sort_order,
                Location=location or "미지정",
                Category=_infer_item_category(product),
                Category1=product,
                cate1=product,
                Quantity=1,
                UnitPrice=0,
                LineTotal=0,
                Width=0,
                Height=0,
            )
        )
        sort_order += 1

    memo_lines = [raw_text]
    memo_lines.extend([m.get("text", "") for m in selected_memos if m.get("text")])
    _append_order_history(
        db,
        new_order.OrderID,
        "음성초안",
        "\n".join([x for x in memo_lines if x]).strip(),
        member.Name,
    )

    if visit_dt:
        _append_order_history(
            db,
            new_order.OrderID,
            "상태변경",
            f"[음성초안/방문제안] 방문시간 {visit_dt.strftime('%Y-%m-%d %H:%M')}",
            member.Name,
        )

    return {
        "targetType": "new_order",
        "targetId": new_order.OrderID,
        "payload": {
            "orderId": new_order.OrderID,
            "progressStatus": progress_status,
            "visitDate": visit_dt.strftime("%Y-%m-%d %H:%M") if visit_dt else None,
        },
    }


def _apply_view_changes(
    db: Session,
    current_user,
    member,
    row: dict,
    draft_json: dict,
    proposals: dict,
    sels: dict,
):
    order_id = _safe_int((draft_json.get("context") or {}).get("orderId") or row.get("MatchedOrderID"), 0)
    if order_id <= 0:
        raise HTTPException(status_code=400, detail="orderId required for view apply")

    order = (
        db.query(models.Order)
        .filter(models.Order.OrderID == order_id, models.Order.CompanyID == current_user.company_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    applied = []
    schedule_idxs = [idx for idx in (sels.get("scheduleUpdates") or []) if isinstance(idx, int)]
    item_idxs = [idx for idx in (sels.get("itemAdds") or []) if isinstance(idx, int)]
    memo_idxs = [idx for idx in (sels.get("memoAdds") or []) if isinstance(idx, int)]

    schedule_items = proposals.get("scheduleUpdates") or []
    item_items = proposals.get("itemAdds") or []
    memo_items = proposals.get("memoAdds") or []

    for idx in schedule_idxs:
        if not (0 <= idx < len(schedule_items)):
            continue
        item = schedule_items[idx]
        dt = _parse_datetime_candidate(item.get("proposedValue"))
        if not dt:
            continue
        field = (item.get("field") or "").strip()
        if field == "as_datetime":
            order.ASDate = dt
            field_label = "AS 일정"
        elif field == "construction_datetime":
            order.ConstructionDate = dt
            field_label = "시공 일정"
        elif field == "visit_datetime":
            order.VisitDate = dt
            field_label = "방문 일정"
        else:
            if order.ProgressStatus == "AS요청":
                order.ASDate = dt
                field_label = "AS 일정"
            elif order.ProgressStatus in ["시공예정", "작업완료"]:
                order.ConstructionDate = dt
                field_label = "시공 일정"
            else:
                order.VisitDate = dt
                field_label = "방문 일정"
        applied.append({"targetType": "schedule_update", "targetId": order_id, "payload": item})
        _append_order_history(
            db,
            order_id,
            "상태변경",
            f"[음성반영/일정변경] {field_label} {dt.strftime('%Y-%m-%d %H:%M')}",
            getattr(member, "Name", getattr(current_user, "Name", None)),
        )

    sort_order = _next_sort_order(db, order_id)
    for idx in item_idxs:
        if not (0 <= idx < len(item_items)):
            continue
        item = item_items[idx]
        product = (item.get("product") or "").strip()
        location = (item.get("location") or "").strip()
        if not product:
            continue
        new_item = models.OrderItem(
            OrderID=order_id,
            SortOrder=sort_order,
            Location=location or "미지정",
            Category=_infer_item_category(product),
            Category1=product,
            cate1=product,
            Quantity=1,
            UnitPrice=0,
            LineTotal=0,
            Width=0,
            Height=0,
        )
        db.add(new_item)
        sort_order += 1
        applied.append({"targetType": "item_add", "targetId": order_id, "payload": item})
        line = f"{location + ' / ' if location else ''}{product}"
        _append_order_history(
            db,
            order_id,
            "상태변경",
            f"[음성반영/품목추가] {line}",
            getattr(member, "Name", getattr(current_user, "Name", None)),
        )

    for idx in memo_idxs:
        if not (0 <= idx < len(memo_items)):
            continue
        item = memo_items[idx]
        text_line = (item.get("text") or "").strip()
        if not text_line:
            continue
        applied.append({"targetType": "memo_add", "targetId": order_id, "payload": item})
        _append_order_history(
            db,
            order_id,
            "메모",
            f"[음성반영] {text_line}",
            getattr(member, "Name", getattr(current_user, "Name", None)),
        )

    return applied


def _save_ledger_expense(
    db: Session,
    current_user,
    member,
    row: dict,
    draft_json: dict,
    proposals: dict,
):
    expense = proposals.get("expenseDraft") or {}
    amount = _safe_float(expense.get("amount"), 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="expense amount is required")

    category = (expense.get("category") or expense.get("item") or "기타").strip() or "기타"
    vendor = (expense.get("vendorCandidate") or "").strip()
    status = (expense.get("status") or "").strip()
    payer_type = (expense.get("payerType") or "").strip()
    raw_text = (draft_json.get("rawText") or "").strip()

    memo_parts = []
    if vendor:
        memo_parts.append(f"업체:{vendor}")
    if payer_type:
        memo_parts.append(f"부담:{payer_type}")
    if status:
        memo_parts.append(f"상태:{status}")
    if raw_text:
        memo_parts.append(raw_text)
    memo = " | ".join(memo_parts)

    order_id = _safe_int((draft_json.get("context") or {}).get("orderId") or row.get("MatchedOrderID"), 0)
    order_id = order_id if order_id > 0 else None

    new_expense = models.FieldExpense(
        CompanyID=current_user.company_id,
        MemberID=getattr(member, "ID", None),
        OrderID=order_id,
        Category=category,
        Amount=amount,
        Memo=memo,
        ExpensedAt=datetime.now(),
    )
    if hasattr(new_expense, "IsActive"):
        new_expense.IsActive = True
    db.add(new_expense)
    db.flush()

    return {
        "targetType": "expense_draft",
        "targetId": new_expense.ExpenseID,
        "payload": {
            "expenseId": new_expense.ExpenseID,
            "amount": amount,
            "category": category,
            "memo": memo,
        },
    }


ROOM_LOCATION_WORDS = ["거실", "안방", "작은방", "주방", "베란다", "드레스룸", "현관", "서재", "아이방"]
PRODUCT_WORDS = [
    "차르르",
    "암막커튼",
    "쉬폰",
    "블라인드",
    "롤스크린",
    "허니콤",
    "콤비블라인드",
    "우드블라인드",
    "커튼",
]
PRODUCT_ALIASES = {
    "차르르": "차르르",
    "암막": "암막커튼",
    "암막커튼": "암막커튼",
    "쉬폰": "쉬폰",
    "블라인드": "블라인드",
    "롤스크린": "롤스크린",
    "롤 스크린": "롤스크린",
    "허니콤": "허니콤",
    "콤비": "콤비블라인드",
    "콤비블라인드": "콤비블라인드",
    "우드블라인드": "우드블라인드",
    "커튼": "커튼",
}
CONSULT_TYPE_KEYWORDS = {
    "QUOTE_REQUEST": ["견적", "견적문의"],
    "VISIT_REQUEST": ["방문", "방문요청", "실측", "상담"],
    "PRODUCT_INQUIRY": ["제품문의", "제품 문의", "문의"],
    "CALLBACK_REQUEST": ["콜백", "연락", "전화"],
}
COMPLEX_SUFFIXES = ["힐스테이트", "푸르지오", "래미안", "자이", "더샵", "아이파크", "아파트", "빌라"]

EXPENSE_CATEGORY_WORDS = ["식대", "주유", "자재", "운송", "배송", "통행료", "주차", "수리", "공구"]
EXPENSE_STATUS_KEYWORDS = {
    "credit": ["외상"],
    "unpaid": ["미결제", "미지급", "후불"],
    "paid": ["결제완료", "지급완료", "완납", "카드결제", "현금결제"],
}
PERSONAL_PAYER_KEYWORDS = ["내 돈", "내돈", "개인", "개인카드"]
COMPANY_PAYER_KEYWORDS = ["회사", "법인", "법인카드", "회사카드"]


def normalize_text(raw: str) -> str:
    text_norm = re.sub(r"\s+", " ", str(raw or "").strip())
    text_norm = text_norm.replace("A/S", "AS")
    return text_norm


def _korean_tens_normalize(text_norm: str) -> str:
    return (
        text_norm.replace("스무", "이십")
        .replace("서른", "삼십")
        .replace("마흔", "사십")
        .replace("쉰", "오십")
        .replace("예순", "육십")
        .replace("일흔", "칠십")
        .replace("여든", "팔십")
        .replace("아흔", "구십")
    )


def _tokenize_korean_number(text_norm: str) -> list[str]:
    src = _korean_tens_normalize(text_norm).replace(" ", "")
    tokens = []
    i = 0
    while i < len(src):
        rest = src[i:]
        multi = next((w for w in ["하나", "둘", "셋", "넷"] if rest.startswith(w)), None)
        if multi:
            tokens.append(multi)
            i += len(multi)
            continue
        ch = src[i]
        if ch.isdigit():
            j = i
            while j < len(src) and src[j].isdigit():
                j += 1
            tokens.append(src[i:j])
            i = j
            continue
        tokens.append(ch)
        i += 1
    return tokens


def parse_korean_integer(text_norm: str) -> int | None:
    if not text_norm:
        return None
    digit_words = {
        "영": 0,
        "공": 0,
        "일": 1,
        "하나": 1,
        "한": 1,
        "이": 2,
        "둘": 2,
        "두": 2,
        "삼": 3,
        "셋": 3,
        "세": 3,
        "사": 4,
        "넷": 4,
        "네": 4,
        "오": 5,
        "육": 6,
        "륙": 6,
        "칠": 7,
        "팔": 8,
        "구": 9,
    }
    small_units = {"십": 10, "백": 100, "천": 1000}
    large_units = {"만": 10000, "억": 100000000}

    tokens = _tokenize_korean_number(text_norm)
    if not tokens:
        return None

    total = 0
    section = 0
    number = 0
    seen = False

    for tok in tokens:
        if tok.isdigit():
            number = int(tok)
            seen = True
            continue
        if tok in digit_words:
            number = digit_words[tok]
            seen = True
            continue
        if tok in small_units:
            if number == 0:
                number = 1
            section += number * small_units[tok]
            number = 0
            seen = True
            continue
        if tok in large_units:
            if section == 0 and number == 0:
                section = 1
            else:
                section += number
            total += section * large_units[tok]
            section = 0
            number = 0
            seen = True
            continue

    if not seen:
        return None
    return total + section + number


def parse_amount_candidate(text_norm: str) -> int | None:
    numeric = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(만원|원)?", text_norm)
    if numeric:
        unit = numeric.group(2) or "원"
        value = float(numeric.group(1).replace(",", ""))
        return int(round(value * 10000 if unit == "만원" else value))

    korean_match = re.search(
        r"([영공일이삼사오육륙칠팔구십백천만억하나둘셋넷스무서른마흔쉰예순일흔여든아흔 ]+)\s*원",
        text_norm,
    )
    if korean_match:
        return parse_korean_integer(korean_match.group(1))

    return None


def parse_time_candidates(text_norm: str) -> list[dict]:
    now = datetime.now()
    candidates = []
    seen = set()
    pattern = re.compile(r"(오늘|내일|모레)?\s*(오전|오후)?\s*(\d{1,2})\s*시(?:\s*(반|\d{1,2}\s*분)?)?")
    day_offsets = {"오늘": 0, "내일": 1, "모레": 2}
    weekday_map = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

    for m in pattern.finditer(text_norm):
        day_word = m.group(1) or "오늘"
        meridiem = m.group(2)
        hour = int(m.group(3))
        minute_token = m.group(4)
        minute = 0
        if minute_token:
            minute = 30 if minute_token == "반" else int(minute_token.replace("분", "").strip())
        if meridiem == "오후" and hour < 12:
            hour += 12
        if meridiem == "오전" and hour == 12:
            hour = 0

        target = (now + timedelta(days=day_offsets.get(day_word, 0))).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        key = target.strftime("%Y-%m-%d %H:%M")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "text": m.group(0).strip(),
                "value": key,
                "status": "pending",
            }
        )

    week_pattern = re.compile(r"(다음주\s*)?([월화수목금토일])요일?\s*(오전|오후)?\s*(\d{1,2})\s*시(?:\s*(반|\d{1,2}\s*분)?)?")
    for m in week_pattern.finditer(text_norm):
        is_next_week = bool(m.group(1))
        weekday_kor = m.group(2)
        meridiem = m.group(3)
        hour = int(m.group(4))
        minute_token = m.group(5)
        minute = 0
        if minute_token:
            minute = 30 if minute_token == "반" else int(minute_token.replace("분", "").strip())
        if meridiem == "오후" and hour < 12:
            hour += 12
        if meridiem == "오전" and hour == 12:
            hour = 0

        target_weekday = weekday_map.get(weekday_kor)
        if target_weekday is None:
            continue
        delta = target_weekday - now.weekday()
        if delta < 0:
            delta += 7
        if is_next_week or delta == 0:
            delta += 7
        target = (now + timedelta(days=delta)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        key = target.strftime("%Y-%m-%d %H:%M")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "text": m.group(0).strip(),
                "value": key,
                "status": "pending",
            }
        )
    return candidates


def parse_complex_candidates(text_norm: str, site_hints: list[str] | None = None) -> list[str]:
    candidates = []

    for suffix in COMPLEX_SUFFIXES:
        for m in re.finditer(rf"([가-힣A-Za-z0-9]+{suffix})", text_norm):
            candidates.append(m.group(1))

    for hint in (site_hints or []):
        h = (hint or "").strip()
        if h and h in text_norm:
            candidates.append(h)

    dong_match = re.search(r"([가-힣A-Za-z0-9]+)\s*(\d{1,4})\s*동", text_norm)
    if dong_match:
        token = dong_match.group(1)
        if len(token) >= 2:
            candidates.append(token)

    unique = []
    seen = set()
    for item in candidates:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    return unique[:5]


def parse_dong_ho_candidates(text_norm: str) -> list[dict]:
    candidates = []
    seen = set()

    for m in re.finditer(r"(\d{1,4})\s*동\s*(\d{1,4})\s*호", text_norm):
        dong = m.group(1)
        ho = m.group(2)
        key = f"{dong}-{ho}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"dong": dong, "ho": ho, "text": f"{dong}동 {ho}호", "status": "pending"})

    for m in re.finditer(r"(\d{1,4})\s*동", text_norm):
        dong = m.group(1)
        if any(x.get("dong") == dong for x in candidates):
            continue
        key = f"{dong}-"
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"dong": dong, "ho": None, "text": f"{dong}동", "status": "pending"})

    for m in re.finditer(r"(\d{1,4})\s*호", text_norm):
        ho = m.group(1)
        key = f"-{ho}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"dong": None, "ho": ho, "text": f"{ho}호", "status": "pending"})

    return candidates[:5]


def parse_product_candidates(text_norm: str, product_hints: list[str] | None = None) -> list[str]:
    candidates = []
    for alias, normalized in PRODUCT_ALIASES.items():
        if alias in text_norm:
            candidates.append(normalized)
    for hint in (product_hints or []):
        h = (hint or "").strip()
        if h and h in text_norm:
            candidates.append(h)
    unique = []
    seen = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:6]


def parse_item_candidates(
    text_norm: str,
    fallback_location: str = "",
    location_hints: list[str] | None = None,
    product_hints: list[str] | None = None,
) -> list[dict]:
    found_locations = [w for w in ROOM_LOCATION_WORDS if w in text_norm]
    for hint in (location_hints or []):
        h = (hint or "").strip()
        if h and h in text_norm and h not in found_locations:
            found_locations.append(h)
    found_products = parse_product_candidates(text_norm, product_hints=product_hints)
    pairs = []
    if found_locations and found_products:
        for i, loc in enumerate(found_locations):
            prod = found_products[i] if i < len(found_products) else found_products[0]
            pairs.append({"location": loc, "product": prod, "status": "pending"})
    elif found_products:
        for prod in found_products:
            pairs.append({"location": fallback_location, "product": prod, "status": "pending"})
    return pairs[:8]


def detect_dashboard_action(text_norm: str) -> str:
    for action, keywords in CONSULT_TYPE_KEYWORDS.items():
        if any(word in text_norm for word in keywords):
            return action
    return "PENDING_CALLBACK"


def detect_view_action(text_norm: str) -> str:
    if any(x in text_norm for x in ["AS", "수선", "고장", "A/S"]):
        return "AS_REQUEST"

    has_schedule = any(x in text_norm for x in ["변경", "바꿔", "연기", "앞당", "내일", "모레", "오늘", "오전", "오후", "시"])
    has_item = any(x in text_norm for x in ["추가", "차르르", "암막", "블라인드", "롤스크린", "허니콤", "커튼"])

    if has_schedule and has_item:
        return "SCHEDULE_UPDATE+ITEM_ADD"
    if has_schedule:
        return "SCHEDULE_UPDATE"
    if has_item:
        return "ITEM_ADD"
    return "WORK_LOG_ADD"


def detect_intent(page_context: str, text_norm: str) -> tuple[str, str]:
    if page_context == "ledger":
        if "자재" in text_norm:
            return ("EXPENSE", "MATERIAL_PURCHASE")
        if any(x in text_norm for x in PERSONAL_PAYER_KEYWORDS):
            return ("EXPENSE", "PERSONAL_ADVANCE")
        return ("EXPENSE", "GENERAL_EXPENSE")

    if page_context == "dashboard":
        return ("NEW_LEAD", detect_dashboard_action(text_norm))

    if page_context == "view":
        return ("EXISTING_CUSTOMER", detect_view_action(text_norm))

    return ("FOLLOWUP_MEMO", "PENDING_CALLBACK")


def detect_consult_type_candidates(text_norm: str) -> list[str]:
    found = []
    for action, keywords in CONSULT_TYPE_KEYWORDS.items():
        if any(word in text_norm for word in keywords):
            found.append(action)
    if not found:
        found.append("PENDING_CALLBACK")
    return found


def parse_expense_candidates(
    text_norm: str,
    category_hints: list[str] | None = None,
    supplier_hints: list[str] | None = None,
) -> dict:
    amount = parse_amount_candidate(text_norm)

    category = None
    for word in EXPENSE_CATEGORY_WORDS:
        if word in text_norm:
            category = word
            break
    if not category:
        for hint in (category_hints or []):
            h = (hint or "").strip()
            if h and h in text_norm:
                category = h
                break

    vendor = None
    vendor_match = re.search(r"([가-힣A-Za-z0-9]+(?:상사|마트|주유소|상회|카센터|공업사|식당|기업|사))", text_norm)
    if vendor_match:
        vendor = vendor_match.group(1)
    else:
        first = text_norm.split(" ")[0] if text_norm else ""
        if first and not re.search(r"\d", first) and first not in EXPENSE_CATEGORY_WORDS:
            if first not in ["내", "내돈", "내돈으로", "회사", "회사돈", "법인", "외상"]:
                vendor = first
    if not vendor:
        for hint in (supplier_hints or []):
            h = (hint or "").strip()
            if h and h in text_norm:
                vendor = h
                break

    item = category
    if not item:
        for token in ["자재", "주유", "식대", "부품", "공구", "소모품", "운송", "배송", "주차", "통행료"]:
            if token in text_norm:
                item = token
                break

    payer_type = None
    if any(x in text_norm for x in PERSONAL_PAYER_KEYWORDS):
        payer_type = "personal"
    elif any(x in text_norm for x in COMPANY_PAYER_KEYWORDS):
        payer_type = "company"

    status = None
    for status_key, words in EXPENSE_STATUS_KEYWORDS.items():
        if any(w in text_norm for w in words):
            status = status_key
            break

    return {
        "amount": amount,
        "item": item,
        "category": category,
        "vendorCandidate": vendor,
        "payerType": payer_type,
        "status": status,
    }


def build_draft(page_context: str, text_norm: str, intent_type: str, action_type: str, context: dict) -> dict:
    proposals = {
        "scheduleUpdates": [],
        "itemAdds": [],
        "memoAdds": [],
        "expenseDraft": None,
        "siteCandidates": [],
        "dongHoCandidates": [],
        "visitTimeCandidates": [],
        "productCandidates": [],
        "consultTypeCandidates": [],
    }

    if page_context == "view":
        schedule_field = _detect_view_schedule_field(text_norm, action_type)
        time_candidates = parse_time_candidates(text_norm)
        for candidate in time_candidates:
            proposals["scheduleUpdates"].append(
                {
                    "field": schedule_field,
                    "currentValue": None,
                    "proposedValue": candidate["value"],
                    "sourceText": candidate["text"],
                    "status": "pending",
                }
            )
        proposals["itemAdds"] = parse_item_candidates(
            text_norm,
            location_hints=context.get("recentLocations") or [],
            product_hints=context.get("recentProducts") or [],
        )
        proposals["memoAdds"].append(
            {
                "text": text_norm,
                "memoType": "as_request" if action_type == "AS_REQUEST" else "general",
                "status": "pending",
            }
        )

    elif page_context == "dashboard":
        hint_products = context.get("recentProducts") or []
        hint_sites = context.get("recentSiteNames") or []
        dong_ho_candidates = parse_dong_ho_candidates(text_norm)
        time_candidates = parse_time_candidates(text_norm)
        product_candidates = parse_product_candidates(text_norm, product_hints=hint_products)
        site_candidates = parse_complex_candidates(text_norm, site_hints=hint_sites)
        consult_candidates = detect_consult_type_candidates(text_norm)

        fallback_location = dong_ho_candidates[0]["text"] if dong_ho_candidates else ""
        proposals["itemAdds"] = parse_item_candidates(
            text_norm,
            fallback_location=fallback_location,
            location_hints=hint_sites,
            product_hints=hint_products,
        )
        if time_candidates:
            top = time_candidates[0]
            proposals["scheduleUpdates"].append(
                {
                    "field": "visit_datetime",
                    "currentValue": None,
                    "proposedValue": top["value"],
                    "sourceText": top["text"],
                    "status": "pending",
                }
            )

        proposals["memoAdds"].append({"text": text_norm, "memoType": "new_lead", "status": "pending"})
        proposals["siteCandidates"] = site_candidates
        proposals["dongHoCandidates"] = dong_ho_candidates
        proposals["visitTimeCandidates"] = time_candidates
        proposals["productCandidates"] = product_candidates
        proposals["consultTypeCandidates"] = consult_candidates

    elif page_context == "ledger":
        proposals["expenseDraft"] = parse_expense_candidates(
            text_norm,
            category_hints=context.get("recentCategories") or [],
            supplier_hints=context.get("recentSuppliers") or [],
        )
        proposals["memoAdds"].append({"text": text_norm, "memoType": "expense_note", "status": "pending"})

    confidence = 0.50
    if page_context == "view":
        if proposals["scheduleUpdates"] or proposals["itemAdds"]:
            confidence = 0.82
        else:
            confidence = 0.68
    elif page_context == "ledger":
        expense = proposals.get("expenseDraft") or {}
        if expense.get("amount") and (expense.get("item") or expense.get("category")):
            confidence = 0.86
        elif expense.get("amount"):
            confidence = 0.79
        else:
            confidence = 0.63
    elif page_context == "dashboard":
        quality_hits = 0
        quality_hits += 1 if proposals["siteCandidates"] else 0
        quality_hits += 1 if proposals["dongHoCandidates"] else 0
        quality_hits += 1 if proposals["visitTimeCandidates"] else 0
        quality_hits += 1 if proposals["productCandidates"] else 0
        confidence = min(0.66 + (quality_hits * 0.06), 0.90)

    return {
        "intentType": intent_type,
        "actionType": action_type,
        "pageContext": page_context,
        "confidence": confidence,
        "rawText": text_norm,
        "context": context,
        "proposals": proposals,
    }


def _load_draft_row(db: Session, draft_id: int, company_id: int):
    return db.execute(
        text(
            """
        SELECT *
        FROM voice_capture_drafts
        WHERE DraftID = :draft_id AND CompanyID = :company_id
    """
        ),
        {"draft_id": draft_id, "company_id": company_id},
    ).mappings().first()


@router.post("/draft")
def create_voice_draft(payload: VoiceDraftCreateRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_voice_tables(db)
    text_norm = normalize_text(payload.rawText)
    intent_type, action_type = detect_intent(payload.pageContext, text_norm)
    draft_json = build_draft(payload.pageContext, text_norm, intent_type, action_type, payload.context)

    db.execute(
        text(
            """
        INSERT INTO voice_capture_drafts
        (CompanyID, MemberID, PageContext, RawText, NormalizedText, IntentType, ActionType, MatchedOrderID, MatchedCustomerID, ConfidenceScore, DraftJSON, Status)
        VALUES
        (:company_id, :member_id, :page_context, :raw_text, :normalized_text, :intent_type, :action_type, :matched_order_id, :matched_customer_id, :confidence, :draft_json, 'pending')
    """
        ),
        {
            "company_id": current_user.company_id,
            "member_id": getattr(current_user, "member_id", None),
            "page_context": payload.pageContext,
            "raw_text": payload.rawText,
            "normalized_text": text_norm,
            "intent_type": intent_type,
            "action_type": action_type,
            "matched_order_id": payload.context.get("orderId"),
            "matched_customer_id": payload.context.get("customerId"),
            "confidence": draft_json["confidence"],
            "draft_json": json.dumps(draft_json, ensure_ascii=False),
        },
    )
    db.commit()
    draft_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return {
        "ok": True,
        "draftId": draft_id,
        "intentType": intent_type,
        "actionType": action_type,
        "confidence": draft_json["confidence"],
        "draft": draft_json,
    }


@router.get("/drafts")
def list_voice_drafts(
    status: str = "pending",
    pageContext: str | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_voice_tables(db)
    sql = """
        SELECT DraftID, PageContext, RawText, IntentType, ActionType, ConfidenceScore, Status, CreatedAt
        FROM voice_capture_drafts
        WHERE CompanyID = :company_id AND Status = :status
    """
    params = {"company_id": current_user.company_id, "status": status}
    if pageContext:
        sql += " AND PageContext = :page_context"
        params["page_context"] = pageContext
    sql += " ORDER BY DraftID DESC LIMIT 100"
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/drafts/{draft_id}")
def get_voice_draft(draft_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_voice_tables(db)
    row = _load_draft_row(db, draft_id, current_user.company_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    result = dict(row)
    if result.get("DraftJSON"):
        result["DraftJSON"] = json.loads(result["DraftJSON"])
    return result


@router.post("/discard")
def discard_voice_draft(payload: dict, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_voice_tables(db)
    draft_id = payload.get("draftId")
    if not draft_id:
        raise HTTPException(status_code=400, detail="draftId required")
    db.execute(
        text(
            """
        UPDATE voice_capture_drafts
        SET Status = 'discarded'
        WHERE DraftID = :draft_id AND CompanyID = :company_id
    """
        ),
        {"draft_id": draft_id, "company_id": current_user.company_id},
    )
    db.commit()
    return {"ok": True}


@router.post("/apply")
def apply_voice_draft(payload: VoiceApplyRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_voice_tables(db)
    row = _load_draft_row(db, payload.draftId, current_user.company_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft_json = json.loads(row["DraftJSON"]) if row.get("DraftJSON") else {}
    proposals = draft_json.get("proposals") or {}
    sels = payload.applySelections or {}
    page_context = row.get("PageContext") or draft_json.get("pageContext")
    member = _current_member(db, current_user)

    applied_entries = []
    try:
        if page_context == "dashboard":
            applied_entries.append(
                _save_dashboard_lead(db, current_user, member, draft_json, proposals, sels)
            )
        elif page_context == "ledger":
            if not sels.get("expenseDraft"):
                raise HTTPException(status_code=400, detail="expenseDraft selection required")
            applied_entries.append(
                _save_ledger_expense(db, current_user, member, row, draft_json, proposals)
            )
        elif page_context == "view":
            applied_entries.extend(
                _apply_view_changes(db, current_user, member, row, draft_json, proposals, sels)
            )
            if sels.get("memoOnly"):
                order_id = _safe_int((draft_json.get("context") or {}).get("orderId") or row.get("MatchedOrderID"), 0)
                if order_id > 0:
                    _append_order_history(
                        db,
                        order_id,
                        "메모",
                        f"[음성원문] {draft_json.get('rawText', '')}",
                        getattr(member, "Name", getattr(current_user, "Name", None)),
                    )
                    applied_entries.append(
                        {
                            "targetType": "memo_only",
                            "targetId": order_id,
                            "payload": {"rawText": draft_json.get("rawText", "")},
                        }
                    )
        else:
            raise HTTPException(status_code=400, detail="Unsupported pageContext")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"apply failed: {e}")

    if not applied_entries:
        raise HTTPException(status_code=400, detail="No valid selections to apply")

    for entry in applied_entries:
        db.execute(
            text(
                """
            INSERT INTO voice_apply_logs
            (DraftID, CompanyID, AppliedByMemberID, TargetType, TargetID, AppliedJSON)
            VALUES
            (:draft_id, :company_id, :applied_by, :target_type, :target_id, :applied_json)
        """
            ),
            {
                "draft_id": payload.draftId,
                "company_id": current_user.company_id,
                "applied_by": getattr(current_user, "member_id", None),
                "target_type": entry["targetType"],
                "target_id": entry["targetId"],
                "applied_json": json.dumps(entry["payload"], ensure_ascii=False),
            },
        )

    db.execute(
        text(
            """
        UPDATE voice_capture_drafts
        SET Status = 'applied'
        WHERE DraftID = :draft_id AND CompanyID = :company_id
    """
        ),
        {"draft_id": payload.draftId, "company_id": current_user.company_id},
    )
    db.commit()

    return {
        "ok": True,
        "message": "Draft marked as applied",
        "draftId": payload.draftId,
        "appliedEntries": applied_entries,
        "draft": draft_json,
    }


@router.post("/stt")
async def transcribe_voice_audio(
    audio: UploadFile = File(...),
    language: str = Form("ko"),
    model: str = Form("gpt-4o-mini-transcribe"),
    current_user=Depends(get_current_user),
):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"openai sdk import failed: {e}")

    try:
        content = await audio.read()
        if not content:
            raise HTTPException(status_code=400, detail="audio file is empty")

        client = OpenAI(api_key=api_key)
        transcript = client.audio.transcriptions.create(
            model=model,
            file=(audio.filename or "voice.webm", content, audio.content_type or "audio/webm"),
            language=language,
        )
        text_result = (getattr(transcript, "text", None) or "").strip()
        if not text_result:
            raise HTTPException(status_code=422, detail="transcription text is empty")

        return {
            "ok": True,
            "text": text_result,
            "model": model,
            "language": language,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stt transcribe failed: {e}")
