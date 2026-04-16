/* ==========================================================================
   [view_api.js] 서버 통신 (Fetch)
   ========================================================================== */
// 1. 공통 비동기 전송 함수 (세션 만료 자동 튕김 적용)
async function sendBackgroundRequest(url, formData, silent = false) {
    try {
        const response = await fetch(url, { method: 'POST', body: formData });
        
        // ★ 쿠키(세션)가 없거나 만료되었을 때 자동 로그인 페이지 이동
        if (response.status === 401 || response.status === 403) {
            alert("세션이 만료되었습니다. 다시 로그인해주세요.");
            window.location.href = '/login';
            return false;
        }
        
        if (!response.ok) throw new Error("fail");
        return true;
    } catch (e) { 
        console.error("통신 오류:", e);
        if (!silent) alert("저장에 실패했습니다. 네트워크를 확인해주세요.");
        return false; 
    }
}

// 2. 고객/주문 정보 실시간 저장 (순차 실행으로 충돌 방지)
async function saveInfoLive(orderId) {
    // ID 없으면 중단 (orderId가 undefined일 경우 대비 전역변수 g_orderId 사용)
    const targetId = orderId || g_orderId; 
    if(!targetId) return;

    // 화면 텍스트 즉시 업데이트 (사용자 경험 향상)
    const nameEl = document.getElementById('customer-name');
    const phoneEl = document.getElementById('customer-phone');
    const addrEl = document.getElementById('customer-addr');
    const memoEl = document.getElementById('live-memo');
    const inflowRouteEl = document.getElementById('inflow-route');
    const inflowDetailEl = document.getElementById('inflow-detail');
    const asReasonEl = document.getElementById('as-reason');
    const asResponsibilityEl = document.getElementById('as-responsibility');
    const asChargeTypeEl = document.getElementById('as-charge-type');
    const asCostEl = document.getElementById('as-cost');
    const asNoteEl = document.getElementById('as-note');

    if (nameEl) document.querySelectorAll('.cust-name, .m-name').forEach(el => el.innerText = nameEl.value);
    if (phoneEl) document.querySelectorAll('.info-phone').forEach(el => el.innerHTML = `<i class="fas fa-mobile-alt"></i> ${phoneEl.value}`);
    if (addrEl) document.querySelectorAll('.info-addr').forEach(el => el.innerHTML = `<i class="fas fa-map-marker-alt"></i> ${addrEl.value}`);

    const formData = new FormData();
    formData.append('id', targetId);
    formData.append('order_id', targetId); // API 호환성
    
    if(memoEl) formData.append('memo', memoEl.value);
    if(nameEl) formData.append('customer_name', nameEl.value);
    if(phoneEl) formData.append('phone', phoneEl.value);
    if(addrEl) formData.append('address', addrEl.value);
    if(inflowRouteEl) formData.append('inflow_route', inflowRouteEl.value);
    if(inflowDetailEl) formData.append('inflow_detail', inflowDetailEl.value);
    if(asReasonEl) formData.append('as_reason', asReasonEl.value);
    if(asResponsibilityEl) formData.append('as_responsibility', asResponsibilityEl.value);
    if(asChargeTypeEl) formData.append('as_charge_type', asChargeTypeEl.value);
    if(asCostEl) formData.append('as_cost', asCostEl.value);
    if(asNoteEl) formData.append('as_note', asNoteEl.value);

    // 외주팀 키 처리
    const extKey = document.getElementById('extAccessKey')?.value;
    if(extKey) formData.append('access_key', extKey);

    // ★ [핵심 수정] 순차 실행 (await) 및 에러 무시 (true)
    try {
        const isUpdated = await sendBackgroundRequest('/api/order/update-info', formData, true);
        const isSaved = await sendBackgroundRequest('/api/order/save-info', formData, true);
        if (isUpdated && isSaved) {
            if (typeof syncInflowGuideState === 'function') syncInflowGuideState();
            const infoModal = document.getElementById('infoModal');
            const isInfoModalOpen = infoModal && infoModal.style.display !== 'none' && window.getComputedStyle(infoModal).display !== 'none';
            if (isInfoModalOpen) {
                if (typeof closeInfoModal === 'function') closeInfoModal();
                if (typeof triggerModalSuccessFeedback === 'function') triggerModalSuccessFeedback();
            }
        }
        if (!isUpdated || !isSaved) return;
        showToast("저장되었습니다.");
    } catch (e) {
        console.log("실시간 저장 중 충돌 무시");
    }
}

// 3. 결제 상태 업데이트 (즉시 저장)
async function updatePaymentLive(orderId) {
    const clean = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;
    const normalizeDiscount = (discount, isVat) => {
        const raw = parseFloat(discount) || 0;
        return isVat ? Math.round(raw / 1.1) : raw;
    };

    const totalInput = document.getElementById('raw-total-amt');
    const discountInput = document.getElementById('inp-discount');
    const depositInput = document.getElementById('inp-deposit');
    const vatCheck = document.getElementById('chk-vat');

    if (!totalInput) return;

    // 값 가져오기
    const total = clean(totalInput.value); 
    const discount = clean(discountInput?.value);
    const deposit = clean(depositInput?.value);
    const vatYn = vatCheck?.checked;
    const normalizedDiscount = normalizeDiscount(discount, vatYn);

    // 계산
    let supply = total - normalizedDiscount; 
    if (supply < 0) supply = 0;
    let vat = vatYn ? Math.round(supply * 0.1) : 0;
    
    let finalAmt = supply + vat;    
    let balance = finalAmt - deposit; 

    // 포맷팅
    const fmtTotal = finalAmt.toLocaleString();
    const fmtBalance = balance.toLocaleString();

    // 화면 반영
    if(document.getElementById('live-price')) document.getElementById('live-price').innerText = fmtTotal;
    if(document.getElementById('mobileDispFinal')) document.getElementById('mobileDispFinal').innerText = fmtTotal + "원";
    if(document.getElementById('dispFinal')) document.getElementById('dispFinal').innerText = fmtBalance + "원";
    if(document.getElementById('dispVat')) document.getElementById('dispVat').innerText = vatYn ? vat.toLocaleString() + "원" : "별도";

    // 서버 저장
    const formData = new FormData();
    formData.append('id', orderId);
    formData.append('discount', normalizedDiscount);
    formData.append('deposit', deposit);
    formData.append('vat', vatYn ? 'true' : 'false');
    formData.append('final_amount', finalAmt); 

    return await sendBackgroundRequest('/api/order/save-info', formData);
}

