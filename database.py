from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://curtain_user:ckddkfma2026@127.0.0.1/curtain_db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_recycle=3600, 
    pool_pre_ping=True,
    pool_size=20,       # 기본 유지 연결 수 (기본값 5 -> 20)
    max_overflow=40     # 최대 허용 연결 수 (기본값 10 -> 40)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()