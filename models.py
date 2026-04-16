from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, Float, ForeignKey, Numeric
from sqlalchemy.orm import relationship, synonym
from sqlalchemy.sql import func
from database import Base
from datetime import datetime

# ==========================================
# [마케팅 자동화 엔진 로그]
# ==========================================

class AiLog(Base):
    """생성 시도 1건당 생성되는 메인 레코드"""
    __tablename__ = "ai_marketing_logs"

    log_id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("Orders.OrderID"), index=True)
    company_id = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)
    target_region = Column(String(50))
    
    seo_score = Column(Integer, default=0)
    seo_grade = Column(String(5))
    status = Column(String(20))
    attempt_count = Column(Integer, default=1)
    
    final_prompt = Column(Text)
    content_result = Column(Text) 
    
    admin_note = Column(String(255))
    is_experiment = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계 설정 추가
    order = relationship("Order")
    company = relationship("Company")

class AiPromptVersion(Base):
    """재생성 시도별 프롬프트 및 실패 사유 기록"""
    __tablename__ = "ai_prompt_versions"
    
    version_id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True)
    attempt_no = Column(Integer)
    
    prompt_text = Column(Text)
    fail_reasons = Column(Text) # JSON String
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AiSeoResult(Base):
    """시도별 상세 채점표"""
    __tablename__ = "ai_seo_judge_results"
    
    judge_id = Column("judge_id", Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True)
    attempt_no = Column(Integer)
    
    total_score = Column(Integer)
    grade = Column(String(5))
    
    # 상세 점수 Breakdown
    score_brand = Column(Integer)
    score_keyword = Column(Integer)
    score_length = Column(Integer)
    score_cta = Column(Integer)
    score_structure = Column(Integer)
    score_readability = Column(Integer)
    
    raw_json = Column(Text) # 전체 결과 백업
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# [UPGRADE] CTA 실험 데이터 (성과 측정 컬럼 추가)
class CtaExperiment(Base):
    __tablename__ = "cta_experiments"

    experiment_id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True)
    
    variant_type = Column(String(10)) # A / B
    cta_text = Column(Text)
    
    impressions = Column(Integer, default=0)      # 노출
    click_count = Column(Integer, default=0)      # 클릭
    conversion_count = Column(Integer, default=0) # 전화연결
    
    exposed_at = Column(DateTime(timezone=True), server_default=func.now())

# [NEW] 프롬프트 룰 성능 통계
class AiRuleStat(Base):
    __tablename__ = "ai_prompt_rule_stats"

    rule_code = Column(String(50), primary_key=True)
    applied_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    avg_score_boost = Column(Float, default=0)
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# [NEW] Anti-Rule (금지 규칙)
class AiAntiRule(Base):
    __tablename__ = "ai_anti_rules"
    
    rule_code = Column(String(50), primary_key=True)
    description = Column(String(255))
    forbidden_pattern = Column(Text)
    is_active = Column(Boolean, default=True)
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# [NEW] 사전 예측 로그
class AiPredictionLog(Base):
    __tablename__ = "ai_prediction_logs"
    
    pred_id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, index=True)
    
    predicted_score = Column(Integer)
    fail_probability = Column(Float)
    risk_factors = Column(Text)
    
    actual_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarketingLearningNote(Base):
    __tablename__ = "marketing_learning_notes"

    NoteID = Column("note_id", Integer, primary_key=True, index=True)
    CompanyID = Column("company_id", Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=False)
    Version = Column("version", Integer, default=1)
    JsonBlob = Column("json_blob", Text, nullable=False, default="{}")
    UpdatedAt = Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AiGenerationFeedback(Base):
    __tablename__ = "ai_generation_feedback"

    feedback_id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True, nullable=True)
    track_id = Column(Integer, ForeignKey("MarketingTrackedPost.TrackID"), index=True, nullable=True)
    company_id = Column(Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=True)
    feedback_type = Column(String(40), index=True)
    score_delta = Column(Float, default=0)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiContentFeature(Base):
    __tablename__ = "ai_content_features"

    feature_id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True, nullable=True)
    track_id = Column(Integer, ForeignKey("MarketingTrackedPost.TrackID"), index=True, nullable=True)
    title_length = Column(Integer, default=0)
    body_length = Column(Integer, default=0)
    heading_count = Column(Integer, default=0)
    keyword_density_json = Column(Text, nullable=True)
    photo_marker_count = Column(Integer, default=0)
    item_coverage_score = Column(Float, default=0)
    site_check_coverage_score = Column(Float, default=0)
    worklog_coverage_score = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiPhotoInsight(Base):
    __tablename__ = "ai_photo_insights"

    insight_id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("ai_marketing_logs.log_id"), index=True, nullable=True)
    order_id = Column(Integer, ForeignKey("Orders.OrderID"), index=True, nullable=False)
    photo_id = Column(Integer, ForeignKey("OrderPhotos.PhotoID"), index=True, nullable=True)
    path = Column(String(255), nullable=True)
    shot_type = Column(String(20), default="unknown")
    vision_summary = Column(Text, nullable=True)
    space_hint = Column(String(100), nullable=True)
    product_hint = Column(String(100), nullable=True)
    confidence = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ==========================================