// 4. 결제 저장 버튼 클릭 시
async function savePaymentLive() {
    const oid = document.getElementById('srv-order-id')?.value;
    if (!oid) return;
    const ok = await updatePaymentLive(parseInt(oid));
    if (ok && typeof triggerModalSuccessFeedback === 'function') {
        triggerModalSuccessFeedback();
    }
}

// 5. 메모 추가
async function addHistoryLive(orderId) {
    const input = document.getElementById('new-history-input');
    const content = input.value.trim();
    if (!content) return;

    const list = document.querySelector('.history-list'); 
    const now = new Date();
    const dateStr = `${now.getFullYear()}-${(now.getMonth()+1)}-${now.getDate()} ${now.getHours()}:${now.getMinutes()}`;
    
    const html = `
        <div class="memo-item history-row" data-type="메모">
            <div class="memo-top">
                <div class="memo-meta">
                    <span class="badge-type type-memo">메모</span>
                    <span class="author-name">방금</span>
                    <span class="reg-date">${dateStr}</span>
                </div>
            </div>
            <div class="memo-text">${content}</div>
        </div>`;
    
    if(list) {
        if(list.innerText.includes("기록이 없습니다")) list.innerHTML = "";
        list.insertAdjacentHTML('afterbegin', html);
    }
    input.value = "";

    const formData = new FormData();
    formData.append('order_id', orderId);
    formData.append('log_type', '메모');
    formData.append('contents', content);
    
    const ok = await sendBackgroundRequest('/api/history/add', formData);
    if (ok && typeof triggerModalSuccessFeedback === 'function') {
        triggerModalSuccessFeedback();
    }
}

// 6. 메모 삭제
async function deleteHistoryLive(historyId, btn) {
    if (!confirm('삭제하시겠습니까?')) return;
    const formData = new FormData();
    formData.append('history_id', historyId);
    formData.append('order_id', g_orderId); 
    const key = document.getElementById('extAccessKey')?.value;
    if (key) formData.append('access_key', key);

    try {
        const response = await fetch('/api/history/delete', { method: 'POST', body: formData });
        if (response.ok) {
            const row = btn.closest('.history-row');
            if (row) {
                row.style.opacity = '0';
                row.style.transition = '0.3s';
                setTimeout(() => row.remove(), 300);
            }
            showToast("기록이 삭제되었습니다.");
        } else { alert("삭제에 실패했습니다. 다시 시도해 주세요."); }
    } catch (e) { console.error("삭제 중 네트워크 오류:", e); alert("네트워크 연결을 확인해 주세요."); }
}


// ✅ 1. 품목 사진 다중 업로드 함수 (파일명 지정을 위해 item_label 추가 전송)
async function uploadItemPhotoFile(itemId, stage, fileList){
    const oid = (typeof g_orderId !== 'undefined') ? g_orderId : (document.getElementById('srv-order-id')?.value);
    if(!oid) throw new Error("주문번호를 찾을 수 없습니다.");
    if(!itemId) throw new Error("itemId가 없습니다.");
    if(!fileList || fileList.length === 0) throw new Error("파일이 없습니다.");

    const photo_type = (stage === 'before') ? 'before' : (stage === 'during' ? 'during' : 'after');

    // ★ [추가] 화면에 있는 '위치 + 제품명' 글자 긁어오기 (백엔드 파일명 리네이밍용)
    const map = typeof buildItemLabelMap === 'function' ? buildItemLabelMap() : {};
    const itemLabel = map[itemId] || `품목_${itemId}`;

    const form = new FormData();
    form.append('order_id', String(oid));
    form.append('item_id', String(itemId));
    form.append('photo_type', photo_type);
    form.append('item_label', itemLabel); // ★ 서버로 이름표 전달
    
    for(let i=0; i<fileList.length; i++) {
        form.append('files', fileList[i]); 
    }

    const extKey = document.getElementById('extAccessKey')?.value;
    if(extKey) form.append('access_key', extKey);

    const res = await fetch('/api/photo/upload-item', { method:'POST', body: form });
    const raw = await res.text();
    let data = null;
    try{ data = JSON.parse(raw); }catch(e){}

    if(!res.ok){
        const msg = data?.msg || data?.detail || raw?.slice(0,200) || `HTTP ${res.status}`;
        throw new Error("업로드 실패: " + msg);
    }
    return data || {status:'ok'};
}


