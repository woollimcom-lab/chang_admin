from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from database import get_db
from PIL import Image, ImageEnhance, ImageOps, ImageFilter, ImageDraw, ImageFont
import os
import re
import json
import io
import zipfile
import urllib.parse
import urllib.request 
import concurrent.futures 
from functools import lru_cache 
from datetime import datetime
from openai import OpenAI
import math
import random
import models
import logging
from auth import get_current_user

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


# =========================================================
# [Phase 0] 블로그 URL 추적 관리 (수동 순위 입력)
# =========================================================

class TrackAddReq(BaseModel):
    order_id: int | None = None
    blog_url: str
    main_keyword: str | None = None
    region_keyword: str | None = None

class RankAddReq(BaseModel):
    track_id: int
    keyword: str | None = None
    rank: int | None = None
    note: str | None = None


@router.post("/tracking/add")
def add_tracking(req: TrackAddReq, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    url = (req.blog_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="blog_url required")

    row = models.MarketingTrackedPost(
        CompanyID=current_user.company_id,
        OrderID=req.order_id,
        BlogURL=url,
        MainKeyword=(req.main_keyword or "").strip() or None,
        RegionKeyword=(req.region_keyword or "").strip() or None,
        IsActive='Y'
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "track_id": row.TrackID}


@router.get("/tracking/list")
def list_tracking(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    rows = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.CompanyID == current_user.company_id,
        models.MarketingTrackedPost.IsActive == 'Y'
    ).order_by(models.MarketingTrackedPost.TrackID.desc()).all()

    data = []
    for r in rows:
        last = db.query(models.MarketingRankHistory).filter(models.MarketingRankHistory.TrackID == r.TrackID).order_by(models.MarketingRankHistory.CheckedAt.desc()).first()
        data.append({
            "track_id": r.TrackID,
            "order_id": r.OrderID,
            "blog_url": r.BlogURL,
            "main_keyword": r.MainKeyword,
            "region_keyword": r.RegionKeyword,
            "created_at": r.CreatedAt.isoformat() if r.CreatedAt else None,
            "last_rank": last.Rank if last else None,
            "last_checked_at": last.CheckedAt.isoformat() if last and last.CheckedAt else None,
            "last_keyword": last.Keyword if last else None,
        })
    return {"ok": True, "items": data}


@router.post("/tracking/rank/add")
def add_rank(req: RankAddReq, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    track = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.TrackID == req.track_id,
        models.MarketingTrackedPost.CompanyID == current_user.company_id,
        models.MarketingTrackedPost.IsActive == 'Y'
    ).first()
    if not track:
        raise HTTPException(status_code=404, detail="track not found")

    row = models.MarketingRankHistory(
        TrackID=track.TrackID,
        Keyword=(req.keyword or track.MainKeyword or "").strip() or None,
        Rank=req.rank,
        Source='manual',
        Note=(req.note or "").strip() or None
    )
    db.add(row)
    db.commit()
    return {"ok": True}


@router.post("/tracking/deactivate")
def deactivate_tracking(track_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    track = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.TrackID == track_id,
        models.MarketingTrackedPost.CompanyID == current_user.company_id
    ).first()
    if not track:
        raise HTTPException(status_code=404, detail="track not found")
    track.IsActive = 'N'
    db.commit()
    return {"ok": True}

# --- 데이터 모델 ---
class CustomGenerateReq(BaseModel):
    order_id: int
    custom_prompt: str

class AdvancedGenerateReq(BaseModel):
    order_id: int
    company_id: int = 0
    target_region: str = None 
    apt_name: str = None      
    build_type: str = None    
    pyung: str = None         
    items_content: str = None 
    episode: str = None
    extra: str = None         
    persona: str = None 
    tone: str = None    
    brand_mode: str = "강조"
    main_keyword: str = None
    photo_style: str = "설명형"
    cta_strength: str = "일반"
    split_count: int = 1
    seo_target: int = 80
    goal: str = "seo"
    region_strategy: str = "auto"
    cta_experiment: bool = False
    admin_note: str = None
    map_mode: str = "site" 

# =========================================================
# [전략 센터] 프롬프트 보강 규칙
# =========================================================
PROMPT_FEEDBACK_RULES = {
    "CTA_PHONE_MISSING": """
- **[필수 수정]**: 본문 중간이나 하단에 전화번호 숫자만으로 된 줄 <p>{phone_digits}</p> 를 반드시 단독으로 추가하세요.
""",
    "KEYWORD_DISTRIBUTION_WEAK": """
- **[필수 수정]**: 메인 키워드 '{main_keyword}'를 모든 `<h3>` 소제목 바로 아래 첫 번째 문단마다 반드시 1회씩 포함시키세요.
""",
    "H3_STRUCTURE_WEAK": """
- **[구조 수정]**: 소제목 작성 시 <strong>이나 <b> 태그 대신 오직 `<h3>` 태그만 사용하세요.
""",
    "BRAND_MENTION_LOW": """
- **[빈도 수정]**: 상호명 '{company_name}'을 첫 문단, 본문 중간, 아웃트로 CTA 문단에 각각 1회 이상 명시적으로 포함하세요.
""",
    "PHOTO_INSTRUCTION_MISSING": """
- **[배치 수정]**: `[사진: ...]` 지시어를 최소 {target_photo_cnt}개 이상 배치하세요.
  **[중요]**: 사진 위치를 쉽게 찾을 수 있도록 앞뒤로 줄바꿈(<br>)을 넣고 <b> 태그로 감싸세요.
""",
    "CONTENT_SHORT": """
- **[분량 수정]**: 글의 내용이 너무 짧습니다. 묘사를 대폭 보강하여 전체 분량을 1200자 이상으로 길게 작성하세요.
"""
}

JUDGE_READABLE_MESSAGES = {
    "KEYWORD_DISTRIBUTION_WEAK": "메인 키워드 분산 부족",
    "BRAND_MENTION_LOW": "브랜드명 노출 부족",
    "CTA_PHONE_MISSING": "전화번호 미인식",
    "H3_STRUCTURE_WEAK": "H3 태그 미사용",
    "CONTENT_SHORT": "글 분량 부족",
    "PHOTO_INSTRUCTION_MISSING": "사진 배치 지시 부족"
}

DEFAULT_ANTI_RULES = [
    "메인 키워드를 문장의 시작마다 기계적으로 반복하지 마세요.",
    "의미 없는 미사여구로 분량을 억지로 늘리지 마세요.",
    "실제 시공과 관련 없는 일반적인 인테리어 정보 나열을 피하세요."
]

# =========================================================
# [엔진 0] SEO 점수 예측기 (Pre-flight)
# =========================================================
# [marketing.py] predict_seo_score_logic 함수 및 관련 로직 교체

# 자동 보정 규칙 정의
AUTO_ADJUST_RULES = {
    "메인 키워드 미설정": {"action": "set_keyword", "priority": 1},
    "사진 부족": {"action": "relax_photo", "priority": 2},
    "CTA 강도 약함": {"action": "strengthen_cta", "priority": 3}
}

def predict_seo_score_logic(req: AdvancedGenerateReq, photo_count: int):
    score = 95 
    risks = []
    fail_prob = 0.0
    
    # 1. 리스크 분석
    if not req.main_keyword: 
        score -= 25; fail_prob += 0.4; risks.append("메인 키워드 미설정")
    
    if photo_count < 3:
        score -= 15; fail_prob += 0.2; risks.append(f"사진 부족 ({photo_count}장)")
        
    if req.cta_strength == "부드럽게":
        score -= 5; risks.append("CTA 강도 약함")
        
    if req.brand_mode != "강조": score -= 5
    
    predicted_score = max(40, score)
    
    # 2. 자동 보정 제안 생성
    adjustments = []
    for risk in risks:
        # 리스크 메시지의 핵심 키워드로 매핑 (간단한 포함 여부 체크)
        matched_rule = None
        for key, rule in AUTO_ADJUST_RULES.items():
            if key in risk: matched_rule = rule; break
            
        if matched_rule:
            adj = {"reason": risk}
            if matched_rule["action"] == "set_keyword":
                adj["field"] = "main_keyword"
                adj["before"] = "(없음)"
                adj["after"] = f"{req.target_region} 커튼"
            elif matched_rule["action"] == "relax_photo":
                adj["field"] = "photo_style"
                adj["before"] = req.photo_style
                adj["after"] = "감성형 (적은 사진 최적화)"
            elif matched_rule["action"] == "strengthen_cta":
                adj["field"] = "cta_strength"
                adj["before"] = req.cta_strength
                adj["after"] = "강하게"
            
            adjustments.append(adj)

    return {
        "predicted_score": predicted_score,
        "grade_estimate": "A" if predicted_score >= 85 else "B" if predicted_score >= 75 else "C",
        "fail_probability": min(0.95, fail_prob),
        "risk_factors": risks,
        "auto_adjustments": adjustments, # [NEW] 보정 제안 리스트
        "can_generate": fail_prob < 0.85 # [NEW] 생성 가능 여부 (차단 기준)
    }

# =========================================================
# [엔진 1] 정밀 SEO 채점 시스템 (정규화 강화)
# =========================================================
def normalize_text(text: str):
    """[운영 강화] 공백 제거, 소문자, 특수문자 제거"""
    if not text: return ""
    return re.sub(r"\s+|[^가-힣a-zA-Z0-9]", "", text).lower()

def strip_html(text: str):
    return re.sub(r'<[^>]+>', '', text)

def extract_digits(text: str):
    if not text: return ""
    return re.sub(r"\D", "", text)

def check_distribution(text: str, keyword: str) -> bool:
    """[운영 강화] 정규화된 키워드로 매칭"""
    if not keyword or not text: return False
    
    norm_keyword = normalize_text(keyword)
    sections = re.split(r'<\s*h3[^>]*>', text, flags=re.IGNORECASE)
    hit_count = 0
    valid_sections = 0
    
    for section in sections:
        clean_sec = strip_html(section).strip()
        if len(clean_sec) < 30: continue
        valid_sections += 1
        
        # [운영 강화] 섹션 앞부분 400자 내에서 정규화된 키워드 검색
        if norm_keyword in normalize_text(clean_sec[:400]): 
            hit_count += 1
            
    return hit_count >= min(2, valid_sections)

def decide_status(score, target):
    base_pass = max(80, target)
    if score >= base_pass: return "PASS"
    if score >= base_pass - 10: return "CHECK"
    return "RETRY"

def analyze_seo_detail(content: str, keywords: dict, brand_name: str, phone: str, photo_count_req: int, target_score: int):
    clean_text = strip_html(content)
    norm_content = normalize_text(clean_text)
    total_len = len(clean_text)
    
    scores = {"brand_exposure": 0, "keyword_balance": 0, "content_length": 0, "cta_quality": 0, "structure": 0, "readability": 0}
    fail_reasons = []
    
    # 1. 브랜드
    norm_brand = normalize_text(brand_name)
    cnt_brand = norm_content.count(norm_brand) if norm_brand else 0
    if cnt_brand >= 4: scores["brand_exposure"] = 10
    elif cnt_brand >= 2: scores["brand_exposure"] = 7
    else: fail_reasons.append("BRAND_MENTION_LOW")

    # 2. 키워드
    main_kw = keywords.get('main', '')
    if main_kw:
        cnt_main = norm_content.count(normalize_text(main_kw))
        is_distributed = check_distribution(content, main_kw)
        if cnt_main >= 3 and is_distributed: scores["keyword_balance"] = 25
        elif cnt_main >= 2: scores["keyword_balance"] = 15
        else: fail_reasons.append("KEYWORD_DISTRIBUTION_WEAK")

    # 3. 분량
    if total_len >= 1200: scores["content_length"] = 15
    elif total_len >= 800: scores["content_length"] = 10
    else: fail_reasons.append("CONTENT_SHORT")

    # 4. CTA
    phone_digits = extract_digits(phone)
    content_digits = extract_digits(content)
    if (len(phone_digits) >= 8 and phone_digits[-8:] in content_digits) or (phone_digits and phone_digits in content_digits):
        scores["cta_quality"] = 15
    else: fail_reasons.append("CTA_PHONE_MISSING")

    # 5. 구조
    if re.search(r"<\s*h3[^>]*>", content, re.IGNORECASE): scores["structure"] = 15
    else: fail_reasons.append("H3_STRUCTURE_WEAK")

    # 6. 가독성
    photo_marker_cnt = len(re.findall(r"\[(사진|이미지)", content))
    target_cnt = photo_count_req if photo_count_req <= 2 else math.ceil(photo_count_req * 0.7)
    if photo_marker_cnt >= target_cnt: scores["readability"] = 20
    elif photo_marker_cnt >= 1: scores["readability"] = 10
    else: fail_reasons.append("PHOTO_INSTRUCTION_MISSING")

    total_score = min(100, sum(scores.values()))
    status = decide_status(total_score, target_score)
    human_readable = [JUDGE_READABLE_MESSAGES.get(r, r) for r in fail_reasons]

    return {
        "total_score": total_score, 
        "grade": "S" if total_score >= 90 else "A",
        "status": decide_status(total_score, target_score),
        "details": scores, 
        "fail_reasons": fail_reasons, 
        "human_readable": human_readable,
        "target_photo_cnt": target_cnt
    }

# =========================================================
# [엔진 2] 프롬프트 조립기 (안전장치)
# =========================================================
def construct_prompt_for_attempt(base_prompt, fail_reasons, context_data, target_photo_cnt, db: Session = None):
    current_prompt = base_prompt

    # 1. Anti-Rule (DB 연동)
    anti_rules = DEFAULT_ANTI_RULES
    if db:
        try:
            db_rules = db.query(models.AiAntiRule).filter(models.AiAntiRule.is_active == True).all()
            if db_rules: anti_rules = [r.forbidden_pattern for r in db_rules]
        except: pass
    
    if anti_rules:
        anti_header = "\n\n[🚫 절대 금지 사항 (Anti-Rules)]\n"
        anti_body = "\n".join([f"- {rule}" for rule in anti_rules])
        current_prompt += f"{anti_header}{anti_body}"

    # 2. Feedback Rule (Diff Patch)
    if fail_reasons:
        feedback_header = "\n\n[⛔ SEO 품질 미달! 아래 규칙을 반영하여 전체 글을 처음부터 다시 작성하세요]\n"
        booster_body = ""
        format_data = {
            "main_keyword": context_data['keyword_plan']['main'],
            "company_name": context_data['company_name'],
            "phone_digits": " / ".join([extract_digits(p) for p in re.split(r'[/,]', context_data['phone']) if extract_digits(p)]),
            "target_photo_cnt": target_photo_cnt
        }
        
        applied = 0
        for reason in fail_reasons:
            if applied >= 3: break
            rule_template = PROMPT_FEEDBACK_RULES.get(reason)
            if rule_template:
                try: booster_body += rule_template.format(**format_data); applied += 1
                except: pass
        
        current_prompt += f"{feedback_header}{booster_body}"

    return current_prompt

# =========================================================
# [엔진 3] 전략 및 헬퍼 함수
# =========================================================
def generate_title_candidates(region, apt, company):
    return [f"[{region}] {apt} 시공 후기 | {company}", f"{region} {apt} 30평대 커튼 리뷰", f"{region} 맘들이 추천하는 {apt} 블라인드"]

def generate_hashtags(region, company):
    return list(dict.fromkeys([f"#{region}커튼", f"#{region}블라인드", f"#{company.replace(' ', '')}", "#아파트커튼", "#블라인드시공"]))

def generate_cta_variants(phone: str):
    return {"variants": [
        {"type": "A", "style": "Soft", "text": f"궁금한 점은 부담 없이 물어보세요 😊<br>📞 {phone}", "copy": "부담 없이 상담"},
        {"type": "B", "style": "Hard", "text": f"고민은 시공만 늦출 뿐! 지금 바로 전화주세요.<br>📞 {phone}", "copy": "지금 바로 전화"}
    ]}

def build_keyword_plan(region, apt, build_type, main_kw=None, strategy="auto"):
    if strategy == "off": return {"main": "커튼 블라인드", "sub": []}
    base = [f"{region} 커튼", f"{region} 블라인드", f"{apt} 커튼"]
    if main_kw: base.insert(0, main_kw)
    return {"main": base[0], "sub": base[1:]}

def get_paragraph_strategy(photo_count: int, style: str) -> str:
    return "시공 전후의 변화와 감성적인 분위기를 중심으로 서술합니다."

# [수정] 프롬프트 생성 함수 (시공품목 설명 강화 적용)
def build_user_prompt_text(company_name, req, company_address, keyword_plan, brand_mentions, paragraph_strategy, phone, active_cta_text, photo_count, map_url=""):
    raw_phones = re.split(r'[/,]', phone)
    digit_phones = [extract_digits(p) for p in raw_phones if extract_digits(p)]
    phone_instruction = " / ".join(digit_phones)
    target_photo_cnt = photo_count if photo_count <= 2 else math.ceil(photo_count * 0.7)

    admin_hint = ""
    if req.admin_note: admin_hint += f"\n# [💡 특별 요청 사항]\n- \"{req.admin_note}\"\n"
    if req.extra: admin_hint += f"\n# [⚠️ 필수 전달 사항]\n- \"{req.extra}\"\n"

    # [✅ 핵심 수정] 시공 품목 설명 가이드 대폭 강화
    items_info = ""
    if req.items_content:
        items_info = f"""
# [🛋️ 시공 품목 및 공간별 스토리텔링 가이드]

### 1. 실제 시공 내역 (Raw Data)
{req.items_content}

### 2. 작성 가이드 (단순 나열 금지 🚫)
위 시공 내역을 바탕으로, **각 공간별로 시공팀장이 현장에서 설명하듯** 자연스럽게 풀어내세요.
다음 순서로 내용을 전개해야 합니다:
1. **공간 언급**: (예: "가장 공들인 거실입니다.", "프라이버시가 중요한 안방은요...")
2. **선택 이유**: 고객의 고민이나 공간의 특성 (예: "채광은 살리면서 시선 차단이 필요했어요.")
3. **제품 특징**: 품명 반복보다는 **소재, 질감, 기능** 위주 설명 (예: "도톰한 원단이라 방한 효과가 뛰어나요.")
4. **설치 후 변화**: (예: "설치하고 나니 호텔 같은 분위기가 났습니다.")

### 3. 디테일 포인트 (내용에 해당 품목이 있다면 반드시 반영)
- **차르르/쉬폰**: 살랑거리는 부드러운 원단감, 햇살이 들어올 때의 감성적인 무드 강조.
- **암막 커튼**: 확실한 빛 차단율, 형상기억 가공의 정갈한 주름 핏, 방한/단열 효과.
- **블라인드(우드/알루미늄)**: 슬랏 조절의 편리함, 깔끔하고 모던한 공간 연출, 개방감.
- **특이 시공**: 꺾쇠 시공, 커튼박스 등 실무적인 디테일이 있다면 전문가답게 이유를 설명.
"""

    return f"""
# 역할:
당신은 '{company_name}'의 '{req.persona}'입니다. '{req.tone}' 말투를 사용하세요.

# 현장 정보:
- 지역: {req.target_region}
- 현장: {req.apt_name} ({req.build_type} {req.pyung})

# SEO 키워드 전략:
- 메인: {keyword_plan['main']}
- 서브: {", ".join(keyword_plan['sub'])}

{items_info}
{admin_hint}

# [필수 체크리스트]
1. **블로그 글 제목을 3가지 제안**하여 가장 상단에 작성하세요. (형식: "제목1: ...")
2. 상호명('{company_name}')을 총 {brand_mentions}회 이상 자연스럽게 노출하세요.
3. 메인 키워드('{keyword_plan['main']}')는 모든 소제목(`<h3>`) 바로 아래 첫 번째 문단에 반드시 포함하세요.
4. 전화번호는 숫자만 있는 줄을 본문 끝에 추가: <p>{phone_instruction}</p>
5. **[중요]** 사진 위치는 찾기 쉽게 반드시 **앞뒤로 줄바꿈(<br>)**을 하고 **<b>[사진: ...]</b>** 형태로 굵게 표시하세요. (최소 {target_photo_cnt}곳)
6. 소제목은 `<h3>` 태그만 사용하세요.
7. 글자 수 1200자 이상 작성하세요.

# 콘텐츠 전략:
1. **사진 전략**: {paragraph_strategy}
2. **스토리텔링**: "{req.episode}" 내용을 활용하여, 시공 전 고민과 해결 과정을 드라마틱하게 서술하세요.

# 아웃트로:
<hr style='border: 0; height: 1px; background: #ddd; margin: 40px 0;'>
<p>{active_cta_text}</p>
<h3>오시는 길</h3>
<p>{company_name}</p>
<p>{company_address}</p>
<p><a href="{map_url}" target="_blank">📍 네이버 지도 바로가기</a></p>
""".strip()

def prepare_marketing_context(req: AdvancedGenerateReq, db: Session):
    order = db.query(models.Order).filter(models.Order.OrderID == req.order_id).first()
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    company = db.query(models.Company).filter(models.Company.CompanyID == order.CompanyID).first()
    db_photos = db.query(models.OrderPhoto).filter(models.OrderPhoto.OrderID == req.order_id).all()
    photo_count = len(db_photos)
    
    company_name = getattr(company, "CompanyName", "전문시공업체")
    company_phone = getattr(company, "CompanyPhone", None) or getattr(company, "Phone", "")
    company_address = getattr(company, "CompanyAddress", "주소 정보 없음")
    map_url = f"https://map.naver.com/v5/search/{urllib.parse.quote(company_address)}"
    
    keyword_plan = build_keyword_plan(req.target_region, req.apt_name, req.build_type, req.main_keyword, req.region_strategy)
    paragraph_strategy = get_paragraph_strategy(photo_count, req.photo_style)
    cta_variants = generate_cta_variants(company_phone)
    
    if req.cta_experiment:
        selected_variant = random.choice(cta_variants["variants"])
    else:
        selected_variant = cta_variants["variants"][1] if req.cta_strength == "강하게" else cta_variants["variants"][0]
        
    active_cta_text = selected_variant["text"]
    
    titles = generate_title_candidates(req.target_region, req.apt_name, company_name)
    hashtags = generate_hashtags(req.target_region, company_name)

    base_user_prompt = build_user_prompt_text(
        company_name, req, company_address, keyword_plan, 6 if req.brand_mode == "강조" else 3, 
        paragraph_strategy, company_phone, active_cta_text, photo_count, map_url
    )

    return {
        "company_name": company_name, "phone": company_phone, "photo_count": photo_count,
        "keyword_plan": keyword_plan, "base_user_prompt": base_user_prompt,
        "cta_variants": cta_variants, "brand_name": company_name, "seo_target": req.seo_target,
        "titles": titles, "hashtags": hashtags,
        "selected_cta": selected_variant 
    }

# =========================================================
# [엔진 4] 자가 치유 및 학습 (API 호출 안정성 강화)
# =========================================================
def call_llm_safe(client, system_prompt, user_prompt, model="gpt-4o"):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            # [핵심] JSON 포맷 강제 (필요시 response_format={"type": "json_object"} 사용)
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM Call Failed: {e}")
        raise e

def regenerate_until_perfect(base_prompt, system_prompt, context_data, client, max_retries=2, db: Session = None):
    versions = [] 
    content = ""
    analysis = {"total_score": 0, "status": "FAIL", "fail_reasons": []}
    last_used_prompt = ""

    for attempt in range(max_retries + 1):
        # 매번 프롬프트 새로 조립 (오염 방지)
        current_prompt = construct_prompt_for_attempt(
            base_prompt, 
            analysis["fail_reasons"] if attempt > 0 else [], 
            context_data, 
            context_data['photo_count'],
            db
        )
        last_used_prompt = current_prompt

        try:
            content = call_llm_safe(client, system_prompt, current_prompt)
            
            # Judge 평가
            analysis = analyze_seo_detail(
                content, context_data['keyword_plan'], context_data['brand_name'], 
                context_data['phone'], context_data['photo_count'], context_data['seo_target']
            )
            analysis['attempt'] = attempt + 1

            # [데이터 자산화] 점수 기록 -> Rule 학습용
            versions.append({
                "attempt_no": attempt + 1,
                "prompt_text": current_prompt,
                "fail_reasons": analysis["fail_reasons"],
                "total_score": analysis["total_score"] 
            })

            if analysis["status"] in ["PASS", "CHECK"]:
                return content, analysis, versions, last_used_prompt

        except Exception as e:
            logger.error(f"Attempt {attempt+1} Failed: {e}")
            err_analysis = {"total_score": 0, "grade": "F", "fail_reasons": ["SERVER_ERROR"], "human_readable": [str(e)], "status": "ERROR"}
            return "", err_analysis, versions, last_used_prompt

    return content, analysis, versions, last_used_prompt

def update_rule_statistics(versions, db: Session):
    """[자율 진화] Rule 성과 기록 -> 추후 폐기 판단"""
    if not versions or len(versions) < 2: return

    for i in range(1, len(versions)):
        prev = versions[i-1]
        curr = versions[i]
        applied_rules = prev.get("fail_reasons", [])
        
        score_before = prev.get("total_score", 0)
        score_after = curr.get("total_score", 0)
        delta = score_after - score_before
        
        if applied_rules:
            for rule in applied_rules:
                try:
                    stat = models.AiRuleStat(rule_code=rule, score_before=score_before, score_after=score_after, score_delta=delta)
                    db.add(stat)
                except Exception as e:
                    logger.warning(f"Stats Update Failed: {e}")
    try: db.commit()
    except: db.rollback()

# =========================================================
# API 라우터
# =========================================================
# [NEW] CTA 이벤트 수집 API
@router.post("/cta/event")
async def log_cta_event(event_data: dict, db: Session = Depends(get_db)):
    """
    프론트엔드에서 CTA 클릭/전화 버튼 클릭 시 호출
    { "log_id": 123, "event_type": "click" or "conversion" }
    """
    try:
        log_id = event_data.get("log_id")
        event_type = event_data.get("event_type")
        
        exp = db.query(models.CtaExperiment).filter(models.CtaExperiment.log_id == log_id).first()
        if exp:
            if event_type == "click": exp.click_count += 1
            elif event_type == "conversion": exp.conversion_count += 1
            db.commit()
            return {"status": "ok"}
        return {"status": "error", "msg": "Experiment not found"}
    except Exception as e:
        logger.error(f"CTA Event Error: {e}")
        return {"status": "error"}
    
@router.post("/predict-seo")
async def predict_seo(req: AdvancedGenerateReq, db: Session = Depends(get_db)):
    try:
        db_photos = db.query(models.OrderPhoto).filter(models.OrderPhoto.OrderID == req.order_id).all()
        result = predict_seo_score_logic(req, len(db_photos))
        
        # [운영 강화] 예측 로그 저장
        try:
            pred_log = models.AiPredictionLog(
                order_id=req.order_id,
                predicted_score=result["predicted_score"],
                fail_probability=result["fail_probability"],
                risk_factors=json.dumps(result["risk_factors"])
            )
            db.add(pred_log)
            db.commit()
        except Exception as e:
            logger.error(f"Pred Log Save Error: {e}")

        return {"status": "ok", "prediction": result}
    except Exception as e:
        logger.error(f"Predict API Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "msg": str(e)})

@router.post("/preview-advanced-prompt")
async def preview_advanced_prompt(req: AdvancedGenerateReq, db: Session = Depends(get_db)):
    try:
        ctx = prepare_marketing_context(req, db)
        return {"status": "ok", "prompt": ctx["base_user_prompt"]}
    except Exception as e:
        logger.error(f"Preview API Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "msg": str(e)})

# [marketing.py] get_order_info_raw 함수 수정

@router.get("/order-info-raw/{order_id}")
async def get_order_info_raw(order_id: int, db: Session = Depends(get_db)):
    try:
        order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
        if not order: return JSONResponse(status_code=404, content={"msg": "주문 없음"})
        items = db.query(models.OrderItem).filter(models.OrderItem.OrderID == order_id).all()
        photos_count = db.query(models.OrderPhoto).filter(models.OrderPhoto.OrderID == order_id).count()
        item_details = []
        for i in items:
            cate1 = getattr(i, 'cate1', None) or getattr(i, 'ProductName', '')
            cate2 = getattr(i, 'cate2', None) or ''
            cate3 = getattr(i, 'cate3', None) or getattr(i, 'OptionInfo', '')
            detail = f"[{getattr(i, 'Location', '')}] {getattr(i, 'Category', '')} | {cate1}"
            if cate2:
                detail += f" / {cate2}"
            if cate3:
                detail += f" ({cate3})"
            item_details.append(detail)
        
        # [NEW] 설치면 정보 및 공구 추론 로직
        surface = getattr(order, "InstallSurface", "") or ""
        tools = []
        if "콘크리트" in surface or "타일" in surface or "대리석" in surface: tools.append("함마드릴/칼블럭")
        if "석고" in surface: tools.append("토굴앙카/천공앙카")
        if "샷시" in surface or "철판" in surface: tools.append("철판피스/직결피스")
        if "전동제품" in surface: tools.append("전선/몰딩/리모컨")
        if "긴사다리" in surface: tools.append("높은층고")
        
        tool_info = ", ".join(tools) if tools else ""

        return {
            "status": "ok", 
            "company_id": order.CompanyID, 
            "photo_count": photos_count,
            "customer_name": order.CustomerName, 
            "address": order.Address, 
            "item_summary": "\n".join(item_details),
            
            # [NEW] 설치면 및 공구 정보 반환
            "install_surface": surface,
            "tool_info": tool_info,
            
            "admin_note": getattr(order, "Memo", ""), 
            "extra_info": getattr(order, "ChecklistMemo", "")
        }
    except Exception as e: 
        logger.error(f"Order Info API Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "msg": str(e)})


@router.get("/order-memos/{order_id}")
def get_order_memos(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """작업기록(메모) 목록을 history_id와 함께 반환 (블로그 모달 편집용)"""
    rows = db.query(models.OrderHistory).filter(
        models.OrderHistory.OrderID == order_id,
        models.OrderHistory.LogType == '메모'
    ).order_by(models.OrderHistory.HistoryID.desc()).limit(200).all()

    # 회사 검증(주문이 우리 회사 소속인지 확인)
    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order or order.CompanyID != current_user.company_id:
        raise HTTPException(status_code=403, detail="forbidden")

    return {
        "ok": True,
        "items": [
            {
                "history_id": r.HistoryID,
                "contents": r.Contents,
                "reg_date": r.RegDate.isoformat() if r.RegDate else None,
                "member_name": r.MemberName
            } for r in rows
        ]
    }

@router.post("/generate-blog-auto")
async def generate_blog_auto(req: AdvancedGenerateReq, db: Session = Depends(get_db)):
    try:
        ctx = prepare_marketing_context(req, db)
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        dashboard_data = {
            "order_id": req.order_id, "company_id": req.company_id,
            "titles": ctx["titles"], "hashtags": ctx["hashtags"],
            "split_posts": {"enabled": req.split_count == 2, "posts": {}}
        }

        tasks = [("story_post", "스토리형", "1편"), ("info_post", "정보형", "2편")] if req.split_count == 2 else [("story_post", "종합형", "통합")]

        for key, mode_desc, label in tasks:
            system_prompt = f"당신은 '{ctx['company_name']}'의 '{req.persona}'입니다. [작성 모드]: {mode_desc}"
            content, analysis, prompt_versions, last_used_prompt = regenerate_until_perfect(
                ctx['base_user_prompt'], system_prompt, ctx, client, db=db
            )
            
            dashboard_data["split_posts"]["posts"][key] = {
                "label": label, "content": content,
                "generation": {"attempt": analysis.get("attempt", 1), "status": analysis["status"]},
                "seo": analysis,
                "prompt_versions": prompt_versions,
                "final_prompt": last_used_prompt
            }
            if analysis["status"] in ["PASS", "CHECK"]:
                update_rule_statistics(prompt_versions, db)

        # [운영 강화] 트랜잭션 분리 (생성 성공하면 일단 리턴, 저장은 별도 시도)
        main_post = dashboard_data["split_posts"]["posts"].get("story_post")
        if main_post and main_post["generation"]["status"] != "ERROR":
            try:
                content_json = json.dumps(dashboard_data["split_posts"]["posts"], ensure_ascii=False)
                new_log = models.AiLog(
                    order_id=req.order_id, company_id=req.company_id, target_region=req.target_region,
                    seo_score=main_post["seo"]["total_score"], seo_grade=main_post["seo"]["grade"],
                    status=main_post["generation"]["status"], attempt_count=main_post["generation"]["attempt"],
                    final_prompt=main_post["final_prompt"], content_result=content_json,
                    admin_note=req.admin_note, is_experiment=req.cta_experiment
                )
                db.add(new_log)
                db.commit()
                db.refresh(new_log)

                # CTA 실험 데이터 저장 (노출 시각 포함)
                sel_cta = ctx["selected_cta"]
                db.add(models.CtaExperiment(
                    log_id=new_log.log_id, 
                    variant_type=sel_cta["type"], 
                    cta_text=sel_cta["text"],
                    impressions=1 # 노출 카운트 시작
                ))

                # 상세 히스토리 저장
                for key in dashboard_data["split_posts"]["posts"]:
                    post_info = dashboard_data["split_posts"]["posts"][key]
                    for ver in post_info.get("prompt_versions", []):
                        db.add(models.AiPromptVersion(
                            log_id=new_log.log_id, attempt_no=ver["attempt_no"],
                            prompt_text=ver["prompt_text"], fail_reasons=json.dumps(ver["fail_reasons"])
                        ))
                    details = post_info["seo"].get("details", {})
                    db.add(models.AiSeoResult(
                        log_id=new_log.log_id, attempt_no=post_info["generation"]["attempt"],
                        total_score=post_info["seo"].get("total_score", 0), grade=post_info["seo"].get("grade", "F"),
                        score_brand=details.get("brand_exposure", 0), score_keyword=details.get("keyword_balance", 0),
                        score_length=details.get("content_length", 0), score_cta=details.get("cta_quality", 0),
                        score_structure=details.get("structure", 0), score_readability=details.get("readability", 0),
                        raw_json=json.dumps(details)
                    ))
                db.commit()
            except Exception as save_err:
                logger.error(f"DB Save Error: {save_err}")
                db.rollback() # 저장은 실패해도 클라이언트 응답은 성공으로
        
        return {
            "status": "ok", 
            "photo_count": ctx["photo_count"], 
            "results": dashboard_data["split_posts"]["posts"],
            "titles": ctx["titles"], 
            "hashtags": ctx["hashtags"],
            "cta_info": ctx["selected_cta"]
        }

    except Exception as e:
        logger.error(f"Generate API Fatal Error: {e}")
        db.rollback()
        return JSONResponse(status_code=500, content={"status": "error", "msg": str(e)})

@router.post("/generate-from-prompt")
async def generate_from_prompt(req: CustomGenerateReq, db: Session = Depends(get_db)):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": req.custom_prompt}])
        return {"status": "ok", "content": response.choices[0].message.content}
    except Exception as e:
        logger.error(f"Custom Prompt Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "msg": str(e)})

@router.get("/download-blog-package/{order_id}")
async def download_blog_package(order_id: int, db: Session = Depends(get_db)):
    return await download_photos_only(order_id, db)

@router.get("/download-photos/{order_id}")
async def download_photos_only(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.OrderID == order_id).first()
    if not order: return JSONResponse(status_code=404, content={"msg": "주문 없음"})
    company = db.query(models.Company).filter(models.Company.CompanyID == order.CompanyID).first()
    company_name = getattr(company, "CompanyName", "시공업체")
    contact = getattr(company, "CompanyPhone", None) or getattr(company, "Phone", "")
    region = order.Address.split()[0] if order.Address else "지역"
    project_safe = re.sub(r'[\\/*?:"<>|]', "", order.CustomerName).replace(" ", "")
    keyword_base = f"{region}_{project_safe}_{company_name.replace(' ', '')}"
    photos = db.query(models.OrderPhoto).filter(models.OrderPhoto.OrderID == order_id).all()
    if not photos: return JSONResponse(status_code=404, content={"msg": "사진 없음"})
    zip_buffer = io.BytesIO()
    has_files = False
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor: 
            for idx, photo in enumerate(photos):
                path = photo.FilePath.replace("\\", "/").lstrip("/")
                if not os.path.exists(path): path = os.path.join("static", "uploads", os.path.basename(photo.FilePath))
                if os.path.exists(path):
                    with open(path, "rb") as f: img_data = io.BytesIO(f.read())
                    fname = f"{keyword_base}_사진_{idx+1:02d}.jpg"
                    futures.append(executor.submit(enhance_photo_fast, img_data, company_name, contact, fname))
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result: fname, img_bytes = result; zf.writestr(fname, img_bytes); has_files = True
    if not has_files: return JSONResponse(status_code=404, content={"msg": "파일 없음"})
    zip_buffer.seek(0)
    filename = f"{keyword_base}_사진모음.zip"
    encoded_filename = urllib.parse.quote(filename)
    return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"})