# 1. [SaaS 핵심] 회사 및 사용자 (멀티 테넌시)
# ==========================================

class Company(Base):
    __tablename__ = "Companies"
    CompanyID = Column(Integer, primary_key=True, index=True)
    CompanyName = Column(String(100), nullable=False)
    
    CompanyPhone = Column(String(20), nullable=True) 
    CompanyAddress = Column(String(200), nullable=True)
    
    # ★ [추가된 컬럼들]
    CeoName = Column(String(50), nullable=True)      # 대표자명
    BizNum = Column(String(20), nullable=True)       # 사업자번호
    BizClass = Column(String(50), nullable=True)     # 업태
    BizType = Column(String(50), nullable=True)      # 종목
    SealPath = Column(String(255), nullable=True)    # 직인(도장) 이미지 경로
    BankInfo = Column(String(100), nullable=True)    # 계좌 정보 (예: 신한 110... 예금주)
    Email = Column(String(100), nullable=True)       # 이메일


    OwnerID = Column(Integer, ForeignKey("Users.UserID")) # 최초 생성자(사장)
    
    # [글로벌 설정]
    CountryCode = Column(String(5), default='KR')     # KR, US, JP
    Currency = Column(String(5), default='KRW')       # KRW, USD
    Timezone = Column(String(50), default='Asia/Seoul') 
    UnitSystem = Column(String(10), default='metric') # metric(cm), imperial(inch)
    
    # [구독/결제 정보]
    PlanType = Column(String(20), default='trial')    # trial, pro, premium
    ExpireDate = Column(DateTime)                     # 서비스 만료일
    
    # 관계 설정
    members = relationship("CompanyMember", back_populates="company")
    orders = relationship("Order", back_populates="company")
    suppliers = relationship("Supplier", back_populates="company")

class User(Base):
    __tablename__ = "Users"
    UserID = Column(Integer, primary_key=True, index=True)
    
    # ★ [추가] 로그인 아이디 (필수, 중복불가)
    LoginID = Column(String(50), unique=True, index=True, nullable=False)
    
    # 휴대폰 번호 (이제 아이디 아님, 연락처 용도)
    PhoneNumber = Column(String(20)) 
    
    Password = Column(String(200)) 
    Name = Column(String(50))
    
    # [앱 연동]
    PushToken = Column(String(255), nullable=True) # FCM 토큰 (푸시 알림용)
    
    # 관계 설정 (한 사람이 여러 회사 소속 가능)
    memberships = relationship("CompanyMember", back_populates="user")
    
    # 로직 처리용 가상 속성 (DB 컬럼 아님)
    company_id = None
    role = None