// ✅ 2. 갤러리 화면 렌더링 (품목 이름 표시 적용)
async function loadPhotos() {
    const container = document.getElementById('photoGallery');
    if(!container) return;

    try {
        const oid = (typeof g_orderId !== 'undefined') ? g_orderId : document.getElementById('srv-order-id')?.value;
        if(!oid) return;

        const res = await fetch(`/api/photo/list/${oid}`);
        let photos = await res.json();
        const normalizePhotoStage = (fileType) => {
            const raw = String(fileType || '').trim().toLowerCase();
            if (raw === 'before' || raw.includes('before')) return 'before';
            if (raw === 'during' || raw.includes('during')) return 'during';
            if (raw === 'after' || raw.includes('after')) return 'after';
            return '';
        };
        const getPhotoStageKey = (stageSet) => {
            const orderedStages = ['before', 'during', 'after'].filter((stage) => stageSet.has(stage));
            return orderedStages.join('-') || 'none';
        };
        const buildItemPhotoSummary = (photoRows) => {
            const summaryMap = new Map();
            (photoRows || []).forEach((p) => {
                const itemId = parseInt(p.ItemID || 0, 10);
                if (!Number.isFinite(itemId) || itemId <= 0) return;
                const stage = normalizePhotoStage(p.FileType);
                let summary = summaryMap.get(itemId);
                if (!summary) {
                    summary = { count: 0, stages: new Set() };
                    summaryMap.set(itemId, summary);
                }
                summary.count += 1;
                if (stage) summary.stages.add(stage);
            });
            return summaryMap;
        };
        const refreshItemPhotoTriggers = (photoRows) => {
            const summaryMap = buildItemPhotoSummary(photoRows);
            document.querySelectorAll('[data-item-photo-trigger][data-item-id]').forEach((el) => {
                const itemId = parseInt(el.getAttribute('data-item-id') || '0', 10);
                const summary = summaryMap.get(itemId);
                const photoCount = summary?.count || 0;
                const stageKey = summary ? getPhotoStageKey(summary.stages) : 'none';
                el.classList.toggle('has-photo', photoCount > 0);
                el.setAttribute('data-photo-stage', stageKey);
                el.setAttribute('data-photo-count', String(photoCount));
                const countEl = el.querySelector('.item-photo-count');
                if (countEl) {
                    countEl.textContent = String(photoCount);
                    countEl.hidden = photoCount <= 0;
                }
            });
        };
        
        if(photos.length === 0) {
            refreshItemPhotoTriggers([]);
            container.innerHTML = '<div style="padding:40px 10px; text-align:center; color:#adb5bd;"><i class="fas fa-camera" style="font-size:30px; margin-bottom:10px; display:block;"></i>등록된 현장 사진이 없습니다.</div>';
            return;
        }

        // ★ [추가] 화면에서 '위치 + 제품명' 맵핑 데이터 가져오기
        const itemLabelMap = typeof buildItemLabelMap === 'function' ? buildItemLabelMap() : {};

        // 시공전 -> 시공중 -> 시공후 순서로 정렬
        const stageWeight = { 'before': 1, 'during': 2, 'after': 3 };
        photos.sort((a, b) => {
            const wA = stageWeight[normalizePhotoStage(a.FileType)] || 99;
            const wB = stageWeight[normalizePhotoStage(b.FileType)] || 99;
            if(wA === wB) return b.PhotoID - a.PhotoID; 
            return wA - wB;
        });

        window.__galleryPhotos = photos; 
        refreshItemPhotoTriggers(photos);

        let html = '<div class="photo-grid">';
        photos.forEach((p, index) => {
            const stageMap = { 'before': '시공 전', 'during': '시공 중', 'after': '시공 후' };
            const stageType = normalizePhotoStage(p.FileType);
            const stageStr = stageMap[stageType] || p.FileType;
            
            // ★ [핵심] 품목 ID를 기반으로 화면에서 긁어온 '위치 + 제품명' 매칭
            const itemLabel = itemLabelMap[p.ItemID] || (p.cate1 || p.ProductName || '주문 공통 사진');

            html += `
                <div class="photo-card">
                    <button type="button" class="photo-del-btn" onclick="deletePhoto(${p.PhotoID})" title="삭제"><i class="fas fa-trash-alt"></i></button>
                    <img src="${p.FilePath}" alt="${p.FileName}" onclick="openLightbox(${index})" loading="lazy">
                    <div class="photo-card-info">
                        <span class="photo-tag">${stageStr}</span>
                        <div style="color:#212529; margin-top:4px; font-weight:900; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${itemLabel}">
                            ${itemLabel}
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch(err) {
        console.error("사진 로딩 오류:", err);
        container.innerHTML = '<div style="color:red; text-align:center;">사진을 불러오지 못했습니다.</div>';
    }
}

async function uploadItemPhotos(itemId, type='completion') {
    if(!itemId) { alert("품목 정보를 찾을 수 없습니다."); return; }
    if(!g_orderId) { alert("주문 번호를 찾을 수 없습니다."); return; }

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;

    input.onchange = async function() {
        if(!input.files || input.files.length === 0) return;

        const formData = new FormData();
        formData.append('order_id', g_orderId);
        formData.append('item_id', itemId);
        formData.append('photo_type', type);

        const extKey = document.getElementById('extAccessKey');
        if(extKey) formData.append("access_key", extKey.value);

        try {
            const res = await fetch('/api/photo/upload-item', { method:'POST', body:formDataAppendFiles(formData, input.files) });
            const rawText = await res.text();
            let data = null;
            try { data = JSON.parse(rawText); } catch(e) { data = { status:'error', msg: rawText }; }
            if(!res.ok) {
                alert(`업로드 실패 (HTTP ${res.status})\n` + (rawText ? rawText.substring(0,200) : ''));
                return;
            }
            if(data && data.status === 'ok') {
                showToast("사진이 업로드되었습니다.");
                loadPhotos();
            } else {
                alert("오류: " + (data.msg || "업로드 실패"));
            }
        } catch(e) {
            console.error(e);
            alert("서버 통신 오류");
        }
        input.value = "";
    };

    input.click();
}

function formDataAppendFiles(fd, files) {
    for(let i=0;i<files.length;i++) fd.append('files', files[i]);
    return fd;
}


// [view_api.js] 8. 사진 삭제 기능 (파이썬 서버와 찰떡궁합 버전)
async function deletePhoto(id) {
    if(!confirm("사진을 삭제하시겠습니까?")) return;
    
    const extKey = document.getElementById('extAccessKey')?.value || "";
    
    // 바구니(FormData)에 담기
    const formData = new FormData();
    formData.append('photo_id', id);

    // 주소창에 키를 붙여서 권한 확인
    const url = `/api/photo/delete${extKey ? '?access_key=' + extKey : ''}`;

    try {
        const res = await fetch(url, {
            method: 'POST',
            body: formData // JSON 대신 바구니째 전송
        });

        if (res.ok) {
            showToast("삭제되었습니다.");
            if(typeof loadPhotos === 'function') loadPhotos();
        } else {
            const data = await res.json();
            alert("실패: " + (data.msg || "권한이 없습니다."));
        }
    } catch(e) {
        alert("서버와 통신할 수 없습니다.");
    }
}


function buildItemLabelMap() {
    const map = {};
    document.querySelectorAll('tr[data-id]').forEach(tr => {
        const id = parseInt(tr.getAttribute('data-id'));
        const loc = (tr.getAttribute('data-loc') || '').trim();
        let prod = (tr.getAttribute('data-prod') || '').trim();
        const color = (tr.getAttribute('data-color') || '').trim();

        if(!prod) {
            const prodEl = tr.querySelector('.txt-prod div');
            if(prodEl) prod = prodEl.childNodes[0]?.textContent?.trim() || prodEl.textContent.trim();
        }

        const label = [loc, prod, color].filter(Boolean).join(' ');
        if(id) map[id] = label || ('품목 #' + id);
    });
    return map;
}


// ==========================================================================
// [Lightbox 스와이프 뷰어 전역 함수]
// ==========================================================================
window.__currentPhotoIndex = 0;
window.__lbTouchStartX = 0;

// 모달 열기
window.openLightbox = function(index) {
    window.__currentPhotoIndex = index;
    updateLightbox();
    document.getElementById('photoLightbox').style.display = 'flex';
};

// 화면 갱신 (사진 변경 시)
window.updateLightbox = function() {
    if(!window.__galleryPhotos || window.__galleryPhotos.length === 0) return;
    const p = window.__galleryPhotos[window.__currentPhotoIndex];
    const img = document.getElementById('lightboxImg');
    const counter = document.getElementById('lbCounter');
    
    if(img) img.src = p.FilePath;
    if(counter) counter.innerText = `${window.__currentPhotoIndex + 1} / ${window.__galleryPhotos.length}`;
};

// 이전 사진
window.prevPhoto = function(e) {
    if(e) e.stopPropagation(); // 배경 클릭(닫기) 방지
    if(window.__galleryPhotos && window.__galleryPhotos.length > 0) {
        window.__currentPhotoIndex--;
        if(window.__currentPhotoIndex < 0) window.__currentPhotoIndex = window.__galleryPhotos.length - 1; // 끝에 도달하면 처음으로 루프
        updateLightbox();
    }
};

// 다음 사진
window.nextPhoto = function(e) {
    if(e) e.stopPropagation();
    if(window.__galleryPhotos && window.__galleryPhotos.length > 0) {
        window.__currentPhotoIndex++;
        if(window.__currentPhotoIndex >= window.__galleryPhotos.length) window.__currentPhotoIndex = 0;
        updateLightbox();
    }
};

// 📱 모바일 스와이프 감지 이벤트
window.lbTouchStart = function(e) {
    window.__lbTouchStartX = e.changedTouches[0].screenX;
};

window.lbTouchEnd = function(e) {
    const endX = e.changedTouches[0].screenX;
    const diffX = window.__lbTouchStartX - endX;
    
    // 50px 이상 밀었을 때만 스와이프로 인정 (오터치 방지)
    if(diffX > 50) {
        nextPhoto(); // 손가락을 왼쪽으로 밂 -> 다음 사진
    } else if(diffX < -50) {
        prevPhoto(); // 손가락을 오른쪽으로 밂 -> 이전 사진
    }
};

// 10. 품목 상태 변경 (대기/주문/수령/AS)
function toggleStatusAjax(btn) {
    var itemId = btn.getAttribute('data-id');
    var currentStep = parseInt(btn.getAttribute('data-step'));
    var nextStep = (currentStep + 1) % 4;
    var btnInfo = [{t:'대기', c:'stat-0'}, {t:'주문', c:'stat-1'}, {t:'수령', c:'stat-2'}, {t:'AS', c:'stat-3'}];
    
    btn.className = "btn-status-toggle item-stat-btn " + btnInfo[nextStep].c;
    btn.innerText = btnInfo[nextStep].t;
    btn.setAttribute('data-step', nextStep);
    
    fetch(`/api/item/update-step?id=${itemId}&step=${nextStep}`)
        .then(() => { 
            // view_ui.js에 있는 함수 호출
            if(typeof checkAndSyncSubStatus === 'function') checkAndSyncSubStatus(); 
        })
        .catch(err => { console.error(err); alert("오류 발생. 새로고침합니다."); location.reload(); });
}

// 11. 담당자 저장
async function saveManagers() {
    var managerSelect = document.getElementById('managerSelect');
    var ids = [];
    var names = [];

    if (managerSelect) {
        var selectedOptions = Array.from(managerSelect.selectedOptions || []);
        selectedOptions = selectedOptions.filter(function(opt) { return String(opt.value || '').trim() !== ''; });
        ids = selectedOptions.map(function(opt) { return parseInt(opt.value); }).filter(Boolean);
        names = selectedOptions.map(function(opt) { return String(opt.text || '').trim(); }).filter(Boolean);
    } else {
        var checked = document.querySelectorAll('.chk-manager:checked');
        ids = Array.from(checked).map(function(cb) { return parseInt(cb.value); });
        names = Array.from(checked)
            .map(function(cb) {
                return cb.parentElement?.querySelector('span')?.innerText?.trim() || '';
            })
            .filter(Boolean);
    }

    try {
        const res = await fetch("/api/order/update-manager", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order_id: g_orderId, manager_ids: ids })
        });
        const data = await res.json();

        if (data && data.status === 'ok') {
            var disp = document.getElementById('dispManagerName');
            if (disp) {
                disp.innerText = names.length > 0 ? names.join(", ") : "미지정";
                disp.style.color = names.length > 0 ? '' : '#e03131';
            }
            var drop = document.getElementById('dropManagerList');
            if (drop) drop.style.display = 'none';
            if (typeof triggerModalSuccessFeedback === 'function') {
                triggerModalSuccessFeedback();
            }
        } else {
            alert(data.msg);
        }
    } catch (e) {
        alert("\uC624\uB958 \uBC1C\uC0DD");
    }
}

// 12. 현장 정보 저장 (설치면, 체크리스트)
async function saveSiteInfo(isSilent) {
    if(!g_orderId) return;

    var selectedItems = [];
    document.querySelectorAll('.check-btn.active').forEach(function(btn) {
        selectedItems.push(btn.getAttribute('data-val'));
    });
    var sVal = selectedItems.join(',');
    var checklist = document.getElementById('inpChecklist').value;
    
    var formData = new FormData();
    formData.append('order_id', g_orderId);
    formData.append('surface', sVal);
    formData.append('checklist', checklist);
    
    var extKey = document.getElementById('extAccessKey')?.value;
    if(extKey) formData.append('access_key', extKey);
    
    try {
        await fetch('/api/order/update-site-info', { method:'POST', body:formData });
        if (isSilent) {
            var saveIndicator = document.getElementById('saveIndicator');
            if(saveIndicator) { saveIndicator.style.display = 'block'; setTimeout(function() { saveIndicator.style.display = 'none'; }, 1500); }
            return;
        }
        if (typeof triggerModalSuccessFeedback === 'function') {
            triggerModalSuccessFeedback();
        }
        showToast("저장되었습니다.");
        setTimeout(function() {
            location.reload();
        }, 320);
    } catch(e) { if(!isSilent) alert("저장 실패"); }
}

// 13. 서명 저장
async function submitSignature() {
    if (!canvas) return; // canvas는 view_calc.js 또는 view_ui.js 전역변수
    var dataUrl = canvas.toDataURL("image/png");
    var oid = g_orderId || document.getElementById('srv-order-id').value;
    
    try {
        let res = await fetch('/api/order/save-signature', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ order_id: parseInt(oid), image_data: dataUrl })
        });
        let data = await res.json();
        if (data.status === "ok") {
            if (typeof closeSignModal === 'function') closeSignModal();
            if (typeof triggerModalSuccessFeedback === 'function') triggerModalSuccessFeedback();
            setTimeout(function() {
                location.reload();
            }, 320);
        } 
        else { alert("실패: " + data.msg); }
    } catch(e) { alert("통신 에러: " + e); }
}

// 14. 날짜 상태 변경 전송
function submitDateStatus() {
    var dateVal = document.getElementById('dateInput').value;
    var timeVal = document.getElementById('timeInput').value;
    var target = document.getElementById('targetStatus').value;
    if(!dateVal || !timeVal) { alert("날짜와 시간을 모두 확인해주세요."); return; }

    fetch('/api/order/update-date', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            order_id: parseInt(g_orderId),
            target: target,
            date_str: dateVal + " " + timeVal
        })
    }).then(r => r.json()).then(res => {
        if (typeof closeDateModal === 'function') closeDateModal();
        if (typeof triggerModalSuccessFeedback === 'function') triggerModalSuccessFeedback();
        setTimeout(function() {
            location.reload();
        }, 320);
    });
}

// 15. 결제완료 전송 (입금확인)
async function submitPayStatus() {
    const total = parseFloat(document.getElementById('raw-total-amt')?.value || 0);
    const discount = parseFloat(document.getElementById('inp-discount')?.value.replace(/,/g,'') || 0);
    const isVat = document.getElementById('payVatInput').checked;
    let supply = total - discount;
    let finalAmt = isVat ? Math.round(supply * 1.1) : supply;

    try {
        var formData = new FormData();
        formData.append('id', g_orderId);
        formData.append('vat', isVat);
        formData.append('final_amount', finalAmt); 
        await fetch("/api/order/save-info", { method: "POST", body: formData });

        var params = new URLSearchParams({
            id: g_orderId, type: 'pay', val: '입금완료',
            method: document.getElementById('payMethodInput').value,
            bank: document.getElementById('payBank').value,
            depositor: document.getElementById('payDepositor').value
        });

        let res = await fetch("/api/status/update?" + params.toString());
        if(res.ok) {
            if (typeof closePayModal === 'function') closePayModal();
            if (typeof triggerModalSuccessFeedback === 'function') triggerModalSuccessFeedback();
            setTimeout(function() {
                location.reload();
            }, 320);
        }
    } catch(e) { alert("오류 발생: " + e); }
}

// 16. 일정 불러오기 (캘린더)
function fetchSchedules() {
    var extKey = document.getElementById('extAccessKey')?.value || "";
    var url = '/api/schedule' + (extKey ? `?access_key=${extKey}` : '');

    fetch(url)
        .then(res => {
            if (!res.ok) throw new Error("권한 없음 또는 서버 오류");
            return res.json();
        })
        .then(data => {
            g_scheduleData = {};
            if(data && data.length > 0) {
                data.forEach(evt => {
                    var dKey = evt.start; 
                    if(!g_scheduleData[dKey]) g_scheduleData[dKey] = [];
                    g_scheduleData[dKey].push(evt);
                });
            }
            if(typeof g_fpInstance !== 'undefined' && g_fpInstance) g_fpInstance.redraw();
            var picker = document.getElementById('dateInput');
            if(picker && picker.value && typeof renderDailyTimeline === 'function') {
                renderDailyTimeline(picker.value);
            }
        })
        .catch(err => { console.log("일정 로드 건너뜀:", err); });
}

// 17. 아파트 DB 일괄 저장
function submitBulk() {
    if(document.querySelectorAll('.main-chk:checked').length > 0) {
        if(typeof markItemChanged === 'function') markItemChanged();
        var form = document.getElementById('bulkForm');
        var checkedBoxes = document.querySelectorAll('.main-chk:checked');
        var ids = Array.from(checkedBoxes).map(cb => cb.value).join(',');
        
        var hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.name = 'window_ids';
        hiddenInput.value = ids;
        form.appendChild(hiddenInput);
        
        form.action = '/api/apt/import-to-order';
        form.submit();
    }
    else alert("항목을 선택해주세요.");
}


// 20. SMS 트리거 체크 (URL 쿼리)
function checkSmsTrigger() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("sms_trigger") === "Y") {
        var amt = params.get("sms_amt") || "0";
        var txt = buildPaymentSmsText("금액", amt);
        var url = (navigator.userAgent.toLowerCase().indexOf("iphone") > -1) ? "sms:" + g_custPhone + "&body=" + encodeURIComponent(txt) : "sms:" + g_custPhone + "?body=" + encodeURIComponent(txt);
        window.history.replaceState({}, document.title, window.location.pathname + "?id=" + g_orderId);
        window.location.href = url;
    }
}

function getCompanySmsInfo() {
    var raw = window.__companySmsInfo || {};
    return {
        name: String(raw.name || "").trim(),
        bankInfo: String(raw.bankInfo || "").trim()
    };
}

function buildPaymentSmsText(amountLabel, amountText) {
    var smsInfo = getCompanySmsInfo();
    var lines = [];

    if (smsInfo.name) lines.push("[" + smsInfo.name + "]");
    if (smsInfo.bankInfo) lines.push(smsInfo.bankInfo);
    lines.push((amountLabel || "금액") + " : " + (amountText || "0"));
    lines.push("감사합니다.");

    return lines.join("\n");
}

// 21. 서브 상태 변경 (제품주문, 수령 등)
function toggleSubStatus(subType) {
    var statusMap = { 'order': '제품주문', 'receive': '제품수령', 'as': 'AS요청', 'wait': '작업대기', 'hold': '작업보류' };
    if (confirm("'" + statusMap[subType] + "' 상태를 변경하시겠습니까?")) {
        fetch("/api/status/update?id=" + g_orderId + "&type=sub&val=" + encodeURIComponent(subType))
            .then(res => { if(res.ok) location.reload(); else alert("변경 실패"); })
            .catch(e => alert("오류: " + e));
    }
}

// 22. 아파트 DB 단지 로드
function mdlLoadComplexes() {
    fetch('/api/apt/complexes').then(r=>r.json()).then(d=>{
        var html = '<option value="">1. 단지 선택</option>';
        d.forEach(i => html += `<option value="${i.ComplexID}">${i.ComplexName}</option>`);
        document.getElementById('mdlComplex').innerHTML = html;
    });
}

// 23. 아파트 DB 평형 로드
function mdlLoadPlans(cid) {
    var sel = document.getElementById('mdlPlan'); sel.disabled = true; sel.innerHTML = '<option>로딩중...</option>';
    fetch('/api/apt/plans/'+cid).then(r=>r.json()).then(d=>{
        var html = '<option value="">2. 평형 선택</option>';
        d.forEach(i => html += `<option value="${i.PlanID}">${i.PlanName}${i.IsRepresentative=='Y'?' (대표)':''}</option>`);
        sel.innerHTML = html; sel.disabled = false;
    });
}

// 24. 아파트 DB 창문 로드
function mdlLoadWindows(pid) {
    var con = document.getElementById('mdlListContainer'); con.innerHTML = '로딩중...';
    fetch('/api/apt/windows/'+pid).then(r=>r.json()).then(d=>{
        if(d.length === 0) { con.innerHTML = '<div style="padding:40px; text-align:center;">데이터 없음</div>'; return; }
        var grouped = {}; 
        d.forEach(i => { if(!grouped[i.LocationName]) grouped[i.LocationName]=[]; grouped[i.LocationName].push(i); });
        
        var html = '';
        for(var loc in grouped) {
            html += `<div class="loc-section"><div class="loc-header"><i class="fas fa-map-marker-alt"></i> ${loc}</div><div class="item-flex-row">`;
            grouped[loc].forEach(item => {
                var detail = (item.WinType.indexOf('커튼') > -1) ? `<div class="opt-area sub-btn-group"><label class="sub-chk-label"><input type="checkbox" name="CT_Inner_${item.WindowID}" value="Y" checked>속지</label><label class="sub-chk-label"><input type="checkbox" name="CT_Outer_${item.WindowID}" value="Y" checked>겉지</label></div>` : (parseInt(item.SplitCount)>1 ? `<div class="opt-area"><span class="blind-info">${item.SplitCount}창 연창</span></div>` : ``);
                html += `<div class="item-card" onclick="this.querySelector('.main-chk').click()"><div class="card-top"><div><div class="card-type">${item.WinType}</div><div class="card-size">${item.Width} x ${item.Height}</div></div><input type="checkbox" name="window_ids" value="${item.WindowID}" class="main-chk" onclick="event.stopPropagation()"></div>${detail}</div>`;
            });
            html += `</div></div>`;
        }
        con.innerHTML = html;
    });
}

/* ==========================================================================
   [view_api.js] UI 동작 및 서버 통신 (사장님 코드 통합 완료)
   ========================================================================== */

// 1. [진입점] 상태 변경 통합 함수
function updateStatusLive(element, type, value, orderId) {
    if (!orderId && typeof g_orderId !== 'undefined') orderId = g_orderId;

    // ----------------------------------------------------------------------
    // ① [작업완료] 클릭 시 -> 사장님의 processWorkComplete 함수 호출!
    // ----------------------------------------------------------------------
    if (type === 'main' && value === '작업완료') {
        var payBtn = document.querySelector('.btn-pay');
        var sendSms = false;

        // 미입금 상태(버튼 꺼짐)라면 문자 보낼지 물어보기
        if (payBtn && !payBtn.classList.contains('active')) {
            var msg = "현재 [미입금] 상태입니다.\n\n" +
                      "작업을 완료 처리하고,\n" +
                      "고객님께 '계좌번호 및 잔금' 안내 문자를 발송하시겠습니까?";
            if (confirm(msg)) {
                sendSms = true;
            }
        }
        
        // ★ 여기서 사장님의 함수를 호출합니다!
        processWorkComplete(value, sendSms);
        return; 
    }

    // ② [날짜 모달] 방문, 시공, AS는 모달 띄우기
    if (type === 'main' && ['방문상담', '시공예정', 'AS요청'].includes(value)) {
        if (typeof openDateModal === 'function') {
            // [변경 이유] 기존 일정을 JSON 데이터에서 추출하여 전달합니다.
            let savedSchedules = {};
            try {
                const scriptTag = document.getElementById('srv-saved-schedules');
                if (scriptTag) savedSchedules = JSON.parse(scriptTag.textContent);
            } catch(e) { console.error("일정 데이터 파싱 오류", e); }
            
            const existingVal = savedSchedules[value] || "";
            openDateModal(value, existingVal); // orderId 대신 existingVal 전달
            return;
        }
    }

    // ----------------------------------------------------------------------
    // ③ [일반 저장] 그 외 상태는 바로 서버로 전송
    // ----------------------------------------------------------------------
    var serverVal = value;
    if (value === 'wait')    serverVal = 'waiting';
    if (value === 'order')   serverVal = 'ordered';
    if (value === 'receive') serverVal = 'received';

    var targetUrl = `/api/status/update?id=${orderId}&type=${type}&val=${encodeURIComponent(serverVal)}`;
    var extKey = document.querySelector('input[name="access_key"]');
    if (extKey) targetUrl += `&access_key=${extKey.value}`;

    // 페이지 이동 (새로고침 효과)
    location.href = targetUrl;
}

// 2. [사장님 코드 복원] 작업 완료 처리 (문자 앱 연동)
function processWorkComplete(status, sendSms) {
    // 전화번호 가져오기 (전역변수 없으면 화면에서 찾기)
    var phoneTxt = (typeof g_custPhone !== 'undefined') ? g_custPhone : "";
    if (!phoneTxt) {
        var el = document.getElementById('customer-phone');
        if (el) phoneTxt = el.innerText || el.value;
    }

    // 상태 변경 요청 (fetch)
    fetch(`/api/status/update?id=${g_orderId}&type=main&val=${encodeURIComponent(status)}`)
        .then(() => {
            if (sendSms) {
                // 잔금 가져오기
                var balanceTxt = document.getElementById('dispFinal') ? document.getElementById('dispFinal').innerText : "0원";
                var cleanPhone = phoneTxt.replace(/-/g, ""); 
                
                // 문자 내용 구성
                var msg = buildPaymentSmsText("잔금", balanceTxt);

                // 클립보드 복사 (혹시 문자 앱 연결 안 될 때 대비)
                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(msg).catch(e => console.error(e));
                }

                // 스마트폰 문자 앱 호출 (sms: 프로토콜)
                var url = "";
                if (navigator.userAgent.toLowerCase().indexOf("iphone") > -1) {
                    url = "sms:" + cleanPhone + "&body=" + encodeURIComponent(msg);
                } else {
                    url = "sms:" + cleanPhone + "?body=" + encodeURIComponent(msg);
                }
                
                // 문자 앱 열기
                window.location.href = url;
                
                // 1초 뒤 새로고침 (화면 갱신)
                setTimeout(function() { location.reload(); }, 1000);
            } else {
                // 문자 안 보내면 바로 새로고침
                location.reload();
            }
        })
        .catch(err => {
            alert("상태 변경 중 오류가 발생했습니다.");
            console.error(err);
            location.reload();
        });
}

// 3. [결제] 입금확인 버튼 함수
function togglePayment(nextVal) {
    if (nextVal === '입금완료') {
        if (typeof openPayModal === 'function') openPayModal();
    } else {
        if (confirm("결제 상태를 '미결제'로 변경하시겠습니까?")) {
            var oid = (typeof g_orderId !== 'undefined') ? g_orderId : 0;
            location.href = `/api/status/update?id=${oid}&type=sub&val=payment`;
        }
    }
}

// 4. [연결] 상단 타임라인 클릭 연결
function changeMainStatus(newStat) {
    updateStatusLive(null, 'main', newStat, g_orderId);
}



function highlightItemRow(itemId) {
    document.querySelectorAll('tr[data-id]').forEach(tr=>{
        tr.classList.remove('row-photo-focus');
    });
    const tr = document.querySelector('tr[data-id="'+itemId+'"]');
    if(tr){
        tr.classList.add('row-photo-focus');
        tr.scrollIntoView({behavior:'smooth', block:'center'});
        setTimeout(()=>tr.classList.remove('row-photo-focus'), 2500);
    }
}

// ✅ 사진 업로드 자동 작업기록(C)
// - 업로드 성공 후 호출되며 '상태' 탭에 표시됩니다.
async function addAutoHistoryPhotoLog(itemId, stage){
  const oid = (typeof g_orderId !== 'undefined') ? g_orderId : null;
  if(!oid) return;

  const labelMap = { before:'전', during:'중', after:'후' };
  const label = labelMap[stage] || stage;

  // 품목 라벨(위치+제품명) 가져오기
  let itemLabel = '';
  try{
    const map = buildItemLabelMap();
    itemLabel = map[itemId] || ('품목 #' + itemId);
  }catch(e){
    itemLabel = '품목 #' + itemId;
  }

  const formData = new FormData();
  formData.append('order_id', oid);
  // ★ '메모'에서 '상태변경'으로 수정하여 상태 탭에서 보이도록 조치
  formData.append('log_type', '상태변경'); 
  formData.append('contents', `📷 [사진등록] ${label} - ${itemLabel}`);

  const key = document.getElementById('extAccessKey')?.value;
  if(key) formData.append('access_key', key);

  try{
    await fetch('/api/history/add', { method:'POST', body:formData });
  }catch(e){}
}


/* ==========================================================================
   [voice draft API]
   ========================================================================== */
async function apiCreateVoiceDraft(payload) {
    const res = await fetch('/api/voice/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('voice_draft_create_failed');
    return await res.json();
}

async function apiGetVoiceDraft(draftId) {
    const res = await fetch(`/api/voice/drafts/${draftId}`);
    if (!res.ok) throw new Error('voice_draft_get_failed');
    return await res.json();
}

async function apiListVoiceDrafts(status = 'pending', pageContext = 'view') {
    const qs = new URLSearchParams({ status, pageContext });
    const res = await fetch(`/api/voice/drafts?${qs.toString()}`);
    if (!res.ok) throw new Error('voice_drafts_list_failed');
    return await res.json();
}

async function apiDiscardVoiceDraft(draftId) {
    const res = await fetch('/api/voice/discard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ draftId })
    });
    if (!res.ok) throw new Error('voice_draft_discard_failed');
    return await res.json();
}

async function apiApplyVoiceDraft(payload) {
    const res = await fetch('/api/voice/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('voice_draft_apply_failed');
    return await res.json();
}

// /view 작업기록으로 안전하게 남기기
async function addVoiceHistoryLog(orderId, logType, contents) {
    const formData = new FormData();
    formData.append('order_id', orderId);
    formData.append('log_type', logType || '메모');
    formData.append('contents', contents || '');

    const key = document.getElementById('extAccessKey')?.value;
    if (key) formData.append('access_key', key);

    const res = await fetch('/api/history/add', { method: 'POST', body: formData });
    if (!res.ok) throw new Error('voice_history_add_failed');
    return true;
}



/* ========================================================================== 
   [voice draft API - phase2 robust override]
   ========================================================================== */
async function __voiceJson(res, fallbackErr) {
    const raw = await res.text();
    let data = null;
    try { data = raw ? JSON.parse(raw) : null; } catch(e) {}
    if (!res.ok) {
        const msg = (data && (data.detail || data.msg || data.message)) || fallbackErr || raw || ('HTTP ' + res.status);
        throw new Error(msg);
    }
    return data || {};
}

async function apiCreateVoiceDraft(payload) {
    const res = await fetch('/api/voice/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return await __voiceJson(res, 'voice_draft_create_failed');
}

async function apiGetVoiceDraft(draftId) {
    const res = await fetch(`/api/voice/drafts/${draftId}`);
    return await __voiceJson(res, 'voice_draft_get_failed');
}

async function apiListVoiceDrafts(status = 'pending', pageContext = 'view') {
    const qs = new URLSearchParams({ status, pageContext });
    const res = await fetch(`/api/voice/drafts?${qs.toString()}`);
    return await __voiceJson(res, 'voice_drafts_list_failed');
}

async function apiDiscardVoiceDraft(draftId) {
    const res = await fetch('/api/voice/discard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ draftId })
    });
    return await __voiceJson(res, 'voice_draft_discard_failed');
}

async function apiApplyVoiceDraft(payload) {
    const res = await fetch('/api/voice/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return await __voiceJson(res, 'voice_draft_apply_failed');
}
