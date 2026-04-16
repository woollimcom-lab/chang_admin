from typing import List

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import get_user_or_key
from database import get_db
from services.photo_service import (
    delete_photo_action,
    get_order_photos_action,
    upload_item_photo_action,
    upload_photo_action,
)


router = APIRouter()


@router.post("/api/photo/upload")
async def upload_photo(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})
    return await upload_photo_action(request, files, db, auth)


@router.post("/api/photo/upload-item")
async def upload_item_photo(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})
    return await upload_item_photo_action(request, files, db, auth)


@router.get("/api/photo/list/{order_id}")
async def get_order_photos(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(status_code=403, content={"msg": "권한이 없습니다."})
    return get_order_photos_action(order_id, db, auth)


@router.post("/api/photo/delete")
async def delete_photo(
    request: Request,
    photo_id: int = Form(...),
    db: Session = Depends(get_db),
):
    auth = await get_user_or_key(request, db)
    if not auth:
        return JSONResponse(status_code=403, content={"msg": "접근 권한이 없습니다."})
    return delete_photo_action(photo_id, db, auth)
