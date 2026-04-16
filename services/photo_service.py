import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps
from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import models


BASE_DIR = Path(__file__).resolve().parents[1]


def _safe_part(s: str, max_len: int = 20) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:max_len]


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


def _compose_item_label(item) -> str:
    loc = _item_detail_value(item, "Location")
    item_name = _compose_item_name(item)
    return " ".join([p for p in [loc, item_name] if p]).strip()


def _make_photo_filename(order, item, stage_label: str) -> str:
    now = datetime.now().strftime("%Y%m%d-%H%M")
    cust = _safe_part(getattr(order, "CustomerName", "") or "고객", 12)
    loc = _safe_part(getattr(item, "Location", "") if item else "", 14)
    prod = _safe_part(_compose_item_name(item) if item else "", 14)
    stage = _safe_part(stage_label.upper(), 10)
    rnd = uuid.uuid4().hex[:8]
    parts = [now, cust]
    if loc:
        parts.append(loc)
    if prod:
        parts.append(prod)
    parts.append(stage)
    parts.append(rnd)
    return "__".join(parts) + ".jpg"


def normalize_photo_type(photo_type: str) -> str:
    t = (photo_type or "").strip().lower()
    if t in ("site", "before"):
        return "before"
    if t in ("completion", "after"):
        return "after"
    if t == "during":
        return "during"
    return "after"


