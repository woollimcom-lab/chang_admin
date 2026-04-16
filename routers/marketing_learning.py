
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
import json
import models
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/marketing/learning", tags=["marketing-learning"])

class LearningNoteUpsertReq(BaseModel):
    json_blob: dict

class TrackedPostCreateReq(BaseModel):
    blog_url: str
    title: str | None = None
    main_keyword: str | None = None
    region_keyword: str | None = None
    published_at: datetime | None = None
    order_id: int | None = None
    features: dict | None = None

class SuccessToggleReq(BaseModel):
    is_success: bool = True

def _load_note(db: Session, company_id: int) -> models.MarketingLearningNote | None:
    return db.query(models.MarketingLearningNote).filter(models.MarketingLearningNote.company_id == company_id).first()

def _ensure_note(db: Session, company_id: int) -> models.MarketingLearningNote:
    note = _load_note(db, company_id)
    if note:
        return note
    note = models.MarketingLearningNote(company_id=company_id, version=1, json_blob="{}")
    db.add(note)
    db.commit()
    db.refresh(note)
    return note

def _safe_json_load(text: str) -> dict:
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}

def _safe_json_dump(obj: dict) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"

def _recompute_patterns(db: Session, company_id: int) -> dict:
    # 아주 단순한 규칙 기반: 성공 글들의 제목/키워드 기반 템플릿을 누적
    success_posts = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.company_id == company_id,
        models.MarketingTrackedPost.is_success == True
    ).all()

    fail_posts = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.company_id == company_id,
        models.MarketingTrackedPost.is_success == False
    ).all()

    def _median(nums, default=None):
        nums = [n for n in nums if isinstance(n, (int, float))]
        if not nums:
            return default
        nums = sorted(nums)
        m = len(nums)//2
        return nums[m] if len(nums)%2==1 else (nums[m-1]+nums[m])/2

    patterns = []
    if success_posts:
        # 제목 패턴(지역/품목/해결) 통계
        title_samples = [p.title for p in success_posts if (p.title or "").strip()]
        main_kw = [p.main_keyword for p in success_posts if (p.main_keyword or "").strip()]
        region_kw = [p.region_keyword for p in success_posts if (p.region_keyword or "").strip()]

        # 기본 템플릿 생성 (데이터 없으면 fallback)
        t1 = "{지역} {품목} {문제} 해결 후기"
        t2 = "{지역} {품목} 시공 후기, 체크포인트 정리"
        if main_kw:
            t1 = "{지역} " + main_kw[0] + " {문제} 해결 후기"
            t2 = "{지역} " + main_kw[0] + " 시공 후기, 체크포인트 정리"

        patterns.append({
            "id": "p_title_local_service",
            "name": "지역+품목+해결형 제목",
            # success/(success+fail) + smoothing
            "weight": round((len(success_posts) + 1) / (len(success_posts) + len(fail_posts) + 2), 3),
            "rules": {
                "title_templates": [t1, t2],
                "must_have_sections": ["현장상황", "고객반응", "해결", "결과", "주의사항"],
                "photo_guideline": {
                    "min": int(_median([(_safe_json_load(p.features_json).get('photo_count')) for p in success_posts], default=8) or 8),
                    "include_before_after": True,
                    "placement": ["도입 후 1장", "해결 직후 2장", "결과 섹션 3장"]
                },
                "keyword_density": {
                    "suggested": _median([(_safe_json_load(p.features_json).get('keyword_density')) for p in success_posts], default=0.0)
                },
                "heading_count": {
                    "min": int(_median([(_safe_json_load(p.features_json).get('heading_count')) for p in success_posts], default=5) or 5)
                }
            },
            "evidence": {
                "success_posts": len(success_posts),
                "fail_posts": len(fail_posts),
                "titles": title_samples[:5],
                "main_keywords": list(dict.fromkeys(main_kw))[:5],
                "region_keywords": list(dict.fromkeys(region_kw))[:5]
            }
        })
    note = _ensure_note(db, company_id)
    blob = _safe_json_load(note.json_blob)
    blob.setdefault("version", 1)
    blob.setdefault("success_def", {"rank_threshold": 5, "min_days": 3})
    blob["patterns"] = patterns
    blob.setdefault("prompt_tuning", {
        "tone_bias": "현장감 있는 담백한 후기",
        "cta_bias": "문의 유도는 1회만 자연스럽게",
        "forbidden": ["과장", "허위", "근거없는 1등 주장"]
    })
    note.json_blob = _safe_json_dump(blob)
    note.updated_at = datetime.now(timezone.utc)
    db.add(note)
    db.commit()
    return blob