#  CompanyMember 클래스 업데이트
class CompanyMember(Base):
    __tablename__ = "CompanyMembers"
    ID = Column(Integer, primary_key=True, index=True)
    
    # 정직원은 UserID가 있고, 외주직원은 UserID가 NULL입니다.
    UserID = Column(Integer, ForeignKey("Users.UserID"), nullable=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"))
    
    # [1. 기본 정보]
    Name = Column(String(50), nullable=False)   # 이름 (필수)
    Phone = Column(String(20), nullable=False)  # 연락처 (필수)
    
    # [2. 고용 형태] 'internal'(정직원), 'external'(외주)
    Type = Column(String(20), default='internal')
    
    # [3. 외주팀 전용 - 매직 링크 키]
    # 이 키가 있으면 아이디/비번 없이 바로 접속 가능
    AccessKey = Column(String(100), unique=True, nullable=True, index=True)
    
    # [4. 정직원 전용 - 권한 상세 설정]
    RoleName = Column(String(50)) # 화면 표시용 직함 (예: 실장, 팀장)
    
    # -- A. 자금 권한 --
    Perm_ViewRevenue = Column(Boolean, default=False)  # 매출(수입) 전체 보기
    Perm_ViewExpense = Column(Boolean, default=False)  # 지출(매입) 전체 보기
    Perm_ViewMargin  = Column(Boolean, default=False)  # 마진율/원가 보기
    Perm_ViewTotal   = Column(Boolean, default=False)  # 총금액 보기 (리스트/하단 총계)

    # -- B. 인사/관리 권한 --
    Perm_ManageStaff = Column(Boolean, default=False)  # 직원 등록/삭제
    Perm_ViewStats   = Column(Boolean, default=False)  # 통계 메뉴 접근
    
    # -- C. 작업 권한 --
    Perm_EditSchedule = Column(Boolean, default=True)  # 일정 수정/삭제 권한

    # ★ [추가] 신규 권한 3종
    Perm_DeleteOrder = Column(Boolean, default=False)       # 주문 삭제 권한
    Perm_ManageSiteCheck = Column(Boolean, default=False)   # 현장 체크 항목 관리
    Perm_ManageCompanyInfo = Column(Boolean, default=False) # 회사 정보 수정
    
    # 관계 설정
    user = relationship("User", back_populates="memberships")
    company = relationship("Company", back_populates="members")
    
    # 담당한 주문들 (시공 담당자)
    # assigned_orders = relationship("Order", back_populates="installer") 
    # (주의: Order 테이블에 installer 관계가 설정되어 있어야 함)


# ==========================================
# 2. [주문 및 시공] (기존 로직 + 확장)
# ==========================================

class Order(Base):
    __tablename__ = "Orders"
    OrderID = Column(Integer, primary_key=True, index=True)

    # 데이터 격리 (어느 회사 주문인가?)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=True) 
    
    CustomerName = Column(String(100))
    PhoneNumber = Column(String(20))
    Address = Column(String(255))
    ProgressStatus = Column(String(20), index=True)
    PaymentStatus = Column(String(20), index=True)
    PaymentMethod = Column(String(50))
    
    BankName = Column(String(50), nullable=True)
    DepositorName = Column(String(50), nullable=True)
    
    TotalAmount = Column(Numeric(18, 0), default=0)
    DiscountAmount = Column(Numeric(18, 0), default=0)
    DepositAmount = Column(Numeric(18, 0), default=0)
    FinalAmount = Column(Numeric(18, 0), default=0)
    Balance = Column(Numeric(18, 0), default=0) # 잔금 필드
    IsVatIncluded = Column(String(1), default='N')
    
    ConstructionDate = Column(DateTime, nullable=True, index=True)
    VisitDate = Column(DateTime, nullable=True, index=True)
    RequestDate = Column(DateTime, nullable=True, index=True)
    ASDate = Column(DateTime, nullable=True, index=True)
    Memo = Column(Text, nullable=True)
    Order_code = Column(String(50), nullable=True)
    
    # 상태 플래그
    IsHold = Column(String(1), default='N', index=True)
    IsWaiting = Column(String(1), default='N', index=True)
    IsAS = Column(String(1), default='N')
    IsOrdered = Column(String(1), default='N')
    IsReceived = Column(String(1), default='N')
    RegDate = Column(DateTime, default=datetime.now)
    
    # 스마트 시공 & 배송 확장 기능
    ChecklistMemo = Column(Text, nullable=True)        # 공구 체크리스트
    
    DeliveryToken = Column(String(100), unique=True, nullable=True) # 매직링크 토큰
    IsShipped = Column(String(1), default='N')         # 배송출발 여부
    
    # 담당 기사 (직원 테이블과 연결)
    InstallerID = Column(Integer, ForeignKey("CompanyMembers.ID"), nullable=True)
    
    # 관계 설정
    company = relationship("Company", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    # [Phase 2] 현장 체크 & 서명
    InstallSurface = Column(String(50), nullable=True) # 설치면 (콘크리트, 석고 등)
    CeilingHeight = Column(String(20), nullable=True)  # 천고 (cm)
    ClientSignature = Column(Text, nullable=True)      # 전자서명 (Base64 데이터)

# ★ [수정] 현장 사진 테이블 (품목 연동 FK 추가)

class OrderExtraInfo(Base):
    __tablename__ = "OrderExtraInfo"

    ExtraID = Column(Integer, primary_key=True, index=True)
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"), index=True, nullable=False, unique=True)
    InflowRoute = Column(String(50), nullable=True)
    InflowDetail = Column(String(255), nullable=True)
    ASReason = Column(String(50), nullable=True)
    ASResponsibility = Column(String(50), nullable=True)
    ASChargeType = Column(String(30), nullable=True)
    ASCost = Column(Numeric(18, 0), default=0)
    ASNote = Column(Text, nullable=True)
    UpdatedAt = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class OrderManager(Base):
    __tablename__ = "OrderManagers"
    ID = Column(Integer, primary_key=True, index=True)
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"), index=True, nullable=False)
    MemberID = Column(Integer, ForeignKey("CompanyMembers.ID"), index=True, nullable=False)
    IsPrimary = Column(Boolean, default=False, nullable=False)
    RegDate = Column(DateTime, default=datetime.now)

class OrderPhoto(Base):
    __tablename__ = "OrderPhotos"
    PhotoID = Column(Integer, primary_key=True, index=True)
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"), index=True)
    
    # [추가] 특정 품목과 사진을 직접 연결하기 위한 외래키 (전체 현장 사진일 수도 있으므로 nullable=True)
    ItemID = Column(Integer, ForeignKey("OrderItems.ItemID"), index=True, nullable=True) 
    
    FilePath = Column(String(255)) # 저장 경로
    FileName = Column(String(255)) # 파일명
    FileType = Column(String(50))  # 시공전/시공후/AS
    Tags = Column(String(255))     # 검색 태그 (예: 콤비, 우드, 거실)
    RegDate = Column(DateTime, default=datetime.now)
    
    # [추가] 품목과의 양방향 관계 설정
    item = relationship("OrderItem", back_populates="photos")

# ★ [수정] 주문 품목 테이블 (다중 도메인용 JSON 컬럼 추가)
class OrderItem(Base):
    __tablename__ = "OrderItems"
    
    ItemID = Column(Integer, primary_key=True, index=True)
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"))
    GroupID = Column(String(50), nullable=True)
    
    Location = Column(String(50))
    Category = Column(String(50))
    Category1 = Column(String(50), nullable=True)
    
    # [공통 슬롯] 확장형 현장업무용 범용 상세 필드
    cate1 = Column("cate1", String(100), nullable=True)  # 제품명 / 작업명
    cate2 = Column("cate2", String(100), nullable=True)  # 칼라 / 재질 / 톤
    cate3 = Column("cate3", String(100), nullable=True)  # 옵션 / 방식
    cate4 = Column("cate4", Text, nullable=True)         # 비고 / 특이사항

    # [호환 레이어] 기존 커튼/블라인드 코드가 바로 깨지지 않도록 유지
    ProductName = synonym("cate1")
    OptionInfo = synonym("cate3")
    ItemMemo = synonym("cate4")
    
    # [레거시 유지] 기존 커튼/블라인드 데이터 보존용
    Width = Column(Numeric(10, 2), default=0)
    Height = Column(Numeric(10, 2), default=0)
    Quantity = Column(Numeric(10, 2), default=0)
    
    UnitPrice = Column(Numeric(18, 0), default=0)
    LineTotal = Column(Numeric(18, 0), default=0)
    
    Supplier = Column(String(50), nullable=True) 
    
    BlindSize = Column(String(200), nullable=True)
    BlindCount = Column(Integer, default=0)
    BlindQty = Column(String(200), nullable=True)
    
    SortOrder = Column(Integer, default=0)
    ItemStep = Column(Integer, default=0)
    
    # ★ [핵심 추가] 타 업종(조명, 인테리어 등)의 가변 속성을 무한히 담을 수 있는 범용 JSON 컬럼
    Attributes = Column(JSON, nullable=True) 
    
    order = relationship("Order", back_populates="items")
    # [추가] 이 품목에 등록된 사진들 (1:N 관계)
    photos = relationship("OrderPhoto", back_populates="item", cascade="all, delete-orphan")


class OrderHistory(Base):
    __tablename__ = "OrderHistory"
    HistoryID = Column(Integer, primary_key=True, index=True)
    OrderID = Column(Integer, index=True)
    LogType = Column(String(40))
    Contents = Column(Text)
    RegDate = Column(DateTime, default=datetime.now)
    MemberName = Column(String(50), nullable=True)


# ==========================================
# 5. [마케팅 - 블로그 URL 추적/관리] (Phase 0: 수동 순위 기록)
# ==========================================

class MarketingTrackedPost(Base):
    __tablename__ = "MarketingTrackedPost"
    TrackID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), nullable=False, index=True)
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"), nullable=True, index=True)

    BlogURL = Column(String(800), nullable=False)
    MainKeyword = Column(String(200), nullable=True)
    RegionKeyword = Column(String(200), nullable=True)
    IsActive = Column(String(1), default='Y')

    CreatedAt = Column(DateTime, default=datetime.now)


