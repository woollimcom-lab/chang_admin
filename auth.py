# [auth.py] 최종 해결 버전
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from fastapi import Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from jose import jwt, JWTError # ★ JWTError 추가됨
from passlib.context import CryptContext
import models

class NeedsLogin(Exception): pass

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "chang_areum_secret_key_2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

def verify_password(plain, hashed): return plain == hashed
def get_password_hash(password): return password
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_user_or_key(request: Request, db: Session):
    # -------------------------------------------------------
    # [1] 내부 직원 확인 (쿠키 인증)
    # -------------------------------------------------------
    token = request.cookies.get("access_token")
    
    if token:
        try:
            # 토큰 정제
            clean_token = token.split(" ")[1] if token.startswith("Bearer ") else token
            
            # 토큰 검증
            payload = jwt.decode(clean_token, SECRET_KEY, algorithms=[ALGORITHM])
            login_id: str = payload.get("sub")
            
            if login_id:
                user = db.query(models.User).filter(models.User.LoginID == login_id).first()
                if user:
                    uid = user.UserID
                    member = db.query(models.CompanyMember).filter(models.CompanyMember.UserID == uid).first()
                    cid = member.CompanyID if member else getattr(user, 'company_id', None)
                    
                    # 권한 설정 (대표는 무조건 True)
                    is_master = (member.RoleName == '대표') if member else False
                    has_perm = (member.Perm_EditSchedule if member else False) or is_master

                    return {
                        "type": "user", 
                        "company_id": cid, 
                        "name": user.Name, 
                        "user_id": uid,
                        "member_id": member.ID if member else 0, 
                        "perm_schedule": has_perm
                    }
        except Exception as e:
            pass

    # -------------------------------------------------------
    # [2] 외주팀 확인 (Access Key 인증)
    # -------------------------------------------------------
    try:
        key = request.query_params.get("key") or request.query_params.get("access_key")
        if not key:
            try:
                form = await request.form()
                key = form.get("access_key") or form.get("key")
            except: pass

        if key:
            member = db.query(models.CompanyMember).filter(models.CompanyMember.AccessKey == key).first()
            if member:
                return {
                    "type": "external", 
                    "company_id": member.CompanyID, 
                    "name": f"{member.Name}(외주)", 
                    "member_id": member.ID, 
                    "perm_schedule": False
                }
    except: pass
    
    return None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db), 
    token_header: str = Depends(oauth2_scheme)
):
    # 1. 토큰 추출
    if not isinstance(token_header, str):
        token_header = None

    token = None
    if isinstance(request, str):
        token = request # 직접 토큰이 들어온 경우
    else:
        # request 객체에서 쿠키나 헤더 추출
        try:
            token = request.cookies.get("access_token") or token_header
        except:
            token = token_header

    if not isinstance(token, str) or not token: raise NeedsLogin()

    try:
        if token.startswith("Bearer "): token = token.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        login_id: str = payload.get("sub")
        if login_id is None: raise NeedsLogin()
    except JWTError: raise NeedsLogin()
        
    # 2. DB 연결선 확인 (안전장치)
    real_db = db
    if not hasattr(db, 'query'):
        from database import SessionLocal
        real_db = SessionLocal()

    user = real_db.query(models.User).filter(models.User.LoginID == login_id).first()
    if user is None: raise NeedsLogin()

    member = real_db.query(models.CompanyMember).filter(models.CompanyMember.UserID == user.UserID).first()
    if member:
        user.company_id = member.CompanyID
        user.role_name = member.RoleName
        user.member_id = member.ID      
        user.member_name = member.Name  
        user.member_type = member.Type
        user.perm_revenue = member.Perm_ViewRevenue
        user.perm_expense = member.Perm_ViewExpense
        user.perm_margin  = member.Perm_ViewMargin
        user.perm_total   = member.Perm_ViewTotal
        user.perm_staff   = member.Perm_ManageStaff
        user.perm_stats   = member.Perm_ViewStats
        user.perm_schedule= member.Perm_EditSchedule
        return user
    
    raise HTTPException(status_code=400, detail="소속된 회사가 없습니다.")
