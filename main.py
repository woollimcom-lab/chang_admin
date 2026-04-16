from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import text, inspect as sa_inspect
import os
import time
import uuid
from urllib.parse import quote

# OPENAI_API_KEY는 코드에 하드코딩하지 않고 프로세스 환경변수에서만 주입한다.

# 사용자 정의 모듈
import models 
from routers import dashboard_router, marketing, photo_router, admin_router, ledger_router, stats_router, voice_router, item_master_router, item_router, view_router, apt_router, company_router, misc_router, auth_router, order_router, codex_chat_router
from database import engine
# ★ [중요] get_user_or_key가 여기로 이동했으니 꼭 가져와야 합니다.
from auth import NeedsLogin

# ★ 해결 포인트: app = FastAPI()를 무조건 여기로 끌어올려야 합니다!
app = FastAPI()

# ??? ??
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(dashboard_router.router)
app.include_router(marketing.router)
app.include_router(photo_router.router)
app.include_router(ledger_router.router)
app.include_router(stats_router.router)
app.include_router(voice_router.router)
app.include_router(item_master_router.router)
app.include_router(item_router.router)
app.include_router(view_router.router)
app.include_router(apt_router.router)
app.include_router(company_router.router)
app.include_router(codex_chat_router.router)
app.include_router(misc_router.router)
app.include_router(order_router.router)

# DB ??? ??
models.Base.metadata.create_all(bind=engine)
# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

# ==============================================================================
# [DB 자동 마이그레이션 엔진] 서버 시작 시 누락된 컬럼 안전하게 자동 생성
# ==============================================================================
def run_startup_migrations():
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    
    if not inspector.has_table("erp_supplier_products"):
        return

    cols_prod = {col["name"] for col in inspector.get_columns("erp_supplier_products")}
    migration_targets = ["Color", "Option", "Note"]

    with engine.begin() as conn:
        for col_name in migration_targets:
            if col_name not in cols_prod:
                try:
                    conn.execute(text(f"ALTER TABLE erp_supplier_products ADD COLUMN {col_name} VARCHAR(255) NULL"))
                    cols_prod.add(col_name)
                    print(f"✅ [Migration] erp_supplier_products 테이블에 {col_name} 컬럼 추가 성공!")
                except Exception as e:
                    print(f"❌ [Migration Error] {col_name} 추가 실패: {str(e)}")

# ★ 서버 가동 시 무조건 1회 실행되도록 밖으로 빼서 호출
run_startup_migrations()

def ensure_orderitems_cate_columns():
    """OrderItems를 cate1~cate4 공통 슬롯 구조로 마이그레이션합니다."""
    try:
        with engine.connect() as conn:
            inspector = sa_inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("OrderItems")}
            changed = False

            if "cate1" not in cols and "ProductName" in cols:
                conn.execute(text("ALTER TABLE OrderItems CHANGE COLUMN ProductName cate1 VARCHAR(100) NULL"))
                cols.discard("ProductName")
                cols.add("cate1")
                changed = True
            elif "cate1" not in cols:
                conn.execute(text("ALTER TABLE OrderItems ADD COLUMN cate1 VARCHAR(100) NULL AFTER Category1"))
                cols.add("cate1")
                changed = True
            elif "ProductName" in cols:
                conn.execute(text("UPDATE OrderItems SET cate1 = CASE WHEN cate1 IS NULL OR cate1 = '' THEN ProductName ELSE cate1 END WHERE ProductName IS NOT NULL"))
                conn.execute(text("ALTER TABLE OrderItems DROP COLUMN ProductName"))
                cols.discard("ProductName")
                changed = True

            if "cate2" not in cols:
                after_col = "cate1" if "cate1" in cols else "Category1"
                conn.execute(text(f"ALTER TABLE OrderItems ADD COLUMN cate2 VARCHAR(100) NULL AFTER {after_col}"))
                cols.add("cate2")
                changed = True

            if "cate3" not in cols and "OptionInfo" in cols:
                conn.execute(text("ALTER TABLE OrderItems CHANGE COLUMN OptionInfo cate3 VARCHAR(100) NULL"))
                cols.discard("OptionInfo")
                cols.add("cate3")
                changed = True
            elif "cate3" not in cols:
                after_col = "cate2" if "cate2" in cols else ("cate1" if "cate1" in cols else "Category1")
                conn.execute(text(f"ALTER TABLE OrderItems ADD COLUMN cate3 VARCHAR(100) NULL AFTER {after_col}"))
                cols.add("cate3")
                changed = True
            elif "OptionInfo" in cols:
                conn.execute(text("UPDATE OrderItems SET cate3 = CASE WHEN cate3 IS NULL OR cate3 = '' THEN OptionInfo ELSE cate3 END WHERE OptionInfo IS NOT NULL"))
                conn.execute(text("ALTER TABLE OrderItems DROP COLUMN OptionInfo"))
                cols.discard("OptionInfo")
                changed = True

            if "cate4" not in cols and "ItemMemo" in cols:
                conn.execute(text("ALTER TABLE OrderItems CHANGE COLUMN ItemMemo cate4 TEXT NULL"))
                cols.discard("ItemMemo")
                cols.add("cate4")
                changed = True
            elif "cate4" not in cols:
                conn.execute(text("ALTER TABLE OrderItems ADD COLUMN cate4 TEXT NULL AFTER LineTotal"))
                cols.add("cate4")
                changed = True
            elif "ItemMemo" in cols:
                conn.execute(text("UPDATE OrderItems SET cate4 = CASE WHEN cate4 IS NULL OR cate4 = '' THEN ItemMemo ELSE cate4 END WHERE ItemMemo IS NOT NULL"))
                conn.execute(text("ALTER TABLE OrderItems DROP COLUMN ItemMemo"))
                cols.discard("ItemMemo")
                changed = True

            if changed:
                conn.commit()
    except Exception as e:
        print("[WARN] ensure_orderitems_cate_columns failed:", e)


