from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session, sessionmaker, joinedload
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse
from sqlalchemy import func, or_, case, and_, not_, desc
from datetime import datetime, date, timedelta
from collections import Counter
import holidays
import math
import sys




# 프로젝트 설정 가져오기
from database import engine, get_db
# ★ [중요] auth.py로 옮긴 함수를 여기서 가져옵니다.
from auth import get_current_user, get_user_or_key
import models
from services.view_service import backfill_order_managers_for_company, list_order_manager_names, list_order_manager_pairs

# 수동 연결 도구 (대시보드 메인 화면용)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

router = APIRouter(tags=["dashboard"])

# ------------------------------------------------------------------------------
# 템플릿 및 필터 설정 (화면 렌더링용)
# ------------------------------------------------------------------------------
templates = Jinja2Templates(directory="templates")

def safe_num(val):
    if val is None or val == "": return 0.0
    try: return float(str(val).replace(",", ""))
    except: return 0.0

def safe_int(val):
    try: return int(safe_num(val))
    except: return 0

def format_comma(value):
    try: return "{:,.0f}".format(float(value or 0))
    except: return "0"

def format_number(value):
    try: return "{:,}".format(int(float(value or 0)))
    except: return "0"

def format_phone(value):
    if not value: return ""
    p = value.replace("-", "")
    if len(p) == 11: return f"{p[:3]}-{p[3:7]}-{p[7:]}"
    return value

def format_time_pretty(dt):
    if not isinstance(dt, datetime): return ""
    h = dt.hour; m = dt.minute
    ampm = "오후" if h >= 12 else "오전"
    if h > 12: h -= 12
    if h == 0: h = 12
    return f"{ampm} {h}:{m:02d}"

def calc_final_price(total, discount, vat_yn):
    supply = float(total or 0) - float(discount or 0)
    val = supply + (supply * 0.1) if vat_yn == 'Y' else supply
    return int(round(val))

templates.env.filters.update({
    "format_comma": format_comma,
    "format_number": format_number,
    "format_phone": format_phone,
    "format_time_pretty": format_time_pretty
})
templates.env.globals.update({
    "safe_num": safe_num, "safe_int": safe_int, "int": int, "calc_final_price": calc_final_price
})


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request, db: Session = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    mem = db.query(models.CompanyMember).filter(models.CompanyMember.UserID == current_user.UserID).first()
    company = db.query(models.Company).filter(models.Company.CompanyID == current_user.company_id).first()
    base_year = date.today().year
    holiday_map = {}
    try:
        kr_holidays = holidays.country_holidays("KR", years=range(base_year - 1, base_year + 3), language="ko")
        holiday_map = {day.strftime("%Y-%m-%d"): name for day, name in kr_holidays.items()}
    except Exception:
        holiday_map = {}

    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "user_name": current_user.Name,
        "user_role": (mem.RoleName if mem else "직원"),
        "company_name": (company.CompanyName if company else ""),
        "holiday_map": holiday_map
    })


@router.get("/api/calendar/holidays")
async def get_calendar_holidays(year: int = Query(None)):
    base_year = year or date.today().year
    try:
        kr_holidays = holidays.country_holidays("KR", years=range(base_year - 1, base_year + 2), language="ko")
        return {day.strftime("%Y-%m-%d"): name for day, name in kr_holidays.items()}
    except Exception:
        return {}
