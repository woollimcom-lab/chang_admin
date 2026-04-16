from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services.order_service import create_order_action


router = APIRouter()


@router.post("/create-order")
async def create_order(
    req: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return await create_order_action(req, db, current_user)