def process_image_1000_with_watermark(content: bytes, label: str) -> Image.Image:
    img = Image.open(io.BytesIO(content))
    # Mobile photos often rely on EXIF orientation instead of rotated pixels.
    # Normalize first so saved JPEGs keep the expected upright direction.
    img = ImageOps.exif_transpose(img)
    img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    text = (label or "").upper().strip()
    if not text:
        return img

    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    pad = 10
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = draw.textsize(text, font=font)

    x = pad
    y = img.height - th - pad
    box = (x - 6, y - 6, x + tw + 10, y + th + 8)
    draw.rectangle(box, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return img


def _append_photo_history(db: Session, order_id: int, content: str, member_name: str) -> None:
    db.add(models.OrderHistory(
        OrderID=order_id,
        LogType="상태변경",
        Contents=content,
        MemberName=member_name,
    ))


async def upload_photo_action(request: Request, files: List[UploadFile], db: Session, auth: dict):
    form = await request.form()
    order_id = int(form.get("order_id"))
    photo_type = normalize_photo_type(form.get("photo_type"))
    item_id_raw = form.get("item_id")
    item_id = int(item_id_raw) if (item_id_raw and str(item_id_raw).isdigit()) else None

    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return JSONResponse(status_code=403, content={"msg": "잘못된 접근입니다."})

    item = None
    if item_id is not None:
        item = db.query(models.OrderItem).filter(
            models.OrderItem.ItemID == item_id,
            models.OrderItem.OrderID == order_id,
        ).first()
        if not item:
            return JSONResponse(status_code=400, content={"msg": "품목 정보가 올바르지 않습니다."})

    upload_dir = BASE_DIR / "static" / "uploads" / str(order_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    items = db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).all()
    tag_list = set()
    for each in items:
        for tag_val in [
            each.Category,
            each.Category1,
            each.Location,
            _item_detail_value(each, "cate1", "ProductName"),
            _item_detail_value(each, "cate2"),
            _item_detail_value(each, "cate3", "OptionInfo"),
        ]:
            if tag_val:
                tag_list.add(tag_val)
    tags_str = ",".join(tag_list)

    wm_label = "AFTER" if photo_type == "after" else ("BEFORE" if photo_type == "before" else "DURING")
    stage_kor = "전" if photo_type == "before" else ("중" if photo_type == "during" else "후")
    saved_count = 0

    for file in files:
        try:
            content = await file.read()
            img = process_image_1000_with_watermark(content, wm_label)
            filename = _make_photo_filename(order, item, wm_label)
            filepath = upload_dir / filename
            img.save(filepath, "JPEG", quality=85)

            db_path = f"/static/uploads/{order_id}/{filename}"
            db.add(models.OrderPhoto(
                OrderID=order_id,
                ItemID=item_id,
                FilePath=db_path,
                FileName=file.filename,
                FileType=photo_type,
                Tags=tags_str,
            ))
            saved_count += 1

            who = auth.get("name") or "시스템"
            if item:
                item_txt = _compose_item_label(item) or f"품목#{item_id}"
            else:
                item_txt = "주문공통"
            _append_photo_history(db, order_id, f"📷 [사진등록-{stage_kor}] {item_txt}", who)
        except Exception as e:
            print(f"이미지 업로드 실패: {e}")
            continue

    db.commit()
    return {"status": "ok", "count": saved_count}


async def upload_item_photo_action(request: Request, files: List[UploadFile], db: Session, auth: dict):
    form = await request.form()
    order_id = int(form.get("order_id"))
    item_id = int(form.get("item_id"))
    photo_type = normalize_photo_type(form.get("photo_type") or "after")

    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return JSONResponse(status_code=403, content={"msg": "잘못된 접근입니다."})

    item = db.query(models.OrderItem).filter(
        models.OrderItem.ItemID == item_id,
        models.OrderItem.OrderID == order_id,
    ).first()
    if not item:
        return JSONResponse(status_code=400, content={"msg": "품목 정보가 올바르지 않습니다."})

    upload_dir = BASE_DIR / "static" / "uploads" / str(order_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    tag_list = set()
    for tag_val in [item.Category, item.Category1, item.Location, item.cate1, item.cate2, item.cate3]:
        if tag_val:
            tag_list.add(tag_val)
    tags_str = ",".join(tag_list)

    wm_label = "AFTER" if photo_type == "after" else ("BEFORE" if photo_type == "before" else "DURING")
    stage_kor = "전" if photo_type == "before" else ("중" if photo_type == "during" else "후")
    saved_count = 0

    for file in files:
        try:
            content = await file.read()
            img = process_image_1000_with_watermark(content, wm_label)
            filename = _make_photo_filename(order, item, wm_label)
            filepath = upload_dir / filename
            img.save(filepath, "JPEG", quality=85)

            db_path = f"/static/uploads/{order_id}/{filename}"
            db.add(models.OrderPhoto(
                OrderID=order_id,
                ItemID=item_id,
                FilePath=db_path,
                FileName=file.filename,
                FileType=photo_type,
                Tags=tags_str,
            ))
            saved_count += 1

            who = auth.get("name") or "시스템"
            item_txt = _compose_item_label(item) or f"품목#{item_id}"
            _append_photo_history(db, order_id, f"📷 [사진등록-{stage_kor}] {item_txt}", who)
        except Exception as e:
            print(f"이미지 업로드 실패(item): {e}")
            continue

    db.commit()
    return {"status": "ok", "count": saved_count, "photo_type": photo_type}


def get_order_photos_action(order_id: int, db: Session, auth: dict):
    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth["company_id"],
    ).first()
    if not order:
        return JSONResponse(status_code=403, content={"msg": "잘못된 접근입니다."})

    photos = db.query(models.OrderPhoto).filter(
        models.OrderPhoto.OrderID == order_id
    ).order_by(models.OrderPhoto.PhotoID.desc()).all()
    return photos


def delete_photo_action(photo_id: int, db: Session, auth: dict):
    photo = db.query(models.OrderPhoto).filter(models.OrderPhoto.PhotoID == photo_id).first()
    if not photo:
        return JSONResponse(status_code=404, content={"msg": "사진을 찾을 수 없습니다."})

    order = db.query(models.Order).filter(models.Order.OrderID == photo.OrderID).first()
    if not order or order.CompanyID != auth["company_id"]:
        return JSONResponse(status_code=403, content={"msg": "삭제 권한이 없습니다."})

    try:
        real_path = BASE_DIR / photo.FilePath.lstrip("/")
        if real_path.exists():
            os.remove(real_path)
    except Exception as e:
        print(f"파일 삭제 오류: {e}")

    db.delete(photo)
    db.commit()
    return {"status": "ok"}