@router.get("/note")
def get_learning_note(db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    note = _ensure_note(db, company_id)
    return {"company_id": company_id, "note": _safe_json_load(note.json_blob), "updated_at": note.updated_at}

@router.post("/note")
def upsert_learning_note(req: LearningNoteUpsertReq, db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    note = _ensure_note(db, company_id)
    blob = req.json_blob or {}
    note.json_blob = _safe_json_dump(blob)
    note.updated_at = datetime.now(timezone.utc)
    db.add(note)
    db.commit()
    return {"ok": True, "note": blob}

@router.post("/posts")
def create_tracked_post(req: TrackedPostCreateReq, db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    if not (req.blog_url or "").strip():
        raise HTTPException(status_code=400, detail="blog_url is required")
    post = models.MarketingTrackedPost(
        company_id=company_id,
        order_id=req.order_id,
        blog_url=req.blog_url.strip(),
        title=req.title,
        main_keyword=req.main_keyword,
        region_keyword=req.region_keyword,
        published_at=req.published_at,
        features_json=_safe_json_dump(req.features or {}) if req.features is not None else None
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"ok": True, "post_id": post.id}

@router.post("/posts/{post_id}/success")
def toggle_success(post_id: int, req: SuccessToggleReq, db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    post = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.company_id == company_id,
        models.MarketingTrackedPost.id == post_id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    post.is_success = bool(req.is_success)
    post.success_marked_at = datetime.now(timezone.utc) if post.is_success else None
    db.add(post)
    db.commit()

    # 성공 글이 바뀌면 패턴 재계산
    note = _recompute_patterns(db, company_id)
    return {"ok": True, "is_success": post.is_success, "learning_note": note}



class FeedbackReq(BaseModel):
    # 성공/실패 또는 순위 개선 등을 기록 (가중치 업데이트에 사용)
    is_success: bool | None = None
    rank: int | None = None
    note: str | None = None

@router.post("/posts/{post_id}/feedback")
def feedback(post_id: int, req: FeedbackReq, db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    post = db.query(models.MarketingTrackedPost).filter(
        models.MarketingTrackedPost.company_id == company_id,
        models.MarketingTrackedPost.id == post_id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    feat = _safe_json_load(post.features_json or "{}")
    fb = feat.get("feedback", {"success": 0, "fail": 0, "ranks": []})

    if req.is_success is True:
        fb["success"] = int(fb.get("success", 0)) + 1
    elif req.is_success is False:
        fb["fail"] = int(fb.get("fail", 0)) + 1

    if isinstance(req.rank, int):
        fb.setdefault("ranks", []).append(req.rank)
        fb["ranks"] = fb["ranks"][-30:]

    if req.note:
        fb.setdefault("notes", []).append(req.note)
        fb["notes"] = fb["notes"][-20:]

    feat["feedback"] = fb
    post.features_json = _safe_json_dump(feat)
    db.add(post)
    db.commit()

    # 피드백이 들어오면 학습 노트 재계산(가중치에 반영)
    note = _recompute_patterns(db, company_id)
    return {"ok": True, "learning_note": note}

@router.post("/recompute")
def recompute(db: Session = Depends(get_db), auth=Depends(get_current_user)):
    company_id = auth["company_id"]
    note = _recompute_patterns(db, company_id)
    return {"ok": True, "learning_note": note}