# ==============================================================================
# [1] 대시보드 메인 화면 (기존 로직 100% 유지)
# ==============================================================================
@router.get("/dashboard")
async def dashboard(
        request: Request, 
        search: str = Query(None), 
        filterStat: str = Query(None), 
        date_param: str = Query(None, alias="dash_Date"),
        mode: str = Query(None),
        page: int = Query(1)
    ):

    # 수동 연결 (Depends 에러 방지)
    db = SessionLocal()
    
    try:
        # 1. 사용자 인증 체크
        current_user = await get_current_user(request, db)
        if not current_user:
            return RedirectResponse(url="/login", status_code=302)
        
        mem = db.query(models.CompanyMember).filter(models.CompanyMember.UserID == current_user.UserID).first()
        if not mem: return RedirectResponse(url="/login") # 소속 정보 없으면 튕겨냄

        company = db.query(models.Company).filter(models.Company.CompanyID == mem.CompanyID).first()
        company_name = company.CompanyName if company else "상호 미등록"

        # 내 멤버 정보 조회
        my_member = db.query(models.CompanyMember).filter(
            models.CompanyMember.UserID == current_user.UserID,
            models.CompanyMember.CompanyID == current_user.company_id
        ).first()
        
        user_role = my_member.RoleName if my_member else "직원" 
        my_member_id = my_member.ID if my_member else 0
        
        is_master = (user_role == '대표')
        has_schedule_perm = is_master or (my_member.Perm_EditSchedule if my_member else False)
        
        # 3. 리스트 필터 설정
        my_company_id = current_user.company_id
        backfill_order_managers_for_company(db, my_company_id)
        
        my_order_ids = db.query(models.OrderManager.OrderID).filter(
            models.OrderManager.MemberID == my_member_id
        )

        if mode == 'mine':
            base_filter = and_(
                models.Order.CompanyID == my_company_id, 
                models.Order.OrderID.in_(my_order_ids)
            )
        else:
            base_filter = (models.Order.CompanyID == my_company_id)

        # 4. 공통 조건 설정
        today = date.today()
        cond_schedule_const = models.Order.ProgressStatus.in_(['시공예정', '작업완료'])
        not_done_status = models.Order.ProgressStatus.notin_(['작업완료', '취소'])
        cond_status_visit = (models.Order.ProgressStatus == '방문상담')
        cond_status_as    = (models.Order.ProgressStatus == 'AS요청')
        cond_status_quote = (models.Order.ProgressStatus == '견적상담')
        
        not_waiting = or_(models.Order.IsWaiting == None, models.Order.IsWaiting != 'Y')
        is_active   = or_(models.Order.IsHold == None, models.Order.IsHold != 'Y')

        # 5. [통계 쿼리]
        final_amt_expr = case(
            (models.Order.FinalAmount > 0, models.Order.FinalAmount),
            else_=(func.coalesce(models.Order.TotalAmount, 0) - func.coalesce(models.Order.DiscountAmount, 0)) * case((models.Order.IsVatIncluded == 'Y', 1.1), else_=1.0)
        )
        receivable_expr = final_amt_expr - func.coalesce(models.Order.DepositAmount, 0)
        this_month_start = date(today.year, today.month, 1)

        # 변수 초기화
        c1=0; c2=0; c3=0; c4=0; c5=0; 
        ongoing_cnt=0; ongoing_amt=0
        wait_cnt=0; wait_amt=0
        hold_cnt=0; hold_amt=0
        money_cnt=0; money_amt=0
        qv_amt=0; completed_sales=0
        grand_total_flow=0

        try:
            stat_row = db.query(
                func.count(case((and_(models.Order.ProgressStatus == '견적상담', is_active, not_waiting), 1))),
                func.count(case((and_(models.Order.ProgressStatus == '방문상담', is_active, not_waiting), 1))),
                func.count(case((and_(models.Order.ProgressStatus.in_(['시공예정']), is_active, not_waiting), 1))),
                func.count(case((and_(models.Order.ProgressStatus == 'AS요청', is_active, not_waiting), 1))),
                func.sum(case((and_(models.Order.ProgressStatus.in_(['시공예정']), models.Order.ConstructionDate >= datetime.combine(today, datetime.min.time()), is_active, not_waiting), final_amt_expr), else_=0)),
                func.count(case((and_(models.Order.ProgressStatus.in_(['시공예정']), models.Order.ConstructionDate >= datetime.combine(today, datetime.min.time()), is_active, not_waiting), 1))),
                func.sum(case((and_(models.Order.IsWaiting == 'Y', not_done_status), final_amt_expr), else_=0)),
                func.count(case((and_(models.Order.IsWaiting == 'Y', not_done_status), 1))),
                func.sum(case((and_(models.Order.IsHold == 'Y', not_done_status), final_amt_expr), else_=0)),
                func.count(case((and_(models.Order.IsHold == 'Y', not_done_status), 1))),
                func.sum(case((and_(models.Order.ProgressStatus.in_(['작업완료']), is_active, or_(models.Order.PaymentStatus != '입금완료', models.Order.PaymentStatus == None)), receivable_expr), else_=0)),
                func.count(case((and_(models.Order.ProgressStatus.in_(['작업완료']), is_active, or_(models.Order.PaymentStatus != '입금완료', models.Order.PaymentStatus == None)), 1))),
                func.sum(case((and_(models.Order.ProgressStatus.in_(['견적상담','방문상담']), is_active, not_waiting), final_amt_expr), else_=0)),
                func.count(case((and_(models.Order.ProgressStatus.in_(['견적상담','방문상담']), is_active, not_waiting), 1))),
                func.sum(case((and_(models.Order.ProgressStatus.in_(['작업완료']), models.Order.ConstructionDate >= this_month_start), final_amt_expr), else_=0)),
                func.count(case((and_(models.Order.ProgressStatus.in_(['작업완료']), models.Order.ConstructionDate >= this_month_start), 1)))
            ).filter(base_filter).first()

            if stat_row:
                c1, c2, c3, c5 = stat_row[0], stat_row[1], stat_row[2], stat_row[3]
                ongoing_amt, ongoing_cnt = int(stat_row[4] or 0), stat_row[5]
                wait_amt, wait_cnt = int(stat_row[6] or 0), stat_row[7]
                hold_amt, hold_cnt = int(stat_row[8] or 0), stat_row[9]
                money_amt, money_cnt = int(stat_row[10] or 0), stat_row[11]
                qv_amt = int(stat_row[12] or 0)
                completed_sales, c4 = int(stat_row[14] or 0), stat_row[15]
                grand_total_flow = ongoing_amt + wait_amt + qv_amt
                
        except Exception as e:
            print(f"Stats Error: {e}")

        # 6. 리스트 조회
        dt_start = datetime.combine(today, datetime.min.time())
        dt_end   = datetime.combine(today + timedelta(days=1), datetime.min.time())
        dt_future_end = datetime.combine(today + timedelta(days=60), datetime.min.time())

        def get_schedule_query(start_dt, end_dt):
            q1 = db.query(models.Order).filter(base_filter, is_active, cond_schedule_const, not_waiting, models.Order.ProgressStatus != '취소', models.Order.ConstructionDate >= start_dt, models.Order.ConstructionDate < end_dt)
            q2 = db.query(models.Order).filter(base_filter, is_active, cond_status_visit, not_waiting, models.Order.ProgressStatus != '취소', models.Order.VisitDate >= start_dt, models.Order.VisitDate < end_dt)
            q3 = db.query(models.Order).filter(base_filter, is_active, cond_status_as, not_waiting, models.Order.ProgressStatus != '취소', models.Order.ASDate >= start_dt, models.Order.ASDate < end_dt)
            q4 = db.query(models.Order).filter(base_filter, is_active, cond_status_quote, not_waiting, models.Order.ProgressStatus != '취소', models.Order.RequestDate >= start_dt, models.Order.RequestDate < end_dt)
            
            res = []
            res.extend(q1.all())
            res.extend(q2.all())
            res.extend(q3.all())
            res.extend(q4.all())
            return res

        list_today = get_schedule_query(dt_start, dt_end)
        list_future_raw = get_schedule_query(dt_end, dt_future_end)

        # ★ 해결 포인트: q_unlimited를 위로 끌어올립니다.
        q_unlimited = db.query(models.Order).filter(base_filter)

        # [추가] 시공예정이나 아직 주문 안 된 건 (미래 일정 포함)을 '오늘 할 일'에 병합
        list_unordered = q_unlimited.filter(
            is_active, not_done_status, not_waiting, 
            models.Order.ProgressStatus.in_(['시공예정']), 
            or_(models.Order.IsOrdered == None, models.Order.IsOrdered != 'Y'),
            models.Order.ConstructionDate >= dt_start
        ).all()
        today_ids = {o.OrderID for o in list_today}
        for o in list_unordered:
            if o.OrderID not in today_ids:
                list_today.append(o)
                today_ids.add(o.OrderID)

        # 7. 하단 리스트 (지연 일정 세분화: 7일 기준)
        q_unlimited = db.query(models.Order).filter(base_filter)
        dt_week_ago = dt_start - timedelta(days=7)
        
        # [A] 최근 7일 (놓친 일정)
        q_rm1 = q_unlimited.filter(is_active, not_done_status, not_waiting, models.Order.ProgressStatus.in_(['시공예정']), models.Order.ConstructionDate >= dt_week_ago, models.Order.ConstructionDate < dt_start)
        q_rm2 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_visit, models.Order.VisitDate >= dt_week_ago, models.Order.VisitDate < dt_start)
        q_rm3 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_as, models.Order.ASDate >= dt_week_ago, models.Order.ASDate < dt_start)
        q_rm4 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_quote, models.Order.RequestDate >= dt_week_ago, models.Order.RequestDate < dt_start)
        
        list_recent_missed = []
        list_recent_missed.extend(q_rm1.limit(20).all())
        list_recent_missed.extend(q_rm2.limit(20).all())
        list_recent_missed.extend(q_rm3.limit(20).all())
        list_recent_missed.extend(q_rm4.limit(20).all())

        # [B] 7일 이전 (장기 지연 / 관리)
        q_om1 = q_unlimited.filter(is_active, not_done_status, not_waiting, models.Order.ProgressStatus.in_(['시공예정']), models.Order.ConstructionDate < dt_week_ago)
        q_om2 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_visit, models.Order.VisitDate < dt_week_ago)
        q_om3 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_as, models.Order.ASDate < dt_week_ago)
        q_om4 = q_unlimited.filter(is_active, not_done_status, not_waiting, cond_status_quote, models.Order.RequestDate < dt_week_ago)

        list_old_missed = []
        list_old_missed.extend(q_om1.limit(20).all())
        list_old_missed.extend(q_om2.limit(20).all())
        list_old_missed.extend(q_om3.limit(20).all())
        list_old_missed.extend(q_om4.limit(20).all())

        missed_cnt = len(list_recent_missed) + len(list_old_missed)
        missed_amt = sum([int(o.FinalAmount or 0) for o in list_recent_missed + list_old_missed])

        list_wait = q_unlimited.filter(models.Order.IsWaiting == 'Y', not_done_status).order_by(models.Order.RequestDate.desc()).limit(20).all()
        list_money = q_unlimited.filter(is_active, models.Order.ProgressStatus.in_(['작업완료']), or_(models.Order.PaymentStatus != '입금완료', models.Order.PaymentStatus == None)).order_by(models.Order.ConstructionDate.desc()).limit(20).all()

        missed_cnt = len(list_recent_missed) + len(list_old_missed)
        missed_amt = sum([int(o.FinalAmount or 0) for o in list_recent_missed + list_old_missed])

        # 8. 검색
        list_search = []
        if search:
            list_search = db.query(models.Order).filter(
                base_filter, 
                or_(models.Order.CustomerName.like(f"%{search}%"), models.Order.PhoneNumber.like(f"%{search}%"), models.Order.Address.like(f"%{search}%"))
            ).order_by(models.Order.RequestDate.desc()).limit(50).all()
        elif filterStat:
            q_search = db.query(models.Order).filter(base_filter)
            if filterStat == '보류': q_search = q_search.filter(models.Order.IsHold == 'Y', not_done_status)
            elif filterStat == '지연': 
                cond_m1 = and_(models.Order.ProgressStatus.in_(['시공예정']), models.Order.ConstructionDate < dt_start)
                cond_m2 = and_(cond_status_visit, models.Order.VisitDate < dt_start)
                cond_m3 = and_(cond_status_as, models.Order.ASDate < dt_start)
                cond_m4 = and_(cond_status_quote, models.Order.RequestDate < dt_start)
                q_search = q_search.filter(is_active, not_waiting, not_done_status, or_(cond_m1, cond_m2, cond_m3, cond_m4))
            elif filterStat == '대기': q_search = q_search.filter(models.Order.IsWaiting == 'Y', not_done_status)
            elif filterStat == '미수금': q_search = q_search.filter(is_active, models.Order.ProgressStatus.in_(['작업완료']), or_(models.Order.PaymentStatus != '입금완료', models.Order.PaymentStatus == None))
            elif filterStat == '완료': q_search = q_search.filter(models.Order.ProgressStatus.in_(['작업완료']), models.Order.ConstructionDate >= this_month_start)
            elif filterStat == 'AS': q_search = q_search.filter(models.Order.ProgressStatus == 'AS요청', is_active, not_waiting)
            elif filterStat == '견적방문': q_search = q_search.filter(models.Order.ProgressStatus.in_(['견적상담', '방문상담']), is_active, not_waiting)
            elif filterStat == '견적': q_search = q_search.filter(models.Order.ProgressStatus == '견적상담', is_active, not_waiting)
            elif filterStat == '방문': q_search = q_search.filter(models.Order.ProgressStatus == '방문상담', is_active, not_waiting)
            elif filterStat == '시공': q_search = q_search.filter(models.Order.ProgressStatus.in_(['시공예정']), is_active, not_waiting)
            list_search = q_search.order_by(models.Order.RequestDate.desc()).limit(100).all()
        elif date_param:
            try:
                t_date = datetime.strptime(date_param, '%Y-%m-%d')
                list_search = get_schedule_query(t_date, t_date + timedelta(days=1))
            except: pass

        # 9. 데이터 가공
        week_names = ["월", "화", "수", "목", "금", "토", "일"]
        all_target_orders = []
        if list_search: all_target_orders.extend(list_search)
        all_target_orders.extend(list_today)
        all_target_orders.extend(list_recent_missed) # 변경됨
        all_target_orders.extend(list_old_missed)    # 추가됨
        all_target_orders.extend(list_wait)
        all_target_orders.extend(list_money)
        all_target_orders.extend(list_future_raw)
        
        all_ids = list(set([o.OrderID for o in all_target_orders]))
        history_map = {}; item_map = {}
        
        if all_ids:
            try:
                item_rows = db.query(models.OrderItem.OrderID, models.OrderItem.Category, models.OrderItem.Category1, models.OrderItem.BlindCount).filter(models.OrderItem.OrderID.in_(all_ids)).all()
                from collections import defaultdict
                temp_items = defaultdict(list)
                for r in item_rows: temp_items[r.OrderID].append(r)
                for oid, items in temp_items.items():
                    sm = {}
                    for i in items:
                        k = i.Category1 or i.Category
                        if not k: continue
                        val = i.BlindCount if i.Category=='블라인드' and i.BlindCount else 1
                        sm[k] = sm.get(k, 0) + val
                    item_map[oid] = ", ".join([f"{k} {v}" for k, v in sm.items()])
                
                cnt_rows = db.query(models.OrderHistory.OrderID, func.count(models.OrderHistory.HistoryID)).filter(models.OrderHistory.OrderID.in_(all_ids), models.OrderHistory.LogType=='메모').group_by(models.OrderHistory.OrderID).all()
                for oid, c in cnt_rows: history_map[oid] = {'cnt':c, 'last':None, 'list':[]}
                rec_rows = db.query(models.OrderHistory).filter(models.OrderHistory.OrderID.in_(all_ids), models.OrderHistory.LogType=='메모').order_by(models.OrderHistory.HistoryID.desc()).all()
                for h in rec_rows:
                    oid = h.OrderID
                    if oid not in history_map: history_map[oid] = {'cnt':0, 'last':None, 'list':[]}
                    if len(history_map[oid]['list']) < 10: history_map[oid]['list'].append(h.Contents)
                    if not history_map[oid]['last']: history_map[oid]['last'] = h.Contents
            except Exception as e: print(f"Mapping Error: {e}")

        def apply_enrich(order_list):
            if not order_list: return []
            res = []
            for o in order_list:
                t_date = o.RequestDate
                if o.ProgressStatus == 'AS요청': t_date = o.ASDate
                elif o.ProgressStatus == '방문상담': t_date = o.VisitDate
                elif o.ProgressStatus in ['시공예정', '작업완료']: t_date = o.ConstructionDate
                if not t_date: t_date = o.RegDate 
                o.EffDate = t_date
                if t_date:
                    wd = week_names[t_date.weekday()]
                    o.DateOnly = f"{t_date.month}/{t_date.day}({wd})"
                    o.TimeOnly = t_date.strftime('%H:%M')
                else: o.DateOnly = ""; o.TimeOnly = ""

                if o.FinalAmount is not None: o.FinalAmt = int(o.FinalAmount)
                else:
                    tot = float(o.TotalAmount or 0); disc = float(o.DiscountAmount or 0)
                    final = (tot - disc) * 1.1 if o.IsVatIncluded == 'Y' else (tot - disc)
                    o.FinalAmt = int(round(final))
                
                o.ItemSummary = item_map.get(o.OrderID, "")
                h = history_map.get(o.OrderID)
                if h: o.HistoryCount = h['cnt']; o.LastHistory = h['last']; o.HistoryList = h['list']
                else: o.HistoryCount = 0; o.LastHistory = None; o.HistoryList = []
                
                # [추가] 본인 이름 숨기기 로직
                manager_pairs = list_order_manager_pairs(db, o.OrderID)
                if manager_pairs:
                    names = [name for member_id, name in manager_pairs if member_id != my_member_id]
                    o.DisplayManager = ", ".join(names) if names else ""
                else:
                    o.DisplayManager = ""
                
                o.show_unordered_badge = o.ProgressStatus == '시공예정' and (o.IsOrdered is None or o.IsOrdered != 'Y')

                res.append(o)
            res.sort(key=lambda x: x.EffDate or datetime.min)
            return res

        search_orders = apply_enrich(list_search) if list_search else None
        today_orders = apply_enrich(list_today)
        recent_missed_orders = apply_enrich(list_recent_missed) # 추가됨
        old_missed_orders = apply_enrich(list_old_missed)       # 추가됨
        wait_orders = apply_enrich(list_wait)
        money_orders = apply_enrich(list_money)
        temp_future = apply_enrich(list_future_raw)
        
        week_orders = {}
        after_orders = []
        for o in temp_future:
            if not o.EffDate: continue
            diff = (o.EffDate.date() - today).days
            if diff <= 7:
                k = o.EffDate.strftime('%Y-%m-%d')
                if k not in week_orders: week_orders[k] = {'date': o.EffDate, 'day_name': week_names[o.EffDate.weekday()], 'list': []}
                week_orders[k]['list'].append(o)
            else: after_orders.append(o)

        perms = {
            "revenue": current_user.perm_revenue, "expense": current_user.perm_expense, "staff": current_user.perm_staff, "stats": current_user.perm_stats,
            "schedule": has_schedule_perm, 
            "margin": current_user.perm_margin, "total": current_user.perm_total,
            "company": (my_member.Perm_ManageCompanyInfo if my_member else False), 
            "site": (my_member.Perm_ManageSiteCheck if my_member else False),
            "delete_order": (my_member.Perm_DeleteOrder if my_member else False) or is_master
        }
        
        kpi_data = { "completed_sales": completed_sales, "ongoing_sales": ongoing_amt, "qv_sales": qv_amt, "total_receivable": money_amt }
        counts = { "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "money": money_cnt, "wait": wait_cnt, "missed": missed_cnt, "hold": hold_cnt }

        return templates.TemplateResponse("dashboard.html", {
            "request": request, "company_name": company_name, "user_name": current_user.Name, "user_role": user_role,
            "perms": perms, "kpi": kpi_data, "counts": counts,
            "search_orders": search_orders, "today_orders": today_orders, 
            "recent_missed_orders": recent_missed_orders, "old_missed_orders": old_missed_orders, # 변경됨
            "wait_orders": wait_orders, "money_orders": money_orders, "week_orders": week_orders, "after_orders": after_orders,
            "grand_total_flow": grand_total_flow,
            "ongoing_cnt": ongoing_cnt, "ongoing_amt": ongoing_amt, "missed_cnt": missed_cnt, "missed_amt": missed_amt,
            "wait_cnt": wait_cnt, "wait_amt": wait_amt, "hold_cnt": hold_cnt, "hold_amt": hold_amt,
            "money_cnt": money_cnt, "money_amt": money_amt, "qv_cnt": c1+c2, "qv_amt": qv_amt,
            "filter_stat": filterStat, "filter_date": date_param, "search_keyword": search
        })
        
    finally:
        db.close()


# ==============================================================================
# [2] 캘린더 스케줄 API (main.py에서 이사 옴)
# ==============================================================================
@router.get("/api/schedule")
async def get_schedule(
    request: Request,
    start: str = Query(None), 
    end: str = Query(None), 
    mode: str = Query(None), 
    db: Session = Depends(get_db)
):
    auth = await get_user_or_key(request, db)
    if not auth: return [] 

    # 1. 날짜 범위 처리 최적화
    try:
        s_dt = datetime.strptime(start[:10], '%Y-%m-%d') if start else datetime.now() - timedelta(days=30)
        e_dt = datetime.strptime(end[:10], '%Y-%m-%d') if end else datetime.now() + timedelta(days=60)
    except:
        s_dt = datetime.now() - timedelta(days=30); e_dt = datetime.now() + timedelta(days=60)

    # 2. 쿼리 최적화: joinedload로 N+1 방지 및 필요한 필드 위주 필터링
    # [Reason] 관련 품목(items)을 미리 로드하여 루프 내 추가 쿼리 발생을 막습니다.
    base_query = db.query(models.Order).options(
        joinedload(models.Order.items) 
    ).filter(
        models.Order.CompanyID == auth['company_id'], 
        or_(models.Order.IsHold == None, models.Order.IsHold != 'Y'), 
        or_(
            and_(models.Order.ConstructionDate >= s_dt, models.Order.ConstructionDate < e_dt),
            and_(models.Order.VisitDate >= s_dt, models.Order.VisitDate < e_dt),
            and_(models.Order.ASDate >= s_dt, models.Order.ASDate < e_dt),
            and_(models.Order.RequestDate >= s_dt, models.Order.RequestDate < e_dt)
        )
    )

    # 권한 필터링 (기존 유지)
    if auth.get('company_id'):
        backfill_order_managers_for_company(db, auth['company_id'])

    if auth['type'] == 'external':
        assigned_order_ids = db.query(models.OrderManager.OrderID).filter(
            models.OrderManager.MemberID == auth['member_id']
        )
        base_query = base_query.filter(models.Order.OrderID.in_(assigned_order_ids))
    elif auth['type'] == 'user':
        assigned_order_ids = db.query(models.OrderManager.OrderID).filter(
            models.OrderManager.MemberID == auth['member_id']
        )
        if mode == 'mine' and auth.get('member_id'):
            base_query = base_query.filter(models.Order.OrderID.in_(assigned_order_ids))
        elif not auth.get('perm_schedule', False):
            base_query = base_query.filter(models.Order.OrderID.in_(assigned_order_ids))

    orders = base_query.all()
    events = []
    
    for o in orders:
        try:
            # 상태별 날짜 및 클래스 결정 로직 (최적화)
            status_map = {
                'AS요청': (o.ASDate or o.ConstructionDate, "fc-event-as bg-as"),
                '작업완료': (o.ConstructionDate or o.VisitDate, "fc-event-done bg-done"),
                '시공예정': (o.ConstructionDate or o.VisitDate, "fc-event-inst bg-const"),
                '방문상담': (o.VisitDate or o.RequestDate, "fc-event-visit bg-visit")
            }
            
            evt_date, status_cls = status_map.get(o.ProgressStatus, (o.RequestDate, "fc-event-req bg-req"))
            if not evt_date: continue
            
            # [Reason] 루프 밖에서 미리 로드된 items를 사용하여 Counter 집계
            item_summary = ""
            if o.items:
                cats = [i.Category1 or i.Category for i in o.items if (i.Category1 or i.Category)]
                if cats: 
                    cnt_dict = dict(Counter(cats))
                    item_summary = ", ".join([f"{k} {v}" for k, v in cnt_dict.items()])
            
            # 금액 계산 (공통 함수 calc_final_price 활용 제안)
            price_str = ""
            if auth['type'] == 'user' and (o.TotalAmount or 0) > 0:
                final = calc_final_price(o.TotalAmount, o.DiscountAmount, o.IsVatIncluded)
                price_str = f"{final:,}원"

            link_url = f"/view/{o.OrderID}"
            if auth['type'] == 'external':
                current_key = request.query_params.get("access_key")
                link_url = f"/w/view/{o.OrderID}?key={current_key}"

            events.append({
                "id": o.OrderID,
                "title": f"{o.CustomerName} ({o.ProgressStatus or '견적상담'})",
                "start": evt_date.strftime('%Y-%m-%d'),
                "time": evt_date.strftime('%H:%M'),
                "status": o.ProgressStatus or "견적상담",
                "items": item_summary,
                "price": price_str,
                "className": status_cls,
                "url": link_url,
                # [Reason] 프론트엔드 배지 표시를 위한 서브 상태값 추가 전달
                "extendedProps": {
                    "IsWaiting": o.IsWaiting,
                    "IsHold": o.IsHold,
                    "IsOrdered": o.IsOrdered,
                    "IsReceived": o.IsReceived,
                    "PaymentStatus": o.PaymentStatus
                }
            })
        except Exception as e:
            print(f"Event parsing error (ID:{o.OrderID}): {e}")
            continue

    return events


# ==============================================================================
# [3] 주문 요약 팝업 API (main.py에서 이사 옴)
# ==============================================================================
@router.get("/api/order/summary/{order_id}")
async def get_order_summary(order_id: int, request: Request, db: Session = Depends(get_db)):
    auth = await get_user_or_key(request, db)
    if not auth: return JSONResponse({}, status_code=403)

    order = db.query(models.Order).filter(
        models.Order.OrderID == order_id,
        models.Order.CompanyID == auth['company_id']
    ).first()
    
    if not order: return JSONResponse({}, status_code=404)

    if order.FinalAmount is not None:
        final_amt = int(order.FinalAmount)
    else:
        tot = float(order.TotalAmount or 0); disc = float(order.DiscountAmount or 0)
        val = (tot - disc) * 1.1 if order.IsVatIncluded == 'Y' else (tot - disc)
        final_amt = int(round(val))

    t_date = None
    if order.ProgressStatus == 'AS요청': t_date = order.ASDate or order.ConstructionDate
    elif order.ProgressStatus == '방문상담': t_date = order.VisitDate or order.RequestDate
    elif order.ProgressStatus in ['시공예정', '작업완료']: t_date = order.ConstructionDate
    if not t_date: t_date = order.RequestDate

    date_str = ""; time_str = ""
    week_names = ["월", "화", "수", "목", "금", "토", "일"]
    if t_date:
        date_str = f"{t_date.month}/{t_date.day}({week_names[t_date.weekday()]})"
        time_str = t_date.strftime('%H:%M')

    bg = "bg-req"
    st = order.ProgressStatus
    if st == 'AS요청': bg = "bg-as"
    elif st == '방문상담': bg = "bg-visit"
    elif st in ['시공예정', '주문', '수령']: bg = "bg-const"
    elif st in ['작업완료', '시공완료']: bg = "bg-done"

    item_summary = ""
    if order.items:
        cats = [i.Category1 or i.Category for i in order.items if (i.Category1 or i.Category)]
        if cats:
            c = Counter(cats)
            item_summary = ", ".join([f"{k} {v}" for k, v in c.items()])

    histories = db.query(models.OrderHistory).filter(
        models.OrderHistory.OrderID == order_id, 
        models.OrderHistory.LogType == '메모'
    ).order_by(models.OrderHistory.HistoryID.desc()).limit(10).all()

    history_list = [h.Contents for h in histories]

    show_unordered_badge = order.ProgressStatus == '시공예정' and (order.IsOrdered is None or order.IsOrdered != 'Y')

    manager_names = list_order_manager_names(db, order.OrderID)
    manager_text = ", ".join(manager_names) if manager_names else ""

    return {
        "id": order.OrderID,
        "status": order.ProgressStatus,
        "stat_bg": bg,
        "name": order.CustomerName,
        "address": order.Address,
        "phone": order.PhoneNumber,
        "price": "{:,}".format(final_amt),
        "item_summary": item_summary,
        "site_info": order.ChecklistMemo,
        "site_surface": order.InstallSurface,
        "memo": order.Memo,
        "date_str": date_str,
        "time_str": time_str,
        "manager": manager_text,
        "history_list": history_list, 
        "badges": {
            "ordered": order.IsOrdered,
            "received": order.IsReceived,
            "paid": order.PaymentStatus,
            "waiting": order.IsWaiting,
            "hold": order.IsHold,
            "show_unordered_badge": show_unordered_badge
        }
    }


# ==============================================================================
# [4] 통계 관련 API (main.py에서 이사 옴)
# ==============================================================================
@router.get("/api/stats/data")
def get_stats_data(year: int = Query(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # 권한 확인
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id
    ).first()
    
    has_total_perm = (member.RoleName == '대표' or member.Perm_ViewTotal) if member else False
    done_stats = ['작업완료']
    final_price_expr = func.coalesce(models.Order.FinalAmount, 0)

    # 월별 집계 함수
    def get_year_agg(target_year):
        results = db.query(
            func.month(models.Order.ConstructionDate).label('m'),
            func.sum(final_price_expr).label('total_amt'),
            func.count(models.Order.OrderID).label('cnt')
        ).filter(
            models.Order.ProgressStatus.in_(done_stats),
            func.year(models.Order.ConstructionDate) == target_year,
            models.Order.CompanyID == current_user.company_id
        ).group_by(
            func.month(models.Order.ConstructionDate)
        ).all()

        amt_list = [0] * 12
        cnt_list = [0] * 12

        for r in results:
            m_idx = r.m - 1
            if 0 <= m_idx < 12:
                amt_list[m_idx] = int(r.total_amt or 0) if has_total_perm else 0
                cnt_list[m_idx] = int(r.cnt or 0)
        
        return {"amt": amt_list, "cnt": cnt_list}

    cur_year = datetime.now().year
    next_year = year + 1
    
    data_selected = get_year_agg(year)
    data_next = get_year_agg(next_year)
    data_current = get_year_agg(cur_year)
    
    total_rev = sum(data_selected['amt']) if has_total_perm else 0
    total_cnt = sum(data_selected['cnt'])
    
    cat_stats = db.query(models.OrderItem.Category, func.count(models.OrderItem.ItemID))\
        .join(models.Order, models.OrderItem.OrderID == models.Order.OrderID).filter(
        models.Order.ProgressStatus.in_(done_stats),
        func.year(models.Order.ConstructionDate) == year,
        models.Order.CompanyID == current_user.company_id
    ).group_by(models.OrderItem.Category).all()

    cat_c = 0; cat_b = 0; cat_e = 0
    for cat, cnt in cat_stats:
        c_str = (cat or "")
        if "커튼" in c_str: cat_c += cnt
        elif "블라인드" in c_str: cat_b += cnt
        else: cat_e += cnt

    return {
        "result": "success",
        "has_total_perm": has_total_perm,
        "summary": { "total_rev": total_rev, "total_cnt": total_cnt, "cat_c": cat_c, "cat_b": cat_b, "cat_e": cat_e },
        "data_selected": data_selected, "data_next": data_next, "data_current": data_current,
        "years": {"sel": year, "next": next_year, "cur": cur_year}
    }

@router.get("/api/stats/list", response_class=HTMLResponse)
async def get_stats_list(request: Request, year: int, month: int = 0, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id
    ).first()
    
    has_total_perm = (member.RoleName == '대표' or member.Perm_ViewTotal) if member else False
    done_stats = ['작업완료']
    
    sub_items = db.query(
        models.OrderItem.OrderID,
        func.sum(case((models.OrderItem.Category.like('%커튼%'), 1), else_=0)).label('c_cnt'),
        func.sum(case((models.OrderItem.Category.like('%블라인드%'), 1), else_=0)).label('b_cnt'),
        func.sum(case((models.OrderItem.Category.not_like('%커튼%') & models.OrderItem.Category.not_like('%블라인드%'), 1), else_=0)).label('e_cnt')
    ).group_by(models.OrderItem.OrderID).subquery()

    query = db.query(models.Order, sub_items.c.c_cnt, sub_items.c.b_cnt, sub_items.c.e_cnt).outerjoin(
        sub_items, models.Order.OrderID == sub_items.c.OrderID
    ).filter(
        models.Order.ProgressStatus.in_(done_stats),
        func.year(models.Order.ConstructionDate) == year,
        models.Order.CompanyID == current_user.company_id
    )
    
    if month > 0: query = query.filter(func.month(models.Order.ConstructionDate) == month)
    rows = query.order_by(models.Order.ConstructionDate.desc()).all()
    
    if not rows: return "<li class='no-data'>해당 기간 내역이 없습니다.</li>"
    
    results = []
    for row in rows:
        o = row[0]
        results.append({
            "order": o, "final_amt": o.FinalAmount or 0,
            "c_cnt": int(row[1] or 0), "b_cnt": int(row[2] or 0), "e_cnt": int(row[3] or 0)
        })
        
    return templates.TemplateResponse("stats_list.html", {
        "request": request, "results": results, "has_total_perm": has_total_perm
    })

@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, db: Session = Depends(get_db)):
    current_user = await get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    member = db.query(models.CompanyMember).filter(
        models.CompanyMember.UserID == current_user.UserID,
        models.CompanyMember.CompanyID == current_user.company_id
    ).first()
    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "user_name": current_user.Name,
            "user_role": (member.RoleName if member else "직원"),
        }
    )
