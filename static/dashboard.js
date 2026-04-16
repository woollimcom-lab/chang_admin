/* ==========================================================================
   [dashboard.js] 대시보드 UI 동작 스크립트
   ========================================================================== */

// 1. 검색 결과 접기/펼치기
function toggleSearchList(header) {
    var body = header.nextElementSibling;
    if (body.style.display === 'none') {
        body.style.display = 'block';
        header.querySelector('.fa-chevron-down').style.transform = 'rotate(0deg)';
    } else {
        body.style.display = 'none';
        header.querySelector('.fa-chevron-down').style.transform = 'rotate(-90deg)';
    }
}

// 3. 주문 삭제
function deleteOrder(e, orderId) {
    e.stopPropagation();
    if (!confirm('정말로 영구 삭제하시겠습니까?\n복구할 수 없습니다.')) return;

    fetch('/api/order/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'order_id=' + orderId
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'ok') { alert('삭제되었습니다.'); location.reload(); }
        else { alert('삭제 실패: ' + data.msg); }
    })
    .catch(err => alert('오류 발생: ' + err));
}

/*
// 4. 상태 업데이트 시각 효과
function updateStatusLive(element, type, value, orderId) {
    const card = document.getElementById(`card-${orderId}`);
    if (type === 'main') {
        if (['방문상담', '시공예정', 'AS요청'].includes(value)) {
            changeMainStatus(value);
            return;
        }
        element.parentElement.querySelectorAll('.btn-status-main').forEach(b => b.classList.remove('active'));
        element.classList.add('active');
    } else {
        element.classList.toggle('active');
    }

    fetch(`/api/status/update?id=${orderId}&type=${type}&val=${encodeURIComponent(value)}`)
        .then(res => {
            if (res.ok) {
                if (card) {
                    card.style.transition = 'none'; card.style.backgroundColor = '#fff3bf';
                    setTimeout(() => { card.style.transition = 'background-color 0.8s ease'; card.style.backgroundColor = '#fff'; }, 200);
                }
            } else { alert("상태 저장 실패"); location.reload(); }
        })
        .catch(() => alert("네트워크 오류"));
}
        */

// 5. 히스토리 펼치기/접기
function toggleHistoryList(e, element) {
    e.stopPropagation();
    const container = element.parentElement;
    const hiddenList = container.querySelector('.hist-hidden-list');
    const badge = element.querySelector('.hist-badge');

    if (hiddenList) {
        if (hiddenList.style.display === 'none') {
            hiddenList.style.display = 'block';
            if(badge) { badge.style.background = '#4dabf7'; badge.style.color = '#fff'; }
        } else {
            hiddenList.style.display = 'none';
            if(badge) { badge.style.background = '#e9ecef'; badge.style.color = '#495057'; }
        }
    }
}

/* ==========================================================================
   ★ [6] 텍스트 더보기/접기 기능 (좌측 정렬 & 여백 완벽 제거)
   ========================================================================== */