class MarketingRankHistory(Base):
    __tablename__ = "MarketingRankHistory"
    RankID = Column(Integer, primary_key=True, index=True)
    TrackID = Column(Integer, ForeignKey("MarketingTrackedPost.TrackID"), nullable=False, index=True)
    CheckedAt = Column(DateTime, default=datetime.now, index=True)
    Keyword = Column(String(200), nullable=True)
    Rank = Column(Integer, nullable=True)  # 1~100, 없으면 NULL
    Source = Column(String(30), default='manual')  # manual/auto
    Note = Column(String(255), nullable=True)


# ==========================================
# 4. [아파트 DB]
# ==========================================
class AptComplex(Base):
    __tablename__ = "AptComplex"
    ComplexID = Column(Integer, primary_key=True, index=True) 
    ComplexName = Column(String(100), nullable=False)
    SortOrder = Column(Integer, default=0)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), nullable=True, index=True)

class AptPlan(Base):
    __tablename__ = "AptPlan"
    PlanID = Column(Integer, primary_key=True, index=True)
    ComplexID = Column(Integer, ForeignKey("AptComplex.ComplexID"))
    PlanName = Column(String(100))
    IsRepresentative = Column(String(1), default='N')
    FloorPlanImg = Column(String(510), nullable=True)
    Memo = Column(String(1000), nullable=True)
    SortOrder = Column(Integer, default=0)