def ensure_orderphotos_itemid_column():
    """MySQL: OrderPhotos 테이블에 ItemID 컬럼이 없으면 자동으로 추가합니다."""
    try:
        with engine.connect() as conn:
            db_name = conn.execute(text("SELECT DATABASE()")).scalar()
            if not db_name:
                return
            exists = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=:db AND TABLE_NAME='OrderPhotos' AND COLUMN_NAME='ItemID'"
            ), {"db": db_name}).scalar()
            if int(exists or 0) == 0:
                conn.execute(text("ALTER TABLE OrderPhotos ADD COLUMN ItemID INT NULL"))
                conn.execute(text("CREATE INDEX idx_orderphotos_itemid ON OrderPhotos (ItemID)"))
                conn.commit()
    except Exception as e:
        print("[WARN] ensure_orderphotos_itemid_column failed:", e)


ensure_orderitems_cate_columns()
ensure_orderphotos_itemid_column()

# 임시 메모리 저장소 (문자 인증용)
@app.exception_handler(NeedsLogin)
async def login_required_handler(request: Request, exc: NeedsLogin):
    # 1. 만약 API 요청(데이터만 요청)인데 로그인이 안된 경우 -> 401 에러 (JSON)
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=401, 
            content={"detail": "로그인이 만료되었습니다. 다시 로그인해주세요."}
        )
    
    # 2. 웹페이지(대시보드 등) 접속인데 로그인이 안된 경우 -> 로그인 페이지로 이동
    next_url = quote(str(request.url.path or "/dashboard"), safe="/?=&")
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    request_id = uuid.uuid4().hex[:8]
    query_string = request.url.query or ""
    print(f"[MIDDLEWARE] checkpoint=request_enter request_id={request_id} method={request.method} path={request.url.path} query={query_string} timestamp={time.time():.6f}")
    print(f"[MIDDLEWARE] checkpoint=before_call_next request_id={request_id} path={request.url.path}")
    try:
        response = await call_next(request)
    except Exception as exc:
        process_time = time.time() - start_time
        print(f"[MIDDLEWARE] checkpoint=middleware_exception request_id={request_id} path={request.url.path} exception_type={type(exc).__name__} exception_message={str(exc)} elapsed_ms={process_time * 1000:.1f}")
        raise
    process_time = time.time() - start_time
    print(f"[MIDDLEWARE] checkpoint=after_call_next request_id={request_id} path={request.url.path} status_code={response.status_code} elapsed_ms={process_time * 1000:.1f}")
    # 터미널에 시간 출력 (소수점 4자리까지)
    print(f"[TIMING] [{request.url.path}] 처리 시간: {process_time:.4f}초")
    return response


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ==============================================================================
# [0] 헬퍼 함수 & 템플릿 필터
# ==============================================================================
@app.on_event("startup")
def optimize_database():
    """
    [수정됨] 테이블 이름(대소문자)을 자동으로 확인하여 인덱스를 생성합니다.
    """
    try:
        from sqlalchemy import text
        # 모델에서 정확한 테이블 이름을 가져옵니다 (Order vs orders)
        target_table = "Orders"
        
        with engine.connect() as conn:
            # f-string을 사용해 정확한 테이블 이름으로 인덱스 생성
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_stat ON {target_table} (CompanyID, ProgressStatus)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_const ON {target_table} (CompanyID, ConstructionDate)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_visit ON {target_table} (CompanyID, VisitDate)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_as ON {target_table} (CompanyID, ASDate)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_req ON {target_table} (CompanyID, RequestDate)"))
            
            # 대기/보류 상태 검색용 인덱스 추가
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_wait ON {target_table} (CompanyID, IsWaiting)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_order_hold ON {target_table} (CompanyID, IsHold)"))
            
            conn.commit()
            print(f"[PERF] '{target_table}' 테이블 인덱스 설정 완료")
            
    except Exception as e:
        # 이 에러는 서버 작동(주문처리 등)에는 영향을 주지 않으므로 안심하세요.
        print(f"[WARN] 인덱스 설정 알림: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