function toggleTextExpand(el) {
    if (window.event) window.event.stopPropagation();

    var txt = el.querySelector('.expand-txt');
    if (!txt) return;

    var isExpanded = el.getAttribute('data-expanded') === 'true';

    if (isExpanded) {
        // ▶ [접기] 원래 상태로 복구
        txt.style.whiteSpace = 'nowrap';
        txt.style.overflow = 'hidden';
        txt.style.textOverflow = 'ellipsis';
        txt.style.marginTop = '0px';       // ★ 뱃지와 텍스트 윗선을 더 바짝 맞춤
        
        // 부모(row) 스타일 복구
        el.setAttribute('data-expanded', 'false');
    } else {
        // ▶ [펼치기] 사장님이 요청하신 "3번째 사진" 스타일 (상단 밀착 + 여백 제거)
        
        // 1. 부모 컨테이너(row) 설정
        el.style.display = 'flex';
        el.style.marginBottom = '0px';      // ★ 하단 여백 완전 제거
        
        // 2. 텍스트 내용 설정
        txt.style.whiteSpace = 'pre-line';  // 줄바꿈 적용
        txt.style.textAlign = 'left';       // ★ 무조건 좌측 정렬
        txt.style.overflow = 'visible';
        txt.style.wordBreak = 'break-all';
        txt.style.marginTop = '-18px';       // ★ 뱃지와 텍스트 윗선을 더 바짝 맞춤
        txt.style.lineHeight = '1.4';       // 줄 간격을 조여서 여백 최소화
        
        el.setAttribute('data-expanded', 'true');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var containers = document.querySelectorAll('.swipe-container');
    
    containers.forEach(function(el) {
        var startX, startY;
        var currentX;
        var isDragging = false;     // 드래그 중인지 여부
        var isScrollLock = false;   // 수직 스크롤로 판정되어 스와이프를 막을지 여부
        var phone = el.getAttribute('data-phone');
        var content = el.querySelector('.swipe-content');
        var bgLeft = el.querySelector('.bg-left');   // 전화 (우측 이동 시)
        var bgRight = el.querySelector('.bg-right'); // 문자 (좌측 이동 시)
        var threshold = 120; // 동작 실행 임계값 (px)

        if (!content) return;

        // 1. 터치 시작
        el.addEventListener('touchstart', function(e) {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            isDragging = false;
            isScrollLock = false; // 초기화
            content.style.transition = 'none'; // 드래그 중엔 즉시 반응
        }, {passive: true});

        // 2. 터치 이동 (핵심 로직)
        el.addEventListener('touchmove', function(e) {
            if (isScrollLock) return; // 수직 스크롤로 판정났으면 무시

            currentX = e.touches[0].clientX;
            var currentY = e.touches[0].clientY;
            var diffX = currentX - startX;
            var diffY = currentY - startY;

            // [최초 판정] 움직임이 시작될 때, 수직인지 수평인지 판단
            if (!isDragging) {
                // Y축 움직임이 X축보다 크면 -> 이건 스크롤이다. 스와이프 잠금.
                if (Math.abs(diffY) > Math.abs(diffX)) {
                    isScrollLock = true;
                    return;
                }
                // X축 움직임이 더 크면 -> 이건 스와이프다.
                isDragging = true;
            }

            // 스와이프 중이라면 브라우저 기본 스크롤 막기 (옵션)
            if (e.cancelable && isDragging) {
                // e.preventDefault(); // 필요 시 주석 해제 (단, passive:true라서 경고 뜰 수 있음)
            }

            // 이동 제한 (화면 밖으로 너무 나가지 않게)
            var moveX = diffX;
            if (moveX > 200) moveX = 200 + (moveX-200)*0.2; // 탄성 효과
            if (moveX < -200) moveX = -200 + (moveX+200)*0.2;

            // 컨텐츠 이동
            content.style.transform = `translateX(${moveX}px)`;
            
            // 흐려지는 효과 (이동 거리에 비례)
            var opacityVal = 1 - (Math.abs(moveX) / 300); 
            if (opacityVal < 0.3) opacityVal = 0.3;
            content.style.opacity = opacityVal;

            // 배경 색상 표시 로직
            if (diffX > 0) { 
                // 오른쪽으로 밈 -> 전화 (Left BG 보임)
                if(bgLeft) bgLeft.style.visibility = 'visible';
                if(bgRight) bgRight.style.visibility = 'hidden';
            } else {
                // 왼쪽으로 밈 -> 문자 (Right BG 보임)
                if(bgLeft) bgLeft.style.visibility = 'hidden';
                if(bgRight) bgRight.style.visibility = 'visible';
            }

        }, {passive: true});

        // 3. 터치 종료
        el.addEventListener('touchend', function(e) {
            if (isScrollLock || !isDragging) return;

            var diffX = currentX - startX;
            
            // 복귀 애니메이션 설정
            content.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.8, 0.5, 1), opacity 0.3s ease';
            content.style.transform = 'translateX(0)';
            content.style.opacity = '1'; // 투명도 복구

            // 임계값 넘었는지 확인 및 동작 수행
            if (Math.abs(diffX) > threshold) {
                // 클릭 이벤트 방지 플래그
                el.setAttribute('data-swiped', 'true');

                if (diffX > 0) {
                    // 전화 걸기
                    if (phone) location.href = 'tel:' + phone;
                } else {
                    // 문자 보내기
                    if (phone) {
                        var cleanPhone = phone.replace(/-/g, "");
                        var smsUrl = (navigator.userAgent.toLowerCase().indexOf("iphone") > -1) 
                                     ? "sms:" + cleanPhone + "&body=" 
                                     : "sms:" + cleanPhone + "?body=";
                        location.href = smsUrl;
                    }
                }
            } else {
                // 조금만 움직였으면 그냥 취소 (원위치 복귀는 위에서 처리됨)
            }

            // 배경 숨김 (애니메이션 끝난 후)
            setTimeout(function() {
                if(bgLeft) bgLeft.style.visibility = 'hidden';
                if(bgRight) bgRight.style.visibility = 'hidden';
            }, 300);
            
            isDragging = false;
        });
    });
});