class WindowSize(Base):
    __tablename__ = "WindowSize"
    WindowID = Column(Integer, primary_key=True, index=True)
    PlanID = Column(Integer, ForeignKey("AptPlan.PlanID"))
    LocationName = Column(String(100))
    IsExtension = Column(String(1), default='N')
    
    Width = Column(Numeric(10, 2))
    Height = Column(Numeric(10, 2))
    
    SplitCount = Column(Integer, default=1)
    SplitSizes = Column(String(200), nullable=True)
    BoxWidth = Column(Numeric(10, 2), default=0)
    HasObstacle = Column(String(1), default='N')
    
    Memo = Column(Text, nullable=True)
    WinType = Column(String(40), nullable=True)
    SortOrder = Column(Integer, default=0)

class SiteCheckItem(Base):
    __tablename__ = "site_check_items"

    ItemID = Column(Integer, primary_key=True, index=True)
    
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID")) 
    
    ItemName = Column(String(100))  # 예: 콘크리트
    SubText = Column(String(100))   # 예: 함마드릴/비트
    SortOrder = Column(Integer, default=0)

# ==========================================
# [커튼 높이 보정값] (클립보드 발주용)
# ==========================================
class CurtainHeightDeduction(Base):
    __tablename__ = "curtain_height_deductions"

    RuleID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)

    Category = Column(String(50), default="커튼")   # 예: 커튼
    SubType = Column(String(50), nullable=False)    # 예: 속지, 겉지
    DeductValue = Column(Numeric(10, 2), default=0) # 예: 4, 3.5

    UpdatedAt = Column(DateTime, default=datetime.now)

# ==========================================
# 현장직 퀵 지출 관리 (Field Expenses)
# ==========================================
class FieldExpense(Base):
    __tablename__ = "field_expenses"
    
    ExpenseID = Column(Integer, primary_key=True, index=True)
    
    # 1. 소속 및 관계
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)
    MemberID = Column(Integer, ForeignKey("CompanyMembers.ID"), index=True)  # 누가 썼는가?
    OrderID = Column(Integer, ForeignKey("Orders.OrderID"), index=True, nullable=True) # 어느 현장인가? (선택)
    
    # 2. 지출 내역
    Category = Column(String(50))              # 식대, 주유/톨비, 주차, 자재, 기타
    Amount = Column(Numeric(18, 0), default=0) # 금액
    Memo = Column(String(255), nullable=True)  # 음성 인식으로 들어올 메모
    
    # 3. 증빙 자료
    ReceiptPath = Column(String(255), nullable=True) # 영수증 사진 저장 경로
    
    # 4. 시간 기록
    ExpensedAt = Column(DateTime(timezone=True), server_default=func.now())

    # Reason: 현장 지출 내역의 물리 삭제를 막고 복구 가능성을 열어두기 위한 논리 삭제 플래그 추가
    IsActive = Column(Boolean, default=True)
    
    # ORM 관계 설정 (조인용)
    company = relationship("Company")
    member = relationship("CompanyMember")
    order = relationship("Order")