// 클릭 처리 (스와이프가 아닐 때만 상세 이동)
function handleRowClick(el) {
    if (el.getAttribute('data-swiped') === 'true') {
        el.removeAttribute('data-swiped');
        return;
    }
    var url = el.getAttribute('data-url');
    if (url) location.href = url;
}



    // 1. 직원 목록 불러오기 (권한 데이터 연동)
    async function openStaffManager() {
        document.getElementById('modalStaffList').style.display = 'flex';
        const tbody = document.getElementById('staffListBody');
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px;">로딩중...</td></tr>';

        try {
            const res = await fetch("/api/company/members");
            const data = await res.json();
            
            tbody.innerHTML = '';
            
            if(!data || data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px;">등록된 직원이 없습니다.</td></tr>';
                return;
            }

            data.forEach(m => {
                // 권한 요약 텍스트
                let perms = [];
                if(m.Perm_ViewRevenue) perms.push("매출");
                if(m.Perm_ViewTotal)   perms.push("총금액"); // ★ 화면 표시용
                if(m.Perm_ViewMargin)  perms.push("품목금액");
                if(m.Perm_ManageStaff) perms.push("직원");
                if(m.Perm_EditSchedule) perms.push("일정");
                
                let permTxt = perms.length > 0 ? perms.join(", ") : "<span style='color:#ccc'>권한없음</span>";
                if(m.RoleName === '대표') permTxt = "<span style='color:#4361ee; font-weight:bold;'>모든 권한</span>";

                // ★ 수정 버튼에 데이터 담기 (여기에 Perm_ViewTotal 포함)
                // JSON.stringify를 사용하여 객체 전체를 전달
                let row = `
                    <tr>
                        <td style="padding:12px;">
                            <div style="font-weight:bold; color:#333;">${m.Name}</div>
                            <div style="font-size:0.85em; color:#666;">${m.RoleName || '-'}</div>
                        </td>
                        <td>${m.Phone}</td>
                        <td style="font-size:0.85em; color:#555;">${permTxt}</td>
                        <td style="text-align:center;">
                            ${m.RoleName !== '대표' ? 
                                `<button onclick='openEditModal(${JSON.stringify(m)})' style="border:1px solid #ddd; background:#fff; padding:5px 10px; border-radius:4px; cursor:pointer;">
                                    <i class="fas fa-edit"></i>
                                </button>
                                <button onclick="deleteMember(${m.ID})" style="border:1px solid #ddd; background:#fff; color:#dc3545; padding:5px 10px; border-radius:4px; cursor:pointer; margin-left:5px;">
                                    <i class="fas fa-trash"></i>
                                </button>` 
                            : '<span style="color:#ccc; font-size:0.8em;">관리불가</span>'}
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });

        } catch (err) {
            console.error(err);
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:red;">목록을 불러오지 못했습니다.</td></tr>';
        }
    }

    // 2. 수정 모달 열기 (체크박스 상태 반영)
    function openEditModal(m) {
        // 기본 정보 채우기
        document.getElementById('edit_id').value = m.ID;
        document.getElementById('edit_name').value = m.Name;
        document.getElementById('edit_phone').value = m.Phone;
        document.getElementById('edit_role').value = m.RoleName || '';

        // 권한 체크박스 설정
        document.getElementById('ep_rev').checked = m.Perm_ViewRevenue;
        document.getElementById('ep_exp').checked = m.Perm_ViewExpense;
        document.getElementById('ep_mar').checked = m.Perm_ViewMargin;
        document.getElementById('ep_stat').checked = m.Perm_ViewStats;
        document.getElementById('ep_stf').checked = m.Perm_ManageStaff;
        document.getElementById('ep_sch').checked = m.Perm_EditSchedule;
        
        // ★ [핵심] 총금액 체크박스 설정
        if(document.getElementById('ep_total')) {
            document.getElementById('ep_total').checked = m.Perm_ViewTotal;
        }

        // 외주팀 링크 표시 (외주팀일 경우)
        const linkArea = document.getElementById('editLinkArea');
        const linkInput = document.getElementById('edit_access_link');
        if(m.Type === 'external' && m.AccessKey) {
            linkArea.style.display = 'block';
            linkInput.value = window.location.origin + "/w/" + m.AccessKey;
        } else {
            linkArea.style.display = 'none';
        }

        // 모달 표시
        document.getElementById('modalStaffList').style.display = 'none'; // 목록 닫고
        document.getElementById('modalStaffEdit').style.display = 'flex'; // 수정창 열기
    }

    function closeEditModal() {
        document.getElementById('modalStaffEdit').style.display = 'none';
        document.getElementById('modalStaffList').style.display = 'flex'; // 목록 다시 열기
    }

    // 2. 닫기 함수들
    function closeStaffModal() { document.getElementById('modalStaffList').style.display = 'none'; }
    function closeEditModal() { document.getElementById('modalStaffEdit').style.display = 'none'; }

    // 3. 수정 모달 열기 (데이터 채워넣기)
    function openEditStaff(m) {
        document.getElementById('edit_id').value = m.ID;
        document.getElementById('edit_name').value = m.Name;
        document.getElementById('edit_phone').value = m.Phone;
        document.getElementById('edit_role').value = m.RoleName || "";
        
        // 체크박스 세팅
        document.getElementById('ep_rev').checked = m.Perm_ViewRevenue;
        document.getElementById('ep_exp').checked = m.Perm_ViewExpense;
        document.getElementById('ep_mar').checked = m.Perm_ViewMargin;
        document.getElementById('ep_stat').checked = m.Perm_ViewStats;
        document.getElementById('ep_stf').checked = m.Perm_ManageStaff;
        document.getElementById('ep_sch').checked = m.Perm_EditSchedule;

        // ★ [추가된 부분] 외주팀이면 링크 보여주기
        const linkArea = document.getElementById('editLinkArea');
        const linkInput = document.getElementById('edit_access_link');
        
        if (m.Type === 'external' && m.AccessKey) {
            linkArea.style.display = 'block';
            // 현재 도메인 + /w/ + 키 조합
            linkInput.value = window.location.origin + "/w/" + m.AccessKey;
        } else {
            linkArea.style.display = 'none';
        }
        
        document.getElementById('modalStaffEdit').style.display = 'flex';
    }

    // [추가] 링크 복사 함수
    function copyEditLink() {
        const copyText = document.getElementById("edit_access_link");
        copyText.select();
        document.execCommand("copy");
        alert("링크가 복사되었습니다!");
    }

    // 4. 수정사항 저장 (API 호출)
    async function submitEditStaff(e) {
        e.preventDefault();
        
        // 1. 체크박스 값 가져오기
        const permTotal = document.getElementById('ep_total').checked; // ★ 총금액 체크박스 값

        const reqData = {
            member_id: document.getElementById('edit_id').value,
            name: document.getElementById('edit_name').value,
            phone: document.getElementById('edit_phone').value,
            role_name: document.getElementById('edit_role').value,
            
            // 권한 값들
            perm_revenue: document.getElementById('ep_rev').checked,
            perm_expense: document.getElementById('ep_exp').checked,
            perm_margin:  document.getElementById('ep_mar').checked,
            perm_stats:   document.getElementById('ep_stat').checked,
            perm_staff:   document.getElementById('ep_stf').checked,
            perm_schedule:document.getElementById('ep_sch').checked,
            perm_total:   permTotal // ★ 서버로 전송!
        };

        try {
            const res = await fetch("/api/company/member/update", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(reqData)
            });
            const data = await res.json();
            
            if(data.status === "ok") {
                alert("수정되었습니다.");
                closeEditModal();   // 모달 닫기
                openStaffManager(); // 목록 새로고침
            } else {
                alert("오류: " + data.msg);
            }
        } catch(err) {
            console.error(err);
            alert("서버 통신 오류");
        }
    }

    // 5. 직원 삭제
    async function deleteStaff(id) {
        if(!confirm("정말 이 직원을 삭제하시겠습니까?\n(퇴사 처리)")) return;
        
        const formData = new FormData();
        formData.append("member_id", id);
        
        const res = await fetch("/api/company/member/delete", { method:"POST", body:formData });
        const data = await res.json();
        
        if(data.status === "ok") {
            alert("삭제되었습니다.");
            openStaffManager(); // 목록 새로고침
        } else {
            alert(data.msg);
        }
    }

    document.addEventListener("DOMContentLoaded", function() {
        var now = new Date();
        var offset = now.getTimezoneOffset() * 60000;
        var localIso = new Date(now - offset).toISOString().slice(0, 16);
        var dateInput = document.getElementById('newRequestDate');
        if(dateInput) {
            dateInput.value = localIso;
        }
    });

    function handleLogout() {
        document.cookie = "access_token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;";
        location.href = "/login";
    }

    // 1. 문서 로드 시 실행 (기존 코드 유지)
    document.addEventListener("DOMContentLoaded", function() {
        var now = new Date();
        var offset = now.getTimezoneOffset() * 60000;
        var localIso = new Date(now - offset).toISOString().slice(0, 16);
        var dateInput = document.getElementById('newRequestDate');
        if(dateInput) {
            dateInput.value = localIso;
        }
    });

    // 2. [추가] 신규 등록 모달 열기 함수 (이게 없어서 안 눌렸음)
    function openOrderModal() {
        // 날짜 필드에 현재 시간 자동 입력
        var now = new Date();
        var offset = now.getTimezoneOffset() * 60000;
        var localIso = new Date(now - offset).toISOString().slice(0, 16);
        var dateInput = document.getElementById('newRequestDate');
        if(dateInput) {
            dateInput.value = localIso;
        }
        
        // 모달 표시
        document.getElementById('newModal').style.display = 'flex';
    }

    // 3. 대시보드 캘린더 버튼
    function toggleDashCalendar() {
        if (typeof openCommonCalendar === 'function') {
            openCommonCalendar(function(info) {
                // 달력 날짜 클릭 시 해당 날짜로 대시보드 필터링
                location.href = '/dashboard?dash_Date=' + info.dateStr;
            });
        } else {
            alert('캘린더 기능을 불러오는 중입니다. 잠시 후 다시 시도해주세요.');
        }
    }

/* ==========================================
   [성능 최적화] AJAX 필터 & 자동 업데이트 & 신규등록
   ========================================== */

// 1. 필터 클릭 시 리스트만 부분 로딩 (새로고침 X)
async function loadFilterList(stat, btnElement) {
    // URL 변경 (기록 남기기)
    const newUrl = stat ? `/dashboard?filterStat=${encodeURIComponent(stat)}` : '/';
    window.history.pushState(null, '', newUrl);

    // 버튼 활성화 UI 즉시 변경
    document.querySelectorAll('.sb-item').forEach(el => el.classList.remove('active'));
    if(btnElement) btnElement.classList.add('active');

    // 로딩 표시
    const container = document.getElementById('mainDashboardGrid');
    if(!container) return location.href = newUrl; // 안전장치
    container.style.opacity = '0.5';

    try {
        const res = await fetch(newUrl);
        const text = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'text/html');
        
        // 서버에서 받은 페이지 중 '리스트 영역'만 쏙 빼서 교체
        const newContent = doc.getElementById('mainDashboardGrid').innerHTML;
        container.innerHTML = newContent;
        
        // D-Day 배지 등 스크립트 재실행
        if(typeof renderDdayBadges === 'function') renderDdayBadges();
        if(typeof initCardToggles === 'function') initCardToggles(); // ★ [추가] 새로 바뀐 카드들에 마법 다시 걸기!
        
    } catch (err) {
        console.error(err);
        location.href = newUrl; // 에러 시 그냥 이동
    } finally {
        container.style.opacity = '1';
    }
}

async function submitNewOrder(e) {
    if (e) e.preventDefault();
    
    console.log("🚀 [JS] 신규 접수 버튼 클릭됨");

    const form = document.getElementById('formNewOrder');
    const formData = new FormData(form);
    const submitBtn = form.querySelector('button[type="submit"]');

    // [Debug] 전송되는 데이터 눈으로 확인하기
    console.log("📦 [JS] 전송할 데이터 목록:");
    for (let [key, value] of formData.entries()) {
        console.log(`   👉 ${key}: ${value}`);
    }

    try {
        submitBtn.disabled = true;

        const res = await fetch('/create-order', { 
            method: 'POST', 
            body: formData 
        });
        
        console.log(`📡 [JS] 서버 응답 상태: ${res.status}`);
        const result = await res.json();
        console.log("📩 [JS] 서버 응답 내용:", result);

        if (res.ok && result.status === "ok") {
            alert("등록되었습니다.");
            document.getElementById('newModal').style.display = 'none';
            form.reset();
            location.reload(); 
        } else {
            alert("등록 실패: " + (result.msg || "알 수 없는 오류"));
        }
    } catch (err) {
        console.error("❌ [JS] 통신 에러:", err);
        alert("서버와 연결할 수 없습니다.");
    } finally {
        submitBtn.disabled = false;
    }
}

/* ==========================================
   [Dashboard.js] 부분 업데이트 로직 (최적화)
   ========================================== */
async function fetchAndPatchOrder(id) {
    if (!id) return;
    
    try {
        // 서버 API 호출
        const res = await fetch(`/api/order/summary/${id}`);
        if (!res.ok) return; // 실패 시 조용히 종료
        const data = await res.json();

        // 업데이트할 카드 찾기
        const card = document.getElementById('card-' + id);
        if (!card) return; // 화면에 카드가 없으면 패스 (예: 필터링된 상태)

        console.log(`♻️ 카드 업데이트: ${id}`, data);

        // --- [A] 상단 상태/배지 영역 재구성 ---
        const badgeArea = card.querySelector('.js-badge-area');
        if (badgeArea) {
            // 기존 내용 초기화 (싹 비우고 새로 그림)
            badgeArea.innerHTML = '';

            // 1. 메인 상태 배지
            let mainSpan = document.createElement('span');
            mainSpan.className = 'main-bdg';
            mainSpan.innerText = data.status;
            mainSpan.style.cssText = `background:${data.stat_bg}; color:#fff; padding:3px 6px; border-radius:4px; font-size:0.85rem; font-weight:bold; letter-spacing:-0.5px; margin-right:4px;`;
            badgeArea.appendChild(mainSpan);

            // 2. 서브 배지 생성 헬퍼
            const addSubBadge = (text, color) => {
                let s = document.createElement('span');
                s.innerText = text;
                s.style.cssText = `background:${color}; color:#fff; padding:3px 5px; border-radius:8px; font-size:0.75rem; font-weight:500; margin-right:2px;`;
                badgeArea.appendChild(s);
            };

            if (data.badges.show_unordered_badge) addSubBadge('주문누락', '#ff9500');
            if (data.badges.ordered === 'Y') addSubBadge('주문', '#3cce10');
            if (data.badges.received === 'Y') addSubBadge('수령', '#4e98fa');
            if (data.badges.paid === '입금완료') addSubBadge('입금', '#eb4646');
            if (data.badges.waiting === 'Y') addSubBadge('대기', '#9775fa');
            if (data.badges.hold === 'Y') addSubBadge('보류', '#868e96');
        }

        // --- [B] 날짜 및 시간 ---
        const dateEl = card.querySelector('.js-date');
        const timeEl = card.querySelector('.js-time');
        if (dateEl) dateEl.innerText = data.date_str || "";
        if (timeEl) timeEl.innerText = data.time_str || "";

        // --- [C] 고객 정보 ---
        const nameEl = card.querySelector('.js-name');
        if (nameEl) nameEl.innerText = data.name;

        const addrEl = card.querySelector('.js-txt');
        if (addrEl) {
            // 주소가 있으면 주소, 없으면 연락처 표시 (HTML 로직과 동일)
            addrEl.innerText = data.address || data.phone;
        }

        // --- [D] 금액 ---
        const priceEl = card.querySelector('.js-price');
        if (priceEl) {
            // 권한 때문에 가격 요소가 아예 없을 수도 있음
            priceEl.innerHTML = data.price + '<span style="font-size:0.9rem; color:#333; margin-left:2px;"></span>';
        }

        // --- [E] 품목 리스트 ---
        const listEl = card.querySelector('.js-item-list');
        if (listEl) {
            listEl.innerHTML = "";
                if (data.item_summary) {
                    const itemArea = card.querySelector('.js-target-item-list');
                    if (itemArea) {
                        itemArea.innerHTML = ""; // 기존 비우기
                        
                        // 콤마로 분리해서 태그 생성
                        data.item_summary.split(',').forEach(txt => {
                            if (!txt.trim()) return;
                            
                            let div = document.createElement('div');
                            div.style.cssText = "border:1px solid #ced4da; border-radius:6px; padding:2px 5px; background:#fff; color:#495057; font-size:0.9rem; font-weight:500;";
                            div.innerText = txt.trim();
                            itemArea.appendChild(div);
                        });
                        
                        // 감싸는 부모 영역이 숨겨져 있을 수 있으므로 보이게 처리
                        const itemWrapper = card.querySelector('.js-item-area');
                        if (itemWrapper) itemWrapper.style.display = 'flex';
                    }
                }
        }

        // --- [F] 메모 / 현장 / 담당자 / 기록 (display 제어) ---
        
        // 담당자
        const mgrBox = card.querySelector('.js-manager-box');
        const mgrTxt = card.querySelector('.js-manager');
        if (mgrBox && mgrTxt) {
            mgrTxt.innerText = data.manager || "";
            mgrBox.style.display = data.manager ? 'flex' : 'none';
        }

        // 현장 메모
        const siteBox = card.querySelector('.js-site-memo-box');
        const siteTxt = card.querySelector('.js-site-txt');
        if (siteBox && siteTxt) {
            // [설치면] 메모 내용
            let fullSite = (data.site_surface ? `[${data.site_surface}] ` : "") + (data.site_info || "");
            siteTxt.innerText = fullSite;
            siteBox.style.display = fullSite.trim() ? 'flex' : 'none';
        }

        // 일반 메모
        const genBox = card.querySelector('.js-gen-memo-box');
        const genTxt = card.querySelector('.js-gen-txt');
        if (genBox && genTxt) {
            genTxt.innerText = data.memo || "";
            genBox.style.display = (data.memo && data.memo.trim()) ? 'flex' : 'none';
        }

        // [dashboard.js 수정됨] 히스토리 영역 UI 그리기
        const histBox = card.querySelector('.js-hist-box');
        
        if (histBox) {
            histBox.innerHTML = ""; // 초기화
            const logs = data.history_list || [];

            if (logs.length > 0) {
                histBox.style.display = 'block';
                
                // 1. 컨테이너 생성
                const container = document.createElement('div');
                container.className = 'hist-container';

                // 2. 트리거(헤더) 생성
                const trigger = document.createElement('div');
                trigger.className = 'hist-trigger';
                trigger.style.cssText = `display:flex; justify-content:space-between; align-items:center; background:#fff; border:1px solid #dfdfdf; border-radius:8px; padding:6px 10px; cursor:${logs.length > 1 ? 'pointer' : 'default'};`;
                trigger.onclick = function(e) { toggleHistoryList(e, this); };

                // 2-1. 좌측 내용 (아이콘 + 최근글)
                const leftDiv = document.createElement('div');
                leftDiv.style.cssText = "display:flex; align-items:center; flex:1; overflow:hidden;";
                leftDiv.innerHTML = `
                    <span style="background:#4dabf7; color:#fff; font-size:0.75rem; font-weight:bold; padding:2px 6px; border-radius:4px; margin-right:8px; flex-shrink:0;">
                        <i class="fas fa-history"></i> 기록
                    </span>
                    <span style="font-size:0.85rem; color:#555; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1;">
                        ${logs[0]}
                    </span>
                `;
                trigger.appendChild(leftDiv);

                // 2-2. 뱃지 (2개 이상일 때)
                if (logs.length > 1) {
                    const badge = document.createElement('span');
                    badge.className = 'hist-badge';
                    badge.innerText = `+${logs.length - 1}`;
                    badge.style.cssText = "background:#e9ecef; color:#495057; font-size:0.75rem; font-weight:bold; padding:2px 8px; border-radius:12px; margin-left:8px; flex-shrink:0;";
                    trigger.appendChild(badge);
                }
                container.appendChild(trigger);

                // 3. 숨겨진 리스트 (2개 이상일 때)
                if (logs.length > 1) {
                    const hiddenDiv = document.createElement('div');
                    hiddenDiv.className = 'hist-hidden-list';
                    hiddenDiv.style.cssText = "display:none; background:#f8f9fa; border:1px solid #eee; border-top:none; border-radius:0 0 8px 8px; padding:8px 10px; margin-top:-2px;";
                    
                    for(let i=1; i<logs.length; i++) {
                        const row = document.createElement('div');
                        row.innerText = "• " + logs[i];
                        row.style.cssText = "font-size:0.85rem; color:#666; padding:4px 0; border-bottom:1px dashed #e9ecef; line-height:1.4;";
                        hiddenDiv.appendChild(row);
                    }
                    container.appendChild(hiddenDiv);
                }

                histBox.appendChild(container);
            } else {
                histBox.style.display = 'none';
            }
        }

        // --- [G] 시각적 피드백 (깜빡임 효과) ---
        card.style.transition = 'background-color 0.5s ease';
        card.style.backgroundColor = '#fff3bf'; // 노란색으로 반짝
        setTimeout(() => {
            card.style.backgroundColor = '#fff'; // 다시 흰색으로 복귀
        }, 600);

    } catch (e) {
        console.error("Partial Update Error:", e);
    }
}

/* ==========================================
   [Dashboard.js] 초고속 클라이언트 업데이트
   ========================================== */
/* [dashboard.js] 타겟 명찰 기반 정밀 업데이트 */

window.addEventListener('pageshow', function(event) {
    // 1. 릴레이 도착 확인
    sessionStorage.removeItem('is_returning_to_dashboard');

    // 2. 데이터 확인
    const payloadStr = sessionStorage.getItem('dashboard_update_payload');
    if (payloadStr) {
        try {
            const data = JSON.parse(payloadStr);
            console.log(`🚀 타겟 명찰 업데이트: ID ${data.id}`);
            updateDashboardCard(data);
            sessionStorage.removeItem('dashboard_update_payload');
        } catch (e) {
            console.error("Payload Error:", e);
        }
    }
});

/* [dashboard.js] 대시보드 카드 실시간 업데이트 함수 (에러 수정 버전) */
function updateDashboardCard(data) {
    const card = document.getElementById('card-' + data.id);
    if (!card) return;

    // -----------------------------------------------------------
    // [1] 상태 (Status) - 메인/서브 분리 처리
    // -----------------------------------------------------------
    
    // (A) 메인 상태 (js-target-status)
    const mainStatusEl = card.querySelector('.js-target-status');
    const statusText = data["js-target-status"] || "";
    
    if (mainStatusEl) {
        mainStatusEl.innerText = statusText; 
        
        // 배경색 로직
        let bg = "#6f8672"; 
        if (statusText.includes("AS")) bg = "#9e1dbe";
        else if (statusText.includes("방문")) bg = "#39b114";
        else if (["시공", "주문", "수령"].some(s => statusText.includes(s))) bg = "#1472ec";
        else if (statusText.includes("완료")) bg = "#333333";
        else if (statusText.includes("견적")) bg = "#fd7e14";
        
        mainStatusEl.style.background = bg;
    }

    // (B) 서브 배지 (주문, 수령 등)
    const subBadges = data["js-target-sub-badges"];
    if (subBadges && Array.isArray(subBadges)) {
        const subArea = card.querySelector('.js-target-sub-badges');
        if (subArea) {
            subArea.innerHTML = ""; 
            subBadges.forEach(badge => {
                let s = document.createElement('span');
                s.innerText = badge.text;
                s.style.cssText = `background:${badge.color}; color:#fff; padding:3px 5px; border-radius:8px; font-size:0.75rem; font-weight:500; margin-right:2px;`;
                subArea.appendChild(s);
            });
        }
    }

    // -----------------------------------------------------------
    // [2] 기본 정보 (날짜, 이름, 주소, 금액)
    // -----------------------------------------------------------
    
    const dateEl = card.querySelector('.js-target-date');
    const timeEl = card.querySelector('.js-target-time');
    if (dateEl) dateEl.innerText = data["js-target-date"] || "";
    if (timeEl) timeEl.innerText = data["js-target-time"] || "";

    const nameEl = card.querySelector('.js-target-name');
    if (nameEl) nameEl.innerText = data["js-target-name"] || nameEl.innerText;

    const addrEl = card.querySelector('.js-target-address');
    if (addrEl) addrEl.innerText = data["js-target-address"] || "";

    const priceEl = card.querySelector('.js-target-price');
    if (priceEl && data["js-target-price"]) priceEl.innerText = data["js-target-price"];

    const mgrBox = card.querySelector('.js-target-manager-box');
    const mgrEl = card.querySelector('.js-target-manager');
    if (mgrBox && mgrEl) {
        mgrEl.innerText = data["js-target-manager"] || "";
        mgrBox.style.display = data["js-target-manager"] ? 'flex' : 'none';
    }

    // -----------------------------------------------------------
    // [3] 메모 영역 (일반 / 현장)
    // -----------------------------------------------------------

    const siteBox = card.querySelector('.js-target-site-box');
    const siteTxt = card.querySelector('.js-target-site-text');
    const siteVal = data["js-target-site-text"] || "";
    if (siteBox && siteTxt) {
        siteTxt.innerText = siteVal;
        siteBox.style.display = siteVal.trim() ? 'flex' : 'none';
    }

    const memoBox = card.querySelector('.js-target-memo-box');
    const memoTxt = card.querySelector('.js-target-memo-text');
    const memoVal = data["js-target-memo-text"] || "";
    if (memoBox && memoTxt) {
        memoTxt.innerText = memoVal;
        memoBox.style.display = memoVal.trim() ? 'flex' : 'none';
    }

    // -----------------------------------------------------------
    // [4] 히스토리 영역 (리스트 업데이트)
    // -----------------------------------------------------------
    const histBox = card.querySelector('.js-target-hist-box');
    const histListEl = card.querySelector('.js-target-hist-list');
    const logs = data["js-target-hist-list"] || [];

    if (histBox && histListEl) {
        histListEl.innerHTML = ""; 
        if (logs.length > 0) {
            const triggerDiv = document.createElement('div');
            triggerDiv.className = "hist-trigger";
            triggerDiv.style.cssText = `display:flex; justify-content:space-between; align-items:flex-start; background:#fff; border:1px solid #dfdfdf; border-radius:8px; cursor:${logs.length > 1 ? 'pointer' : 'default'};`;
            
            triggerDiv.innerHTML = `
                <div style="display:flex; align-items:center; flex:1; overflow:hidden;">
                    <span style="background:#4dabf7; color:#fff; font-size:0.75rem; font-weight:bold; padding:2px 6px; border-radius:4px; margin-right:8px; flex-shrink:0; white-space:nowrap;">
                        <i class="fas fa-history"></i> 기록
                    </span>
                    <span class="expand-txt" style="font-size:0.85rem; color:#555; line-height:1.4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1;">
                        ${logs[0]}
                    </span>
                </div>
                ${logs.length > 1 ? `<span class="hist-badge" style="background:#e9ecef; color:#495057; font-size:0.75rem; font-weight:bold; padding:2px 8px; border-radius:12px; margin-left:8px; flex-shrink:0;">+${logs.length - 1}</span>` : ''}
            `;

            if (logs.length > 1) {
                const hiddenDiv = document.createElement('div');
                hiddenDiv.className = "hist-hidden-list";
                hiddenDiv.style.cssText = "display:none; background:#f8f9fa; border:1px solid #eee; border-top:none; border-radius:0 0 8px 8px; padding:8px 10px; margin-top:-2px;";

                logs.slice(1).forEach(log => {
                    const item = document.createElement('div');
                    item.innerText = "• " + log;
                    item.style.cssText = "font-size:0.85rem; color:#666; padding:4px 0; border-bottom:1px dashed #e9ecef; line-height:1.4;";
                    hiddenDiv.appendChild(item);
                });

                triggerDiv.onclick = (e) => {
                    e.stopPropagation();
                    hiddenDiv.style.display = hiddenDiv.style.display === "none" ? "block" : "none";
                };
                histListEl.appendChild(triggerDiv);
                histListEl.appendChild(hiddenDiv);
            } else {
                histListEl.appendChild(triggerDiv);
            }
            histBox.style.display = 'block';
        } else {
            histBox.style.display = 'none';
        }
    }

    // [5] 변경 알림 효과 (노란색 반짝임)
    card.style.transition = 'none';
    card.style.backgroundColor = '#fff3bf';
    setTimeout(() => {
        card.style.transition = 'background-color 0.8s ease';
        card.style.backgroundColor = '#fff';
    }, 200);
}