class ExpenseCategory(Base):
    __tablename__ = "erp_expense_categories"

    CategoryID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=False)
    CategoryName = Column(String(50), nullable=False)
    Icon = Column(String(20), nullable=True)
    SortOrder = Column(Integer, default=1)
    IsActive = Column(Boolean, default=True)
    CreatedAt = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company")

# ==========================================
# 거래처 마스터 및 매입/지급 원장 (Ledger)
# ==========================================
class Supplier(Base):
    """거래처(업체) 목록"""
    __tablename__ = "erp_suppliers"
    
    SupplierID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)
    
    SupplierName = Column(String(100))      # 업체명 (예: 동대문A원단, B블라인드)
    ContactName = Column(String(50))        # 담당자명
    Phone = Column(String(50))              # 대표 연락처
    Mobile = Column(String(50), nullable=True)       # 담당자 휴대폰 번호
    AccountInfo = Column(String(100), nullable=True) # 은행 및 계좌번호
    MainItems = Column(String(255))         # 주요 취급품목
    IsActive = Column(Boolean, default=True) # 거래 유지 여부

    company = relationship("Company", back_populates="suppliers")
    products = relationship("SupplierProduct", back_populates="supplier")

class SupplierTransaction(Base):
    """거래처별 매입(+) 및 지급(-) 내역"""
    __tablename__ = "erp_supplier_transactions"
    
    TxID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)
    SupplierID = Column(Integer, ForeignKey("erp_suppliers.SupplierID"), index=True)
    MemberID = Column(Integer, ForeignKey("CompanyMembers.ID")) 
    
    TxDate = Column(DateTime(timezone=True), default=func.now()) 
    TxType = Column(String(20))               # '청구' 또는 '지급'
    Amount = Column(Numeric(18,0), default=0) # 금액
    Memo = Column(String(255))                # 적요
    ReceiptPath = Column(String(255), nullable=True) 

    # Reason: 매입/지급 원장의 안전한 관리를 위한 논리 삭제 플래그 추가
    IsActive = Column(Boolean, default=True)
    
    supplier = relationship("Supplier")


class SupplierTransactionLink(Base):
    """매입 거래와 거래처의 다중 연결"""
    __tablename__ = "erp_supplier_transaction_links"

    LinkID = Column(Integer, primary_key=True, index=True)
    TxID = Column(Integer, ForeignKey("erp_supplier_transactions.TxID"), index=True, nullable=False)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=False)
    SupplierID = Column(Integer, ForeignKey("erp_suppliers.SupplierID"), index=True, nullable=False)
    SortOrder = Column(Integer, default=1)
    IsPrimary = Column(Boolean, default=False)
    IsActive = Column(Boolean, default=True)
    CreatedAt = Column(DateTime(timezone=True), server_default=func.now())

    supplier = relationship("Supplier")

# ==========================================
# 거래처 취급 제품 마스터 (원가 및 마진 연동용)
# ==========================================
class SupplierProduct(Base):
    __tablename__ = "erp_supplier_products"
    
    ProductID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True)
    SupplierID = Column(Integer, ForeignKey("erp_suppliers.SupplierID"), index=True)
    
    Category = Column(String(50), nullable=True, index=True)
    SubCategory = Column(String(50), nullable=True, index=True)
    ProductName = Column(String(100), index=True)
    
    CostPrice = Column(Numeric(18, 0), default=0)
    SellingPrice = Column(Numeric(18, 0), default=0)
    IsActive = Column(Boolean, default=True)
    
    supplier = relationship("Supplier", back_populates="products")


class SupplierProductAttr(Base):
    __tablename__ = "erp_supplier_product_attrs"

    AttrID = Column(Integer, primary_key=True, index=True)
    CompanyID = Column(Integer, ForeignKey("Companies.CompanyID"), index=True, nullable=False)
    ProductID = Column(Integer, ForeignKey("erp_supplier_products.ProductID"), index=True, nullable=False)
    AttrType = Column(String(20), index=True, nullable=False)
    AttrValue = Column(String(255), nullable=False)
    ExtraPrice = Column(Numeric(18, 0), default=0)
    UseCount = Column(Integer, default=1)
    IsActive = Column(Boolean, default=True)
    LastUsedAt = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product = relationship("SupplierProduct")
