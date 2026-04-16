/* ==========================================================================
   [view_ui.js] page interaction helpers
   ========================================================================== */

window.safeCleanNum = window.safeCleanNum || function(value) {
    if (typeof cleanNum === 'function') return cleanNum(value);
    return parseFloat(String(value || '').replace(/,/g, '')) || 0;
};

window.__checklistManualOverride = window.__checklistManualOverride || false;

function splitManagerDisplayNames(raw) {
    return String(raw || '')
        .split(/\s*[,/]\s*/)
        .map(function(name) { return String(name || '').trim(); })
        .filter(Boolean);
}

function formatCompactManagerNames(names) {
    var list = Array.isArray(names) ? names.filter(Boolean) : splitManagerDisplayNames(names);
    if (!list.length) return "미지정";
    if (list.length === 1) return list[0];
    return list[0] + " 외 " + (list.length - 1) + "명";
}

function syncManagerSummaryDisplay(rawNames) {
    var names = Array.isArray(rawNames) ? rawNames.filter(Boolean) : splitManagerDisplayNames(rawNames);
    var compact = formatCompactManagerNames(names);
    var full = names.join(", ");
    var shell = document.querySelector('.mgr-select-shell');
    var disp = document.getElementById('dispManagerName');
    if (disp) {
        disp.innerText = compact;
        disp.style.color = names.length > 0 ? '' : '#e03131';
        disp.dataset.fullNames = full;
        disp.title = full || compact;
    }
    if (shell) {
        shell.classList.toggle('is-compact-summary', names.length > 1);
    }
    var inlineSummary = document.getElementById('managerSummaryCompact');
    if (inlineSummary) {
        var extraSummary = names.length > 1 ? (names[0] + " \uC678 " + (names.length - 1) + "\uBA85") : "";
        inlineSummary.innerText = extraSummary;
        inlineSummary.style.display = extraSummary ? 'block' : 'none';
        inlineSummary.style.color = extraSummary ? '#868e96' : '#e03131';
        inlineSummary.title = full || compact;
    }
    var staticName = document.querySelector('.mgr-name-static');
    if (staticName) {
        staticName.innerText = compact;
        staticName.title = full || compact;
    }
}

function installManagerSaveSummaryPatch() {
    if (window.__managerSaveSummaryPatched) return;
    if (typeof window.saveManagers !== 'function') return;
    var original = window.saveManagers;
    window.saveManagers = async function() {
        var result = await original.apply(this, arguments);
        var managerSelect = document.getElementById('managerSelect');
        if (managerSelect) {
            var names = Array.from(managerSelect.selectedOptions || [])
                .map(function(opt) { return String(opt.text || '').trim(); })
                .filter(Boolean);
            syncManagerSummaryDisplay(names);
        } else {
            syncManagerSummaryDisplay(document.getElementById('dispManagerName')?.innerText || document.querySelector('.mgr-name-static')?.innerText || '');
        }
        return result;
    };
    window.__managerSaveSummaryPatched = true;
}

function hasChecklistManualOverride() {
    return window.__checklistManualOverride === true;
}

function setChecklistManualOverride(enabled) {
    window.__checklistManualOverride = !!enabled;
    var input = document.getElementById('inpChecklist');
    if (!input) return;
    input.dataset.manualOverride = enabled ? '1' : '0';
    if (enabled) {
        input.dataset.manualChecklistValue = input.value;
    } else {
        delete input.dataset.manualChecklistValue;
    }
}

function resetChecklistManualOverride(nextValue) {
    var input = document.getElementById('inpChecklist');
    setChecklistManualOverride(false);
    if (!input || typeof nextValue === 'undefined') return;
    input.dataset.autoUpdating = '1';
    input.value = nextValue || '';
    delete input.dataset.autoUpdating;
}

function bindChecklistManualOverride() {
    var input = document.getElementById('inpChecklist');
    if (!input || input.dataset.manualOverrideBound === '1') return;
    input.dataset.manualOverrideBound = '1';
    input.addEventListener('input', function() {
        if (this.dataset.autoUpdating === '1') return;
        setChecklistManualOverride(this.value.trim().length > 0);
    });
}

function installChecklistManualGuard() {
    if (window.__checklistManualGuardInstalled) return;
    var original = window.autoCalcRails || (typeof autoCalcRails === 'function' ? autoCalcRails : null);
    if (typeof original !== 'function') return;
    window.__checklistManualGuardInstalled = true;
    window.__originalAutoCalcRails = original;
    window.autoCalcRails = function() {
        if (hasChecklistManualOverride()) {
            var input = document.getElementById('inpChecklist');
            if (input && typeof input.dataset.manualChecklistValue === 'string' && input.value !== input.dataset.manualChecklistValue) {
                input.dataset.autoUpdating = '1';
                input.value = input.dataset.manualChecklistValue;
                delete input.dataset.autoUpdating;
            }
            return input ? input.value : '';
        }
        return original.apply(this, arguments);
    };
}

document.addEventListener("DOMContentLoaded", function() {

    var key = document.getElementById('extAccessKey')?.value;
    if (key) {
        var memoForm = document.getElementById('memoForm');
        if (memoForm) {
            var input = document.createElement("input");
            input.type = "hidden";
            input.name = "access_key";
            input.value = key;
            memoForm.appendChild(input);
        }
    }

    var idEl = document.getElementById('srv-order-id');
    if (idEl) {
        g_orderId = parseInt(idEl.value);
    } else {
        var path = window.location.pathname.split('/');
        var last = path[path.length - 1];
        if (!isNaN(last)) g_orderId = parseInt(last);
    }

    var scrollTarget = sessionStorage.getItem('scroll_target');
    if (scrollTarget === 'item_add_bar') {
        sessionStorage.removeItem('scroll_target');
        setTimeout(function() {
            var itemAddBar = document.getElementById('itemAddButtonBar');
            if (itemAddBar) {
                var rect = itemAddBar.getBoundingClientRect();
                var fixedBottomGap = 170;
                var targetY = window.scrollY + rect.bottom - window.innerHeight + fixedBottomGap;
                window.scrollTo({ top: Math.max(0, targetY), behavior: 'auto' });
            }
        }, 60);
    } else {
        var scrollPos = sessionStorage.getItem('scrollPos');
        if (scrollPos) window.scrollTo(0, scrollPos);
    }

    if (typeof initSortable === 'function') initSortable();
    if (typeof initPage === 'function') initPage();
    if (typeof checkSmsTrigger === 'function') checkSmsTrigger();
    if (typeof fetchSchedules === 'function') fetchSchedules();
    if (typeof initFontControl === 'function') initFontControl();

    window.addEventListener("beforeunload", function() {
        sessionStorage.setItem('scrollPos', window.scrollY);
    });

    var btnMemo = document.getElementById('btnTabMemo');
    if (btnMemo && typeof filterHistory === 'function') {
        filterHistory('\uBA54\uBAA8', btnMemo);
    }

    var surfVal = document.getElementById('srv-site-surf') ? document.getElementById('srv-site-surf').value : "";
    if (surfVal) {
        surfVal.split(',').forEach(function(val) {
            var cleanVal = val.trim();
            if (cleanVal) {
                var cb = document.querySelector(`input[name="site_surf"][value="${cleanVal}"]`);
                if (cb) cb.checked = true;
            }
        });
    }

    bindChecklistManualOverride();
    installChecklistManualGuard();
    installManagerSaveSummaryPatch();

    var checkVal = document.getElementById('srv-checklist') ? document.getElementById('srv-checklist').value : "";
    var inpCheck = document.getElementById('inpChecklist');
    if (inpCheck) {
        var currentChecklist = inpCheck.value || "";
        if (checkVal) {
            resetChecklistManualOverride(checkVal);
        } else if (currentChecklist.trim()) {
            setChecklistManualOverride(true);
        } else {
            resetChecklistManualOverride("");
            if (typeof autoCalcRails === 'function') autoCalcRails();
        }
    }

    if (typeof loadPhotos === 'function') loadPhotos();

    if (typeof initMobileSwiperController === 'function') initMobileSwiperController();

    if (typeof initVoiceMode === 'function') initVoiceMode();
    if (typeof initializeLocationPickerUi === 'function') initializeLocationPickerUi();
    if (typeof initInfoModalSelects === 'function') initInfoModalSelects();
    if (typeof syncInflowGuideState === 'function') syncInflowGuideState();

    var inflowRouteEl = document.getElementById('inflow-route');
    var inflowDetailEl = document.getElementById('inflow-detail');
    if (inflowRouteEl && !inflowRouteEl.dataset.guideBound) {
        inflowRouteEl.dataset.guideBound = '1';
        inflowRouteEl.addEventListener('change', syncInflowGuideState);
    }
    if (inflowDetailEl && !inflowDetailEl.dataset.guideBound) {
        inflowDetailEl.dataset.guideBound = '1';
        inflowDetailEl.addEventListener('input', syncInflowGuideState);
    }

    setTimeout(function() {
        var managerSelect = document.getElementById('managerSelect');
        if (managerSelect) {
            var names = Array.from(managerSelect.selectedOptions || [])
                .map(function(opt) { return String(opt.text || '').trim(); })
                .filter(Boolean);
            syncManagerSummaryDisplay(names);
        } else {
            syncManagerSummaryDisplay(document.getElementById('dispManagerName')?.innerText || document.querySelector('.mgr-name-static')?.innerText || '');
        }
    }, 0);

    var manualForm = document.getElementById('manualForm');
    if (manualForm && !manualForm.dataset.manualSaveFlashBound) {
        manualForm.dataset.manualSaveFlashBound = '1';
        manualForm.addEventListener('submit', function() {
            sessionStorage.setItem('manual_save_flash', '1');
            sessionStorage.setItem('scroll_target', 'item_add_bar');
        });
    }

    var bulkForm = document.getElementById('bulkForm');
    if (bulkForm && !bulkForm.dataset.bulkSaveScrollBound) {
        bulkForm.dataset.bulkSaveScrollBound = '1';
        bulkForm.addEventListener('submit', function() {
            sessionStorage.setItem('scroll_target', 'item_add_bar');
        });
    }

    var hasPendingModalSuccess =
        sessionStorage.getItem('manual_save_flash') === '1' ||
        sessionStorage.getItem('modal_success_feedback') === '1';
    if (hasPendingModalSuccess) {
        sessionStorage.removeItem('manual_save_flash');
        sessionStorage.removeItem('modal_success_feedback');
        setTimeout(function() {
            if (typeof triggerModalSuccessFeedback === 'function') triggerModalSuccessFeedback();
        }, 60);
    }

    const subBtns = ['btnSub_order', 'btnSub_receive'];
    subBtns.forEach(id => {
        let el = document.getElementById(id);
        if (el) {
            let originClick = el.getAttribute('onclick');
            el.removeAttribute('onclick');

            el.addEventListener('click', function(e) {
                if (isProcessing) {
                    e.preventDefault();
                    return;
                }
                isProcessing = true;
                setTimeout(() => isProcessing = false, 1000);

                if (originClick && typeof toggleSubStatus === 'function') {
                    if (originClick.includes('order')) toggleSubStatus('order');
                    else if (originClick.includes('receive')) toggleSubStatus('receive');
                }
            });
        }
    });

    setTimeout(function() {
        var btnMemo = document.getElementById('btnTabMemo');
        if (btnMemo) {
            filterHistory('\uBA54\uBAA8', btnMemo);
        } else {
            filterHistory('\uBA54\uBAA8', null);
        }
    }, 150);
});

/* ========================================================================== */
/* Mobile Swiper (Site / Payment / Photos / Log) */
/* ========================================================================== */

let _mobileSwiper = null;
const _mobileSectionOrigins = new Map(); // el -> {parent, nextSibling}
let _mobileLogBadgeCount = 0;
let _toastTimer = null;
var g_groupData = {};

try {
    const groupDataNode = document.getElementById('srv-group-data');
    const groupDataText = groupDataNode ? groupDataNode.textContent : '';
    if (groupDataText && groupDataText.trim()) {
        g_groupData = JSON.parse(groupDataText);
    }
} catch (e) {
    console.warn('group data parse failed', e);
    g_groupData = {};
}

function scrollToMobileSwiper() {
    const root = document.getElementById('mobileSwiperRoot');
    if (!root) return;
    // 탭/슬라이드가 보이도록 스무스 스크롤
    const y = window.scrollY + root.getBoundingClientRect().top - 8;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
}

function showMobileToast(msg, ms = 1400) {
    const el = document.getElementById('mobileToast');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { el.style.display = 'none'; }, ms);
}

function setLogBadge(n) {
    _mobileLogBadgeCount = Math.max(0, parseInt(n || 0));
    const badge = document.getElementById('mBadgeLog');
    if (!badge) return;
    if (_mobileLogBadgeCount <= 0) {
        badge.style.display = 'none';
        badge.textContent = '0';
    } else {
        badge.style.display = 'inline-flex';
        badge.textContent = String(_mobileLogBadgeCount);
    }
}

function incLogBadge() {
    setLogBadge((_mobileLogBadgeCount || 0) + 1);
}

function initMobileSwiperController() {
    // Swiper가 없으면 스킵 (CDN 로딩 실패 등)
    if (typeof Swiper === 'undefined') return;

    const mq = window.matchMedia('(max-width: 900px)');

    const handle = () => {
        if (mq.matches) {
            enableMobileSwiper();
        } else {
            disableMobileSwiper();
        }
    };

    // 초기 1회
    handle();

    // 리사이즈/회전 대응 (디바운스)
    let t = null;
    window.addEventListener('resize', () => {
        clearTimeout(t);
        t = setTimeout(handle, 120);
    });
}

function enableMobileSwiper() {
    const root = document.getElementById('mobileSwiperRoot');
    if (!root) return;

    const secPayment = document.getElementById('section-payment');
    const secSite = document.getElementById('section-site');
    const secPhotos = document.getElementById('section-photos');
    const secLog = document.getElementById('section-log');

    // 섹션이 없으면 스킵
    if (!secPayment || !secSite || !secPhotos || !secLog) return;

    // 이미 활성화된 상태면 탭 UI만 동기화
    if (_mobileSwiper) {
        document.body.classList.add('mobile-swiper-on');
        syncMobileTabs(_mobileSwiper.realIndex ?? _mobileSwiper.activeIndex);
        return;
    }

    // 섹션을 Swiper 슬라이드로 이동
    const slotSite = root.querySelector('.mobile-slide-inner[data-section="site"]');
    const slotPayment = root.querySelector('.mobile-slide-inner[data-section="payment"]');
    const slotPhotos = root.querySelector('.mobile-slide-inner[data-section="photos"]');
    const slotLog = root.querySelector('.mobile-slide-inner[data-section="log"]');

    if (!slotSite || !slotPayment || !slotPhotos || !slotLog) return;

    mountSectionToSlot(secSite, slotSite);
    mountSectionToSlot(secPayment, slotPayment);
    mountSectionToSlot(secPhotos, slotPhotos);
    mountSectionToSlot(secLog, slotLog);

    document.body.classList.add('mobile-swiper-on');

    // Swiper 생성 (기본은 결제: index 1)
    _mobileSwiper = new Swiper('.mobileSwiper', {
        initialSlide: 0,
        loop: true,
        centeredSlides: true,
        slidesPerView: 'auto',
        spaceBetween: 12,
        resistanceRatio: 0.85,
        threshold: 6,
        pagination: {
            el: '#mobileSwiperRoot .swiper-pagination',
            clickable: true,
        },
        on: {
            init: function() {
                syncMobileTabs(this.realIndex);
                bindMobileTabs(this);
                bindMobileQuickbar(this);
            },
            slideChange: function() {
                syncMobileTabs(this.realIndex);
            }
        }
    });
}

function disableMobileSwiper() {
    if (_mobileSwiper) {
        try { _mobileSwiper.destroy(true, true); } catch(e) {}
        _mobileSwiper = null;
    }
    // 원위치 복구
    restoreAllMobileSections();
    document.body.classList.remove('mobile-swiper-on');
}

function mountSectionToSlot(sectionEl, slotEl) {
    if (!sectionEl || !slotEl) return;

    // 원래 위치 기록 (최초 1회)
    if (!_mobileSectionOrigins.has(sectionEl)) {
        _mobileSectionOrigins.set(sectionEl, {
            parent: sectionEl.parentNode,
            nextSibling: sectionEl.nextSibling
        });
    }

    // 이동
    slotEl.appendChild(sectionEl);
}

function restoreAllMobileSections() {
    if (_mobileSectionOrigins.size === 0) return;
    _mobileSectionOrigins.forEach((pos, el) => {
        if (!pos || !pos.parent) return;
        // 이미 같은 부모면 스킵
        if (el.parentNode === pos.parent) return;
        if (pos.nextSibling && pos.nextSibling.parentNode === pos.parent) {
            pos.parent.insertBefore(el, pos.nextSibling);
        } else {
            pos.parent.appendChild(el);
        }
    });
}

function bindMobileTabs(swiper) {
    const root = document.getElementById('mobileSwiperRoot');
    if (!root) return;
    const tabs = root.querySelectorAll('.mobile-swiper-tabs .m-tab');
    tabs.forEach(btn => {
        btn.addEventListener('click', () => {
            scrollToMobileSwiper();
            const idx = parseInt(btn.getAttribute('data-index'));
            if (!isNaN(idx)) swiper.slideToLoop(idx);
        });
    });
}

function bindMobileQuickbar(swiper) {
    const root = document.getElementById('mobileSwiperRoot');
    if (!root) return;
    const bar = root.querySelector('.mobile-quickbar');
    if (!bar) return;

    // 중복 바인딩 방지
    if (bar.getAttribute('data-bound') === '1') return;
    bar.setAttribute('data-bound', '1');

    const getOrderId = () => {
        const v = document.getElementById('srv-order-id')?.value;
        const n = parseInt(v);
        return Number.isFinite(n) ? n : null;
    };

    // 사진추가: "시공완료(After)" 업로드로 바로 연결
    const clickCompletionPhotoInput = () => {
        const sec = document.getElementById('section-photos');
        if (!sec) return;
        // completion 업로드 input만 선택
        const input = sec.querySelector('input[type="file"][onchange*="completion"]') ||
                      sec.querySelector('input[type="file"][onchange*="\'completion\'"]') ||
                      sec.querySelectorAll('input[type="file"]')[1];
        if (input) input.click();
    };

    const saveCurrent = () => {
        const idx = swiper.realIndex;
        const oid = getOrderId();

        // 0:현장, 1:결제, 2:사진, 3:기록
        if (idx === 1) {
            if (typeof window.savePaymentLive === 'function') return window.savePaymentLive();
        }
        if (idx === 0) {
            // 현장: 메모/체크리스트 둘 다 저장 시도
            if (oid && typeof window.saveInfoLive === 'function') window.saveInfoLive(oid);
            if (typeof window.saveSiteInfo === 'function') window.saveSiteInfo(false);
            return;
        }
        if (idx === 3) {
            // 기록: 입력이 있으면 추가
            if (oid && typeof window.addHistoryLive === 'function') return window.addHistoryLive(oid);
        }
        // 사진은 업로드 시 즉시 저장됨
    };

    bar.addEventListener('click', (e) => {
        const btn = e.target?.closest?.('button[data-action]');
        if (!btn) return;
        const act = btn.getAttribute('data-action');

        // 대시보드/맨위는 스크롤 우선 순서가 다름
        if (act === 'dashboard') {
            try { goBackToDashboard(); } catch(e) { location.href = '/dashboard'; }
            return;
        }
        if (act === 'top') {
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }

        // 하단 버튼(결제/사진 등)을 누르면:
// 1) 음성모드 토글은 스크롤 없이 처리
// 2) 결제/사진 등은 Swiper 영역이 보이도록 먼저 스크롤
        if (act === 'voiceMode') {
            toggleVoiceMode();
            return;
        }

        scrollToMobileSwiper();

        if (act === 'pay') return swiper.slideToLoop(1);
        if (act === 'photo') {
            swiper.slideToLoop(2);
            // 슬라이드 이동 후 파일 선택창
            setTimeout(clickCompletionPhotoInput, 250);
            return;
        }
    });

    // 어디서든 작업기록 입력 바 바인딩
    bindMobileWorklogBar();
}

// ✅ 하단 퀵바(작업기록 & 마이크) 완벽 제어 함수
function bindMobileWorklogBar() {
    const input = document.getElementById('quick-worklog-input');
    const btn = document.getElementById('quick-worklog-submit');
    const mic = document.getElementById('quick-worklog-mic');
    
    // 요소가 없거나 이미 연결되었으면 중복 연결 방지
    if (!input || !btn) return;
    if (btn.getAttribute('data-bound') === '1') return;
    btn.setAttribute('data-bound', '1');

    const getOrderId = () => {
        if (typeof g_orderId !== 'undefined' && g_orderId) return g_orderId;
        const v = document.getElementById('srv-order-id')?.value;
        const n = parseInt(v);
        return Number.isFinite(n) ? n : null;
    };

    const appendWorklogRow = (content) => {
        const list = document.querySelector('.history-list');
        if (!list) return;
        const now = new Date();
        const pad2 = (x) => String(x).padStart(2, '0');
        const dateStr = `${now.getFullYear()}-${pad2(now.getMonth()+1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}`;

        const html = `
            <div class="memo-item history-row" data-type="메모">
                <div class="memo-top">
                    <div class="memo-meta">
                        <span class="badge-type type-memo">작업기록</span>
                        <span class="author-name">방금</span>
                        <span class="reg-date">${dateStr}</span>
                    </div>
                </div>
                <div class="memo-text">${escapeHtml(content)}</div>
            </div>`;

        if (list.innerText.includes('기록이 없습니다')) list.innerHTML = '';
        list.insertAdjacentHTML('afterbegin', html);
    };

    // 텍스트/음성 공통 전송 로직
    const submit = async () => {
        const oid = getOrderId();
        if (!oid) return;
        const content = (input.value || '').trim();
        if (!content) return;

        appendWorklogRow(content);
        input.value = ''; // 창 비우기

        const formData = new FormData();
        formData.append('order_id', oid);
        formData.append('log_type', '메모');
        formData.append('contents', content);

        const key = document.getElementById('extAccessKey')?.value;
        if (key) formData.append('access_key', key);

        let ok = true;
        if (typeof window.sendBackgroundRequest === 'function') {
            ok = await window.sendBackgroundRequest('/api/history/add', formData, true);
        } else {
            ok = await fetch('/api/history/add', { method: 'POST', body: formData })
                .then(res => res.ok)
                .catch(() => false);
        }

        if (typeof incLogBadge === 'function' && typeof _mobileSwiper !== 'undefined' && _mobileSwiper && (_mobileSwiper.realIndex !== 3)) {
            incLogBadge();
        }

        if (ok && typeof triggerModalSuccessFeedback === 'function') {
            triggerModalSuccessFeedback();
        }
        
        try { showToast('작업기록 등록 완료!'); } catch(e) { triggerModalSuccessFeedback(); }
    };

    // 1. 등록 버튼 클릭 시 전송
    btn.addEventListener('click', submit);
    
    // 2. 키보드 엔터 칠 때 전송
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            submit();
        }
    });

    // 3. 마이크 로직 (클릭 시 듣고 -> 자동 전송)
    if (mic && mic.getAttribute('data-bound') !== '1') {
        mic.setAttribute('data-bound', '1');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (!SpeechRecognition) {
            mic.style.display = 'none';
        } else {
            let recog = null;

            mic.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation(); 
                
                if (mic.classList.contains('listening')) {
                    if (recog) recog.stop();
                    return;
                }
                
                try {
                    recog = new SpeechRecognition();
                    recog.lang = 'ko-KR';
                    recog.maxAlternatives = 1;
                    recog.continuous = false;
                    recog.interimResults = false;

                    recog.onstart = function() {
                        mic.classList.add('listening');
                        mic.style.color = '#e03131'; 
                        input.placeholder = "말씀하세요 🎤...";
                    };

                    recog.onresult = function(event) {
                        const t = (event.results[0][0].transcript || '').trim();
                        if (t) {
                            input.value = (input.value ? (input.value.trim() + ' ') : '') + t;
                            // ★ 핵심: 인식이 성공하면 0.3초 뒤에 자동으로 'submit' 함수를 실행!
                            setTimeout(() => { submit(); }, 300);
                        }
                    };

                    recog.onend = function() {
                        mic.classList.remove('listening');
                        mic.style.color = '';
                        input.placeholder = "작업기록 입력…";
                    };

                    recog.onerror = function(event) {
                        mic.classList.remove('listening');
                        mic.style.color = '';
                        input.placeholder = (event.error === 'no-speech') ? "음성 미감지" : "인식 실패";
                        setTimeout(() => { input.placeholder = "작업기록 입력…"; }, 1500);
                    };

                    recog.start();
                } catch(err) {
                    mic.classList.remove('listening');
                    mic.style.color = '';
                }
            });
        }
    }
}

// XSS 방지용 최소 escape
function escapeHtml(str) {
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}


/* ========================================================================== */
/* Global Dictation (모든 input/textarea에서 음성 입력) */
/* - 사용법: 원하는 입력칸을 탭(포커스) → 하단 [음성] 버튼 클릭 → 말하기 */
/* ========================================================================== */

let __lastFocusedInput = null;

document.addEventListener('focusin', (e) => {
    const t = e.target;
    if (!t) return;
    const tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea') {
        if (t.disabled || t.readOnly) return;
        if (t.id === 'locPickerDisplay') return;
        __lastFocusedInput = t;
        const type = (t.getAttribute('type') || '').toLowerCase();
        const selectableTypes = ['', 'text', 'number', 'tel', 'search', 'email', 'url'];
        if (tag === 'textarea' || selectableTypes.includes(type)) {
            setTimeout(() => {
                if (document.activeElement === t && typeof t.select === 'function') {
                    t.select();
                }
            }, 0);
        }
    }
}, true);

function isNumericLikeInput(el) {
    if (!el) return false;
    const type = (el.getAttribute('type') || '').toLowerCase();
    const inputmode = (el.getAttribute('inputmode') || '').toLowerCase();
    const pattern = (el.getAttribute('pattern') || '');
    return type === 'number' || inputmode === 'numeric' || /\d/.test(pattern);
}

function parseSpokenNumberKo(text) {
    const raw = (text || '').toString().trim();
    if (!raw) return null;

    // Normalize commas/spaces early
    const cleaned = raw.replace(/,/g, '').replace(/\s+/g, '');

    // 1) If explicit digits exist, prefer them (support decimals like "3.5", "12.75")
    // Examples: "3만원" -> 3, "3.5만원" -> 3.5, "12,000.5원" -> 12000.5
    const m = cleaned.match(/-?\d+(?:\.\d+)?/);
    if (m) return m[0].replace(/^(-?)0+(\d)/, '$1$2');

    // 2) Normalize Korean suffixes
    let s = cleaned.replace(/원|개|도|℃|%/g, '');

    // 3) Decimal spoken with "점/쩜"
    // Examples: "삼점일사" -> 3.14, "오천점오" -> 5000.5, "0점5" -> 0.5
    const decSplit = s.split(/(?:점|쩜|\.)/);
    const hasDec = decSplit.length >= 2;

    const parseIntegerKo = (part) => {
        if (!part) return null;

        // If digits are present inside part, use them
        const mm = part.match(/-?\d+/);
        if (mm) return parseInt(mm[0], 10);

        const digitMap = {
            '영':0,'공':0,'일':1,'이':2,'삼':3,'사':4,'오':5,'육':6,'칠':7,'팔':8,'구':9,
            '하나':1,'둘':2,'셋':3,'넷':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9
        };
        const smallUnit = { '십':10, '백':100, '천':1000 };
        const bigUnit = { '만':10000, '억':100000000 };

        const tokens = [];
        for (let i = 0; i < part.length; ) {
            const three = part.slice(i, i+3);
            const two = part.slice(i, i+2);
            if (digitMap.hasOwnProperty(three)) { tokens.push(three); i += 3; continue; }
            if (digitMap.hasOwnProperty(two)) { tokens.push(two); i += 2; continue; }
            tokens.push(part[i]); i += 1;
        }

        let total = 0;
        let section = 0;
        let number = 0;

        const flushNumber = () => { section += number; number = 0; };

        for (const t of tokens) {
            if (digitMap.hasOwnProperty(t)) { number = digitMap[t]; continue; }
            if (smallUnit.hasOwnProperty(t)) {
                const u = smallUnit[t];
                const n = (number === 0 ? 1 : number);
                section += n * u;
                number = 0;
                continue;
            }
            if (bigUnit.hasOwnProperty(t)) {
                flushNumber();
                const u = bigUnit[t];
                const n = (section === 0 ? 1 : section);
                total += n * u;
                section = 0;
                number = 0;
                continue;
            }
        }
        flushNumber();
        total += section;

        return isNaN(total) ? null : total;
    };

    const intPartRaw = decSplit[0] || '';
    const intVal = parseIntegerKo(intPartRaw);
    if (intVal === null) return null;

    if (!hasDec) {
        return String(intVal);
    }

    // Fractional part: interpret digits one-by-one (삼점일사 -> 3.14)
    let fracRaw = (decSplit.slice(1).join('') || '');
    if (!fracRaw) return String(intVal);

    // Convert Korean digit words in fractional part to digit characters
    const fracDigitMap = {
        '영':'0','공':'0','일':'1','이':'2','삼':'3','사':'4','오':'5','육':'6','칠':'7','팔':'8','구':'9',
        '하나':'1','둘':'2','셋':'3','넷':'4','다섯':'5','여섯':'6','일곱':'7','여덟':'8','아홉':'9'
    };

    const fracTokens = [];
    for (let i = 0; i < fracRaw.length; ) {
        const three = fracRaw.slice(i, i+3);
        const two = fracRaw.slice(i, i+2);
        if (fracDigitMap.hasOwnProperty(three)) { fracTokens.push(three); i += 3; continue; }
        if (fracDigitMap.hasOwnProperty(two)) { fracTokens.push(two); i += 2; continue; }
        fracTokens.push(fracRaw[i]); i += 1;
    }

    let fracDigits = '';
    for (const t of fracTokens) {
        if (fracDigitMap.hasOwnProperty(t)) { fracDigits += fracDigitMap[t]; continue; }
        if (/\d/.test(t)) { fracDigits += t; continue; }
        // ignore units/suffixes in fractional part
    }

    if (!fracDigits.length) return String(intVal);
    // remove trailing zeros? keep as-is for precision
    return String(intVal) + '.' + fracDigits;
}

// =========================
// Voice Mode (Mobile)
// - Toggle ON: tap an input/textarea to select target WITHOUT opening keyboard
// - Speech recognition runs once, fills target. Voice mode stays ON until user toggles OFF.
// =========================
let __voiceModeOn = false;
let __voiceActiveEl = null;
let __voiceRecog = null;

function updateVoiceModeButton() {
    const setBtn = (id) => {
        const b = document.getElementById(id);
        if (!b) return;
        const span = b.querySelector('span');
        if (span) span.textContent = __voiceModeOn ? '음성 ON' : '음성 OFF';
        b.classList.toggle('is-on', __voiceModeOn);
        b.setAttribute('aria-pressed', __voiceModeOn ? 'true' : 'false');
    };

    setBtn('voiceModeBtn');
    setBtn('modalVoiceModeBtn');
    setBtn('zoomVoiceBtn'); // ★ 새로 추가된 위젯 버튼 동기화
}

function clearVoiceTarget() {
    if (__voiceActiveEl) __voiceActiveEl.classList.remove('voice-target');
    __voiceActiveEl = null;
}

function stopVoiceRecognition() {
    try { if (__voiceRecog) __voiceRecog.stop(); } catch(e) {}
    __voiceRecog = null;
}

function isNumericField(el) {
    if (!el) return false;
    const type = (el.getAttribute('type') || '').toLowerCase();
    const inputmode = (el.getAttribute('inputmode') || '').toLowerCase();
    const pattern = (el.getAttribute('pattern') || '');
    return type === 'number' || inputmode === 'numeric' || /\d/.test(pattern);
}

function applyVoiceTextToElement(el, text) {
    if (!el) return;
    const t = (text || '').trim();
    if (!t) return;

    if (isNumericField(el)) {
        const n = parseSpokenNumberKo(t);
        if (n !== null) el.value = n;
        else el.value = (t.replace(/[^0-9]/g,'') || '');
    } else {
        el.value = t;
    }
    try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch(e) {}
    try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch(e) {}
}

function startOneShotVoiceRecognition(targetEl) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        try { showToast('이 기기에서 음성 인식을 지원하지 않아요'); } catch(e) { alert('이 기기에서 음성 인식을 지원하지 않아요'); }
        toggleVoiceMode(false);
        return;
    }

    stopVoiceRecognition();

    const recog = new SpeechRecognition();
    __voiceRecog = recog;
    let hadResult = false;

    recog.lang = 'ko-KR';
    recog.maxAlternatives = 1;
    recog.continuous = false;
    recog.interimResults = false;

    recog.onresult = function(evt) {
        hadResult = true;
        try {
            const transcript = evt.results[0][0].transcript || '';
            applyVoiceTextToElement(targetEl, transcript);
            try { showToast('음성 입력 완료'); } catch(e) {}
        } finally {
            // 결과 입력 후에는 인식 세션만 종료하고, 음성모드는 유지(사용자가 토글로 OFF)
            stopVoiceRecognition();
            clearVoiceTarget();
            updateVoiceModeButton();
        }
    };

    recog.onerror = function(evt) {
        // 'no-speech' 등은 즉시 OFF하지 않고 ON 유지(재시도 가능)
        const err = (evt && evt.error) ? evt.error : '';
        if (err === 'no-speech' || err === 'aborted') {
            try { showToast('음성이 감지되지 않았어요. 다시 탭해서 말해 주세요'); } catch(e) {}
            stopVoiceRecognition();
            return;
        }
        // 그 외 오류도 음성모드는 유지(사용자가 토글로 제어)
        try { showToast('음성 인식 오류: ' + err); } catch(e) {}
        stopVoiceRecognition();
    };

    recog.onend = function() {
        // 결과 없이 끝난 경우(무음/취소 등)에는 ON을 유지해서 다시 시도 가능
        if (!hadResult && __voiceModeOn) {
            try { showToast('음성 인식이 끝났어요. 입력칸을 다시 탭해서 재시도해 주세요'); } catch(e) {}
            stopVoiceRecognition();
            return;
        }
        stopVoiceRecognition();
    };

    try { recog.start(); } catch(e) { toggleVoiceMode(false); }
}


function initVoiceMode() {
    updateVoiceModeButton();

    if (document.__voiceCaptureBound) return;
    document.__voiceCaptureBound = true;

    // 터치 스크롤 중 실수로 인식이 시작되는 문제를 줄이기 위해
    // touchstart → touchend 탭 판정(이동량 작을 때만)으로 처리
    let candidateEl = null;
    let sx = 0, sy = 0;
    let moved = false;
    let startedAt = 0;

    const findEligible = (t) => {
        const el = t && t.closest ? t.closest('input, textarea') : null;
        if (!el) return null;
        if (el.disabled || el.readOnly) return null;
        return el;
    };

    const onTouchStart = function(e) {
        if (!__voiceModeOn) return;
        const el = findEligible(e.target);
        if (!el) return;

        // 후보만 잡아두고, 실제 시작은 touchend에서
        candidateEl = el;
        const touch = e.touches && e.touches[0];
        sx = touch ? touch.clientX : 0;
        sy = touch ? touch.clientY : 0;
        moved = false;
        startedAt = Date.now();
    };

    const onTouchMove = function(e) {
        if (!__voiceModeOn || !candidateEl) return;
        const touch = e.touches && e.touches[0];
        if (!touch) return;
        const dx = Math.abs(touch.clientX - sx);
        const dy = Math.abs(touch.clientY - sy);
        if (dx > 10 || dy > 10) moved = true;
    };

    const onTouchEnd = function(e) {
        if (!__voiceModeOn || !candidateEl) return;

        const el = candidateEl;
        candidateEl = null;

        // 스크롤/드래그로 판단되면 시작하지 않음
        if (moved) return;

        // 너무 오래 누른 경우(롱프레스 등)도 제외
        if (Date.now() - startedAt > 900) return;

        // 포커스(키보드) 방지
        e.preventDefault();
        e.stopPropagation();

        clearVoiceTarget();
        __voiceActiveEl = el;
        el.classList.add('voice-target');

        startOneShotVoiceRecognition(el);
    };

    // 데스크톱(마우스)은 기존 방식 유지
    const onMouseDown = function(e) {
        if (!__voiceModeOn) return;
        const el = findEligible(e.target);
        if (!el) return;

        e.preventDefault();
        e.stopPropagation();

        clearVoiceTarget();
        __voiceActiveEl = el;
        el.classList.add('voice-target');

        startOneShotVoiceRecognition(el);
    };

    document.addEventListener('touchstart', onTouchStart, true);
    document.addEventListener('touchmove', onTouchMove, true);
    document.addEventListener('touchend', onTouchEnd, true);
    document.addEventListener('mousedown', onMouseDown, true);
}

function startGlobalDictationForFocusedInput() {
    const target = __lastFocusedInput;
    if (!target) {
        try { showMobileToast('입력칸을 먼저 선택해 주세요'); } catch(e) { alert('입력칸을 먼저 선택해 주세요'); }
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        try { showMobileToast('이 기기에서 음성 인식을 지원하지 않아요'); } catch(e) { alert('음성 인식을 지원하지 않아요'); }
        return;
    }

    const recog = new SpeechRecognition();
    recog.lang = 'ko-KR';
    recog.maxAlternatives = 1;
    recog.continuous = false;
    recog.interimResults = false;

    target.classList.add('dictating');

    recog.onresult = (event) => {
        const transcript = (event?.results?.[0]?.[0]?.transcript || '').trim();
        if (!transcript) return;

        if (isNumericLikeInput(target)) {
            const num = parseSpokenNumberKo(transcript);
            target.value = (num !== null) ? num : transcript;
            target.dispatchEvent(new Event('input', { bubbles: true }));
            return;
        }

        const prev = (target.value || '').trim();
        target.value = prev ? (prev + ' ' + transcript) : transcript;
        target.dispatchEvent(new Event('input', { bubbles: true }));
    };

    recog.onend = () => {
        target.classList.remove('dictating');
        try { target.focus(); } catch(e) {}
    };
    recog.onerror = () => {
        target.classList.remove('dictating');
    };

    try { recog.start(); } catch(e) {
        target.classList.remove('dictating');
    }
}



function syncMobileTabs(activeIndex) {
    const root = document.getElementById('mobileSwiperRoot');
    if (!root) return;
    const tabs = root.querySelectorAll('.mobile-swiper-tabs .m-tab');
    tabs.forEach(btn => {
        const idx = parseInt(btn.getAttribute('data-index'));
        const isActive = idx === activeIndex;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    // 기록 탭으로 들어오면 뱃지 초기화
    if (activeIndex === 3) setLogBadge(0);
}

// 2. 작업기록 필터링 함수 (원본 로직 완벽 반영)
function filterHistory(type, btn) {
    // (1) 탭 버튼 스타일 업데이트
    document.querySelectorAll('.h-tab').forEach(function(tab) {
        tab.classList.remove('active');
        // 강제로 스타일 초기화 (CSS 클래스가 안 먹힐 경우 대비)
        tab.style.borderBottom = "none";
        tab.style.color = "#888";
        tab.style.fontWeight = "normal";
    });

    if (btn) {
        btn.classList.add('active');
        btn.style.borderBottom = "3px solid #333";
        btn.style.color = "#333";
        btn.style.fontWeight = "bold";
    }

    // (2) 리스트 항목 필터링
    var rows = document.querySelectorAll('.history-row');
    rows.forEach(function(row) {
        var rowType = row.getAttribute('data-type');
        var isVisible = false;

        if (type === '상태') {
            // '상태' 탭에서 보여줄 모든 시스템 로그 타입
            const statusTypes = ['상태변경', '결제', '정보수정', '일정변경', '현장체크', '서명완료'];
            isVisible = statusTypes.includes(rowType);
        } else {
            // '메모' 탭에서 보여줄 항목 (전화, 문자 포함)
            const memoTypes = ['메모', '전화', '문자'];
            isVisible = memoTypes.includes(rowType);
        }

        // flex 레이아웃 유지하며 보임/숨김 처리
        row.style.display = isVisible ? 'flex' : 'none';
    });
}

function initPage() {
    // 1. 기본 카테고리 설정
    if (typeof changeCategory === 'function') changeCategory(getDefaultItemCategory());

    // 2. 블라인드 창 개수 선택 버튼 생성
    if (typeof renderBlindButtons === 'function') renderBlindButtons(); 

    // 3. 발주처별 주문 복사 버튼 생성
    if (typeof renderSupplierButtons === 'function') renderSupplierButtons();

    // 4. 테이블 내 블라인드 사이즈 줄바꿈 처리 및 금액 계산
    if (typeof renderBlindListSizes === 'function') renderBlindListSizes();
    if (typeof calcFinalPrice === 'function') calcFinalPrice();

    // 5. 일정/달력 라이브러리(flatpickr) 초기화
    initCalendar(); 

    // ★ [핵심 추가] 하단 작업기록 퀵바 이벤트를 무조건 강제 연결!
    if (typeof bindMobileWorklogBar === 'function') {
        bindMobileWorklogBar();
    }
}

/* [view_ui.js] initPage 함수 (공통 함수 사용으로 코드 최적화) */
function initCalendar() {
    var dateInput = document.getElementById('modalDateInput');
    if (dateInput) {
        g_fpInstance = flatpickr(dateInput, {
            locale: "ko",
            enableTime: true,
            dateFormat: "Y-m-d H:i",
            inline: true,
            onChange: function(selectedDates, dateStr, instance) {
                var con = document.getElementById('sameDayScheduleList');
                if (!con) return;

                con.innerHTML = '<div style="padding:10px; color:#666;"><i class="fas fa-spinner fa-spin"></i> 조회 중...</div>';
                var ymd = dateStr.split(' ')[0];

                fetch('/api/schedule/check-date?date=' + ymd)
                    .then(res => res.json())
                    .then(data => {
                        if (!data || data.length === 0) {
                            con.innerHTML = '<div style="font-size:0.85rem; color:#999; text-align:center; padding:10px;">일정 없음</div>';
                            return;
                        }

                        // ★ [핵심 수정] 여기서도 현재 주문은 제외하고 렌더링
                        // [Reason] 데이터 일관성을 위해 동일하게 필터링 적용
                        var filtered = data.filter(evt => String(evt.id) !== String(g_orderId));
                        
                        if (filtered.length === 0) {
                            con.innerHTML = '<div style="font-size:0.85rem; color:#999; text-align:center; padding:10px;">다른 일정 없음</div>';
                            return;
                        }

                        var html = filtered.map(evt => makeScheduleItemHtml(evt)).join('');
                        con.innerHTML = html;
                    });
            }
        });
    }
}

window.addEventListener('load', function() {
    setTimeout(function() {
        if(typeof renderBlindListSizes === 'function') renderBlindListSizes();
    }, 100);
});

// 3. 발주처 버튼 렌더링
function renderSupplierButtons() {
    var container = document.getElementById('supplierBtnContainer');
    if (!container) return;
    
    var rows = document.querySelectorAll('.excel-table tbody tr');
    var suppliers = new Set();
    var hasEmptySup = false;
    
    rows.forEach(function(row) {
        var sup = row.getAttribute('data-sup');
        if (sup && sup.trim() !== "") suppliers.add(sup);
        else hasEmptySup = true;
    });
    
    var html = "";
    suppliers.forEach(function(sup) {
        html += `<button type="button" class="btn" style="background:#17a2b8; font-size:13px !important;" onclick="copySmart('supplier', '${sup}')">
            <i class="far fa-copy"></i> ${sup} 주문
         </button>`;
    });

    if (hasEmptySup) {
        html += `<button type="button" class="btn" style="background:#6c757d; font-size:13px !important;" onclick="copySmart('empty', '')">
                    <i class="fas fa-question-circle"></i> 발주처 미기입 주문
                 </button>`;
    }
    container.innerHTML = html;
}

// 4. 스마트 복사
function copySmart(type, targetVal) {
    var cName = document.getElementById('srv-cust-name')?.value || '고객';
    var header = (type === 'supplier') ? targetVal : '미지정';
    var clipText = `[${header}] ${cName}\n----------------------------------------\n`;
    
    var rows = document.querySelectorAll('.excel-table tbody tr');
    var count = 0;

    rows.forEach(function(row) {
        var btn = row.querySelector('.btn-edit');
        if (!btn) return;

        var rowSup = btn.getAttribute('data-sup') || "";
        var isMatch = false;
        if (type === 'supplier') {
            if (rowSup === targetVal) isMatch = true;
        } else if (type === 'empty') {
            if (!rowSup || rowSup.trim() === "") isMatch = true;
        }

        if (isMatch) {
            count++;
            var cat = btn.getAttribute('data-cat');
            var loc = btn.getAttribute('data-loc') || "";
            var sub = btn.getAttribute('data-sub') || "";
            var prod = btn.getAttribute('data-prod') || "";
            var color = btn.getAttribute('data-color') || "";
            var opt = btn.getAttribute('data-opt') || "";
            var qty = btn.getAttribute('data-qty') || "0";
            
            if (getItemCategoryMode(cat) === 'blind') {
                var bSize = btn.getAttribute('data-bsize') || "";
                var bCount = btn.getAttribute('data-bcount') || "";
                var line = `${loc}`;
                if (sub && sub.trim() !== "") line += ` | ${sub}`;
                line += ` | ${prod}`;
                if (color) line += ` | ${color}`;
                if (opt) line += ` | ${opt}`;
                line += ` | `; 

                if (bSize) {
                    var formattedSize = bSize.split(',').map(s => s.trim()).join(',\n');
                    line += `\n${formattedSize}`;
                }
                if (bCount && parseInt(bCount) > 1) {
                    line += `\n(${bCount}\uCC3D)`;
                }
                clipText += line + "\n";
            } 
            else {
                var rawW = btn.getAttribute('data-w') || "0";
                var rawH = btn.getAttribute('data-copy-h') || btn.getAttribute('data-h') || "0";
                var smartW = parseFloat(rawW);
                var smartH = parseFloat(rawH);
                var unit = getItemCategoryUnit(cat);
                var smartQty = parseFloat(qty);

                var line = `${loc}`;
                if (sub) line += ` | ${sub}`;
                line += ` | ${prod}`;
                if (color) line += ` | ${color}`;
                if (opt) line += ` | ${opt}`;
                line += ` | ${smartQty}${unit}`;
                line += ` | ${smartW} x ${smartH}`;
                clipText += line + "\n";
                // [Reason] 커튼은 비고(data-memo)를 발주처 주문 복사에 포함
                if (getItemCategoryMode(cat) === 'curtain') {
                    var memo = btn.getAttribute('data-memo') || "";
                    if (memo && memo.trim() !== "") clipText += `  · 비고: ${memo}
`;
                }
            }
        }
    });

    if (count === 0) { alert("복사할 항목이 없습니다."); return; }

    var cDate = document.getElementById('srv-const-date')?.value || '미정';
    clipText += "----------------------------------------\n";
    clipText += `[시공예정] : ${cDate}\n`;

    copyToClipboard(clipText);
}


function copyItemInfo(cat, sub, loc, prod, color, opt, unit, w, h) {
    var text = "";
    if (getItemCategoryMode(cat) === 'blind') {
        var sizeText = String(w).replace(/,\s*/g, ",\n");
        text = loc;
        if (sub && sub !== 'undefined' && sub.trim() !== "") text += ` | ${sub}`;
        text += ` | ${prod}`;
        if (color) text += ` | ${color}`;
        if (opt) text += ` | ${opt}`;
        text += ` | \n${sizeText}`;
    } else {
        var smartW = parseFloat(w);
        var smartH = parseFloat(h);
        var sizeText = `${smartW} x ${smartH}`;
        var cleanUnit = String(unit).replace(/\.0+([가-힣a-zA-Z]+)/, "$1");
        var parts = [loc, prod];
        if (color) parts.push(color);
        if (opt) parts.push(opt);
        text = `${parts.join(' | ')} | ${cleanUnit} | ${sizeText}`;
    }
    executeCopy(text);
}

const ITEM_FIELD_LABELS = {
    default: { cate1: '제품명', cate2: '칼라', cate3: '옵션', cate4: '비고' },
    '커튼': { cate1: '제품명', cate2: '칼라', cate3: '옵션', cate4: '비고' },
    '블라인드': { cate1: '제품명', cate2: '칼라', cate3: '옵션', cate4: '비고' },
    '청소': { cate1: '작업명', cate2: '구역/재질', cate3: '방식', cate4: '특이사항' },
    '바닥': { cate1: '제품/작업명', cate2: '재질/칼라', cate3: '시공방식', cate4: '비고' },
    '도배': { cate1: '제품명', cate2: '칼라/패턴', cate3: '옵션', cate4: '비고' },
    '장판': { cate1: '제품명', cate2: '칼라/톤', cate3: '옵션', cate4: '비고' },
    '샤시': { cate1: '제품명', cate2: '칼라', cate3: '옵션', cate4: '비고' },
    '방충망': { cate1: '제품명', cate2: '망 종류', cate3: '옵션', cate4: '비고' },
    '인테리어': { cate1: '작업명', cate2: '재질/톤', cate3: '옵션', cate4: '비고' }
};

const ITEM_CATEGORY_MODE_MAP = Object.assign({
    '커튼': 'curtain',
    '블라인드': 'blind',
    '기타': 'generic'
}, window.ITEM_CATEGORY_MODES || {});

const ITEM_CATEGORY_UNIT_MAP = {
    '커튼': '폭',
    '블라인드': '㎡'
};

function getItemCategoryMode(cat) {
    const key = String(cat || '').trim();
    if (!key) return 'generic';
    return ITEM_CATEGORY_MODE_MAP[key] || 'generic';
}

function getItemCategoryUnit(cat) {
    const key = String(cat || '').trim();
    return ITEM_CATEGORY_UNIT_MAP[key] || '';
}

function getDefaultItemCategory() {
    const list = Array.isArray(window.ITEM_CATEGORIES) ? window.ITEM_CATEGORIES : [];
    if (list.length > 0) {
        return String(list[0] || '').trim() || '커튼';
    }
    return '커튼';
}

function getItemFieldLabels(cat) {
    return ITEM_FIELD_LABELS[cat] || ITEM_FIELD_LABELS.default;
}

// 5. 블라인드 버튼 및 UI 렌더링
function renderBlindButtons() {
    var html = '<div class="blind-btns">';
    for(var i=1; i<=6; i++) html += `<button type="button" class="btn-blind-num" id="bBtn_${i}" onclick="setBlindCount(${i})">${i}</button>`;
    html += '</div><select id="blindSelect" class="blind-select" onchange="setBlindCount(this.value)">';
    for(var j=7; j<=20; j++) html += `<option value="${j}">${j}</option>`;
    html += `</select>`;
    document.getElementById('blindBtnGroup').innerHTML = html;
}

function setBlindCount(cnt) {
    cnt = parseInt(cnt); 
    if(!cnt) return;

    var currentItems = [];
    var prevCount = parseInt(document.getElementById('blindSplit').value) || 0;
    
    var mProd = document.getElementById('Master_Prod')?.value || "";
    var mColor = document.getElementById('Master_Color')?.value || "";
    var mOpt = document.getElementById('Master_Opt')?.value || "";
    var mPrice = document.getElementById('Master_Price')?.value || "";
    var mMemo = document.getElementById('Master_Memo')?.value || "";

    var mSupplier = document.getElementById('Master_Supplier')?.value || "";
    var mCost = document.getElementById('Master_CostPrice')?.value || "";
    if (prevCount > 0) {
        for(var i=1; i<=prevCount; i++) {
            var w = document.getElementById('RawW_' + i)?.value || "";
            var h = document.getElementById('RawH_' + i)?.value || "";
            var q = document.getElementById('Qty_' + i)?.value || "";
            var handle = document.getElementById('Handle_' + i)?.value || "\uC6B0";
            var cord = document.getElementById('CordLen_' + i)?.value || "150";
            var id = document.querySelector(`input[name="ItemID_${i}"]`)?.value || "";

            currentItems.push({
                w: w, h: h, q: q,
                handle: handle, cord: cord, id: id,
                prod: mProd, color: mColor, opt: mOpt, p: cleanNum(mPrice), memo: mMemo,
                supplier: mSupplier, attributes: { cost_price: cleanNum(mCost) }
            });
        }
    }

    document.getElementById('blindSplit').value = cnt;
    document.querySelectorAll('.btn-blind-num').forEach(b => b.classList.remove('active'));
    document.getElementById('blindSelect').classList.remove('active');
    
    if(cnt <= 5) {
        var btn = document.getElementById('bBtn_' + cnt);
        if(btn) btn.classList.add('active');
        document.getElementById('blindSelect').value = "";
    } else {
        var sel = document.getElementById('blindSelect');
        sel.value = cnt;
        sel.classList.add('active');
    }

    if (cnt > currentItems.length) {
        var lastH = currentItems.length > 0 ? currentItems[currentItems.length-1].h : "";
        for (var k = currentItems.length; k < cnt; k++) {
            currentItems.push({
                w: "", h: lastH, q: "",
                handle: "\uC6B0",
                cord: "150",
                prod: mProd, color: mColor, opt: mOpt, p: cleanNum(mPrice), memo: mMemo,
                supplier: mSupplier, attributes: { cost_price: cleanNum(mCost) }
            });
        }
    }

    if (cnt > 1 && currentItems.length > 0) {
        currentItems[0].handle = "좌";
    } else if (cnt === 1 && currentItems.length > 0) {
        currentItems[0].handle = "우";
    }

    var container = document.getElementById('dynamicArea');
    (window.__itemMasterRenderBlindUI || renderBlindUI)(container, cnt, currentItems);
    
    setTimeout(function() {
        if(typeof updateBlindAggregates === 'function') updateBlindAggregates();
    }, 10);
}

// [view_ui.js] 카테고리 전환 함수 수정
function changeCategory(cat, options) {
    options = options || {};
    var skipRender = !!options.skipRender;
    var forceRender = !!options.forceRender;
    var mode = getItemCategoryMode(cat);

    var hiddenInput = document.getElementById('catSelect');
    if (hiddenInput) hiddenInput.value = cat;

    if (typeof syncCategoryUI === 'function') {
        syncCategoryUI(cat);
    } else {
        document.querySelectorAll('.btn-cat-type').forEach(function(btn) {
            if (btn.innerText.trim() === cat) btn.classList.add('active');
            else btn.classList.remove('active');
        });
    }

    var info = document.getElementById('calcInfoBox');
    if (info) info.style.display = (mode === 'blind') ? 'none' : 'block';
    if (mode === 'generic') {
        var etcInput = document.getElementById('inpEtcKind');
        if (etcInput && !skipRender) etcInput.value = String(cat || '').trim() || '기타';
    }

    var hidItem = document.getElementById('hidItemID');
    var isEditMode = !!(hidItem && hidItem.value);
    if (!skipRender && (forceRender || !isEditMode)) renderRows();
}

function renderRows() {
    var cat = document.getElementById('catSelect').value;
    var mode = getItemCategoryMode(cat);
    var container = document.getElementById('dynamicArea');
    var html = "";
    var rowRenderer = window.__itemMasterMakeRowHTML || makeRowHTML;
    var blindRenderer = window.__itemMasterRenderBlindUI || renderBlindUI;

    if (mode === 'curtain') {
        var type = document.querySelector('input[name="CurtainType"]:checked').value;
        if (type === 'mix') {
            html += rowRenderer(1, '속지', 'label-inner', '나비주름(2배)', null, '속지');
            html += rowRenderer(2, '겉지', 'label-outer', '평식(형상)', null, '겉지');
        } else if (type === 'outer') {
            html += rowRenderer(1, '겉지', 'label-outer', '평식(형상)', null, '겉지');
        } else {
            html += rowRenderer(1, '속지', 'label-inner', '나비주름(2배)', null, '속지');
        }
        container.innerHTML = html;
    } else if (mode === 'blind') {
        var cnt = parseInt(document.getElementById('blindSplit').value);
        blindRenderer(container, cnt, null);
    } else {
        var genericInput = document.getElementById('inpEtcKind');
        var genericLabel = String((genericInput && genericInput.value) || cat || '').trim() || '기타';
        html += rowRenderer(1, genericLabel, 'label-badge', '', null, genericLabel);
        container.innerHTML = html;
    }
}

function renderBlindUI(container, count, items) {
    g_blindHeightState = {}; 
    window.g_blindCordState = {}; // ★ 줄길이 수동 입력 상태 저장
    var labels = getItemFieldLabels('블라인드');
    var mProd="", mColor="", mOpt="", mPrice="", mMemo="";
    var firstH = ""; 

    if(items && items.length > 0) {
        mProd = items[0].prod || ""; mColor = items[0].color || ""; mOpt = items[0].opt || ""; mPrice = items[0].p || ""; mMemo = items[0].memo || "";
        if(items[0].h) firstH = items[0].h;
    }
    
    var subCatVal = document.getElementById('blindSubKind') ? document.getElementById('blindSubKind').value : "콤비";
    var hasLBracket = (mOpt && mOpt.indexOf("[ㄱ자 꺽쇠]") > -1);

    var html = `
    <input type="hidden" name="BlindSize" id="TotalBlindSize" value="">
    <input type="hidden" name="BlindQty" id="TotalBlindQty" value="">
    
    <div style="margin-top:10px;">
        <div class="size-layout">
            <div style="flex:1;">
                <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:5px;">
                    <div style="font-size:13px; font-weight:bold; color:#666;">📐 창별 사이즈 (<span style="color:#007bff;">가로 x 세로</span>)</div>
                    <label style="font-size:12px; cursor:pointer; display:flex; align-items:center; gap:3px; background:#f8f9fa; padding:2px 6px; border-radius:4px; border:1px solid #ddd; margin:0;">
                        <input type="checkbox" id="chkLBracket" onchange="toggleLBracket(this)" ${hasLBracket ? 'checked' : ''}>
                        <span style="font-weight:bold; color:#d63384;">ㄱ자 꺽쇠</span>
                    </label>
                </div>
                <div class="w-grid" style="display:flex; flex-direction:column; gap:6px;">`;

    for(var i=1; i<=count; i++) {
        var valW="", valH="", valID="", valQty="", valHandle="우", valCord="150";
        if (count > 1 && i === 1) valHandle = "좌";

        if(items && items[i-1]) {
            var it = items[i-1];
            valID = it.id || "";
            valW = (it.w && !isNaN(it.w)) ? parseFloat(it.w) : "";
            valH = (it.h && !isNaN(it.h)) ? parseFloat(it.h) : "";
            valQty = (it.q && !isNaN(it.q)) ? parseFloat(it.q) : "";
            valHandle = it.handle || valHandle;
            valCord = it.cord || "150"; 
        } else {
            valH = (firstH && !isNaN(firstH)) ? parseFloat(firstH) : "";
        }

        if(valW === 0) valW = ""; if(valH === 0) valH = ""; if(valQty === 0) valQty = "";

        var evtCalc = `oninput="calcBlindRowArea(${i}); updateBlindAggregates();"`;

        var evtHeight = (i === 1) 
            ? `oninput="syncBlindHeight(this.value); calcBlindRowArea(1); updateBlindAggregates();"` 
            : `oninput="g_blindHeightState[${i}]=true; calcBlindRowArea(${i}); updateBlindAggregates();"`;
        var highlightStyle = (i === 1) ? "color:#007bff; border-color:#007bff;" : "";

        // ★ 줄길이 1번 입력 시 아래로 자동 복사 이벤트
        var evtCord = (i === 1)
            ? `oninput="syncBlindCord(this.value); updateBlindAggregates();"`
            : `oninput="window.g_blindCordState[${i}]=true; updateBlindAggregates();"`;

        html += `
        <div class="w-item" style="display:flex; align-items:center; gap:5px;">
            <span style="font-size:12px; color:#888; width:15px; text-align:center; flex-shrink:0;">${i}</span>
            <input type="number" step="0.1" name="W_${i}" id="RawW_${i}" class="inp-size" value="${valW}" placeholder="W" style="flex:1; min-width:65px; text-align:center; font-weight:bold;" ${evtCalc} onfocus="this.select()">
            <span style="color:#ccc; font-size:12px; flex-shrink:0;">x</span>
            <input type="number" step="0.1" name="H_${i}" id="RawH_${i}" class="inp-size" value="${valH}" placeholder="H" style="flex:1; min-width:65px; text-align:center; font-weight:bold; ${highlightStyle}" ${evtHeight} onfocus="this.select()">
            <select id="Handle_${i}" onchange="updateBlindAggregates()" style="width:50px; height:34px; font-size:12px; font-weight:bold; border:1px solid #ced4da; border-radius:4px; text-align:center; flex-shrink:0;">
                <option value="좌" ${valHandle==='좌'?'selected':''}>좌</option>
                <option value="우" ${valHandle==='우'?'selected':''}>우</option>
            </select>
            <div style="position:relative; width:65px; flex-shrink:0;">
                <span style="position:absolute; left:6px; top:50%; transform:translateY(-50%); font-size:11px; color:#888; pointer-events:none;">줄</span>
                <input type="text" id="CordLen_${i}" value="${valCord}" style="width:100%; height:34px; text-align:center; font-size:12px; border:1px solid #ced4da; border-radius:4px; font-weight:bold;" ${evtCord} onfocus="this.select()">
            </div>
            <div style="width:75px; flex-shrink:0;">
                <input type="number" step="0.01" name="Qty_${i}" id="Qty_${i}" class="inp-area-mini" value="${valQty}" placeholder="㎡" style="width:100%; text-align:center; background:#f8f9fa; border:1px solid #e9ecef; color:#007bff; font-weight:bold; height:34px; border-radius:4px;" oninput="calcBlindTotalPrice(); updateBlindAggregates();" onfocus="this.select()">
            </div>
            <input type="hidden" name="RowIdx" value="${i}">
            <input type="hidden" name="ItemID_${i}" value="${valID}">
            <input type="hidden" name="SubCat_${i}" value="${subCatVal}">
            <input type="hidden" name="ProdName_${i}" class="sync-prod" value="${mProd}">
            <input type="hidden" name="Color_${i}" class="sync-color" value="${mColor}">
            <input type="hidden" name="Option_${i}" class="sync-opt" value="${mOpt}">
            <input type="hidden" name="Price_${i}" class="sync-price" value="${mPrice}">
            <input type="hidden" name="Memo_${i}" class="sync-memo" value="${mMemo}">
        </div>`;
    }
    
    html += `</div></div></div>
    <div class="common-box" style="margin-top:15px;">
        <div class="common-title" style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-weight:bold; color:#333;"><i class="fas fa-bullhorn"></i> 공통 정보</span>
            <div style="display:flex; align-items:center; gap:10px;">
                <span id="blindRealtimeTotal" style="color:#d63384; font-size:1.1em; font-weight:800; cursor:pointer;" onclick="triggerBlindMarginPopup(this)">0원</span>
            </div>
        </div>
        <div class="common-row" style="display:flex; gap:5px; margin-bottom:5px;">
            <input type="text" id="Master_Prod" class="inp-prod" placeholder="${labels.cate1}" value="${mProd}" style="flex:1.2; font-weight:bold; position:relative;" onkeyup="handleCustomAuto(this)" oninput="syncBlindData(${count}, 'ProdName')" onfocus="handleCustomAuto(this); this.select()" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
            <input type="text" id="Master_Color" class="inp-color" placeholder="${labels.cate2}" value="${mColor}" style="flex:0.8;" oninput="syncBlindData(${count}, 'Color')" onfocus="this.select()">
        </div>
        <div class="common-row" style="display:flex; gap:5px; margin-bottom:5px;">
            <input type="text" id="Master_Opt" class="sel-opt" placeholder="${labels.cate3}" value="${mOpt}" style="flex:1;" oninput="syncBlindData(${count}, 'Option')" onfocus="this.select()">
            <input type="text" inputmode="numeric" id="Master_Price" class="inp-price" placeholder="단가" value="${formatComma(mPrice)}" style="flex:0.8; border:2px solid #ffc107;" oninput="this.value=formatComma(this.value); syncBlindData(${count}, 'Price')" onfocus="this.select()">
            <input type="text" id="Master_Memo" class="inp-memo" placeholder="${labels.cate4}" value="${mMemo}" style="flex:1.2;" oninput="syncBlindData(${count}, 'Memo')" onfocus="this.select()">
        </div>
    </div>`;
    
    container.innerHTML = html;
    setTimeout(function() { 
        if(typeof calcBlindTotalPrice === 'function') calcBlindTotalPrice(); 
        if(typeof updateBlindAggregates === 'function') updateBlindAggregates(); 
    }, 50);
}

// ★ 줄길이 연쇄 채우기 실행 함수
window.syncBlindCord = function(val) {
    var cnt = parseInt(document.getElementById('blindSplit')?.value) || 1;
    for(var i = 2; i <= cnt; i++) {
        if(!window.g_blindCordState[i]) {
            var el = document.getElementById('CordLen_' + i);
            if(el) el.value = val;
        }
    }
};

function makeRowHTML(idx, label, badgeClass, defOpt, item, subCatVal) {
    var valProd = "", valColor = "", valW = "", valH = "", valQ = "", valP = "", valMemo = "", valID = "";
    defOpt = defOpt || "";

    if(item) {
        valProd = item.prod || "";
        valColor = item.color || "";
        valW = smartFloat(item.w, 1);
        valH = smartFloat(item.h, 1);
        valQ = smartFloat(item.q, 2);
        valP = item.p || "";
        valMemo = item.memo || "";
        valID = item.id || "";
        if(item.subCat) subCatVal = item.subCat;
        else if(item.category1 && !subCatVal) subCatVal = item.category1;
    }
    if(!subCatVal) subCatVal = "";

    var currentCat = document.getElementById('catSelect').value;
    var currentMode = getItemCategoryMode(currentCat);
    var labels = getItemFieldLabels(currentCat);
    var optHtml = "";
    var stepVal = (currentMode === 'curtain') ? "1" : "0.01";

    if (valW !== "") valW = smartFloat(valW, 1);
    if (valH !== "") valH = smartFloat(valH, 1);
    if (valQ !== "") valQ = smartFloat(valQ, 2);

    if(valW == 0) valW = "";
    if(valH == 0) valH = "";
    if(valQ == 0) valQ = "";
    if(valP == 0) valP = "";

    if(currentMode === 'curtain' && (label.indexOf('속지') > -1 || label.indexOf('겉지') > -1 || label === '수정')) {
        optHtml = `<select name="Option_${idx}" class="sel-opt" onchange="calcQty(${idx})">
            <option value="나비주름(2배)" ${defOpt.indexOf('나비') > -1 && defOpt.indexOf('형상') === -1 ? 'selected' : ''}>나비주름(2배)</option>
            <option value="나비주름+형상" ${defOpt.indexOf('나비') > -1 && defOpt.indexOf('형상') > -1 ? 'selected' : ''}>나비+형상(2배)</option>
            <option value="평식(형상)" ${defOpt.indexOf('평식') > -1 ? 'selected' : ''}>평식(형상)(1.5배)</option>
        </select>`;
    } else {
        optHtml = `<input type="text" name="Option_${idx}" class="sel-opt" placeholder="${labels.cate3}" value="${defOpt}" onfocus="this.select()">`;
    }
    var syncEvent = `oninput="syncInput(this, '${idx}', '${label}')"`;

    return `
    <div class="dynamic-row">
        <input type="hidden" name="RowIdx" value="${idx}">
        <input type="hidden" name="ItemID_${idx}" value="${valID}">
        <input type="hidden" name="SubCat_${idx}" value="${subCatVal}">
        <input type="hidden" name="LocSuffix_${idx}" value="${(label=='속지')?'(속지)':(label=='겉지'?'(겉지)':'')}">
        <div class="row-line-1" style="flex-wrap:wrap;">
            <span class="label-badge ${badgeClass}">${label}</span>
            <input type="text" name="ProdName_${idx}" class="inp-prod" placeholder="${labels.cate1}" value="${valProd}" onkeyup="handleCustomAuto(this)" onfocus="handleCustomAuto(this); this.select()" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" ${syncEvent} style="min-width:110px; position:relative; flex:1.1;">
            <input type="text" name="Color_${idx}" class="inp-color" placeholder="${labels.cate2}" value="${valColor}" onfocus="this.select()" style="min-width:90px; flex:0.8;">
            <div style="flex:1; min-width:110px;">${optHtml.replace('class="sel-opt"', 'class="sel-opt" style="width:100%;"')}</div>
        </div>
        <div class="row-line-2" style="align-items:center;">
            <input type="number" name="W_${idx}" class="inp-size" placeholder="가로" step="0.1" value="${valW}" oninput="syncInput(this, '${idx}', 'W'); calcQty(${idx});" onfocus="this.select()"> x 
            <input type="number" name="H_${idx}" class="inp-size" placeholder="세로" step="0.1" value="${valH}" oninput="syncInput(this, '${idx}', 'H'); calcQty(${idx});" onfocus="this.select()">
            <input type="number" name="Qty_${idx}" id="Qty_${idx}" class="inp-qty" placeholder="수량" step="${stepVal}" value="${valQ}" oninput="calcCurtainEtcTotal('${idx}')" onfocus="this.select()">
            <input type="text" inputmode="numeric" name="Price_${idx}" class="inp-price" placeholder="단가" style="border: 2px solid #ffc107;" value="${formatComma(valP)}" oninput="this.value=formatComma(this.value); syncInput(this, '${idx}', '${label}'); calcCurtainEtcTotal('${idx}')" onfocus="this.select()">
            <input type="text" name="Memo_${idx}" class="inp-memo" placeholder="${labels.cate4}" value="${valMemo}" onfocus="this.select()">
        </div>
        <div id="RowTotal_${idx}" style="font-size:0.9rem; font-weight:bold; color:#d63384; min-width:60px; text-align:right; margin-left:5px; cursor:pointer;" onclick="triggerMarginPopup(this, '${idx}')">0원</div>
    </div>`;
}

// 6. 모달 열기/닫기/수정
function queueModalSuccessFeedback() {
    sessionStorage.setItem('modal_success_feedback', '1');
}

function triggerModalSuccessVibration(pattern) {
    if (!navigator) return false;
    var vibrate = navigator.vibrate || navigator.webkitVibrate || navigator.mozVibrate || navigator.msVibrate;
    if (typeof vibrate !== 'function') return false;
    try {
        return vibrate.call(navigator, pattern || [120, 60, 160]);
    } catch (e) {
        return false;
    }
}

function triggerModalSuccessFeedback(options) {
    if (!document.body) return;
    var opts = options || {};
    var existing = document.getElementById('manualSaveFlashLayer');
    if (existing) existing.remove();

    var flash = document.createElement('div');
    flash.id = 'manualSaveFlashLayer';
    flash.style.position = 'fixed';
    flash.style.inset = '0';
    flash.style.pointerEvents = 'none';
    flash.style.zIndex = '100300';
    flash.style.opacity = '0';
    flash.style.transition = 'opacity 1s ease';
    flash.style.background = 'rgba(0, 55, 175, 0.8)';
    document.body.appendChild(flash);

    requestAnimationFrame(function() {
        flash.style.opacity = '1';
    });

    setTimeout(function() {
        flash.style.opacity = '0';
    }, 140);

    clearTimeout(window.__modalSuccessFlashTimer);
    window.__modalSuccessFlashTimer = setTimeout(function() {
        if (flash.parentNode) flash.parentNode.removeChild(flash);
    }, 200);

    if (!opts.skipVibrate) triggerModalSuccessVibration(opts.pattern);
}

function triggerManualSaveFlash() {
    triggerModalSuccessFeedback();
}

window.__modalBackTrapStack = window.__modalBackTrapStack || [];
window.__modalBackTrapListening = window.__modalBackTrapListening || false;
window.__modalBackTrapSuppress = window.__modalBackTrapSuppress || false;

function isTrackedModalVisible(modalId) {
    var modal = document.getElementById(modalId);
    if (!modal) return false;
    return modal.style.display !== 'none' && window.getComputedStyle(modal).display !== 'none';
}

function handleModalBackTrapPopstate() {
    if (window.__modalBackTrapSuppress) {
        window.__modalBackTrapSuppress = false;
        return;
    }

    var stack = window.__modalBackTrapStack || [];
    while (stack.length > 0) {
        var top = stack[stack.length - 1];
        if (!top || !isTrackedModalVisible(top.modalId)) {
            stack.pop();
            continue;
        }

        var closeFn = typeof window[top.closeFnName] === 'function' ? window[top.closeFnName] : null;
        if (!closeFn) {
            stack.pop();
            return;
        }

        closeFn({ fromHistory: true });
        return;
    }
}

function ensureModalBackTrapListener() {
    if (window.__modalBackTrapListening) return;
    window.addEventListener('popstate', handleModalBackTrapPopstate);
    window.__modalBackTrapListening = true;
}

function registerModalBackTrap(modalId, closeFnName) {
    if (!modalId) return;
    ensureModalBackTrapListener();

    var stack = window.__modalBackTrapStack || [];
    var top = stack.length ? stack[stack.length - 1] : null;
    if (top && top.modalId === modalId) return;

    stack.push({ modalId: modalId, closeFnName: closeFnName });
    history.pushState({
        __modalTrap: true,
        modalId: modalId,
        ts: Date.now()
    }, document.title);
}

function releaseModalBackTrap(modalId, options) {
    var opts = options || {};
    var stack = window.__modalBackTrapStack || [];
    for (var i = stack.length - 1; i >= 0; i -= 1) {
        if (stack[i] && stack[i].modalId === modalId) {
            stack.splice(i, 1);
            break;
        }
    }

    if (opts.fromHistory) return;

    var state = history.state || {};
    if (state.__modalTrap && state.modalId === modalId) {
        window.__modalBackTrapSuppress = true;
        history.back();
        setTimeout(function() {
            window.__modalBackTrapSuppress = false;
        }, 0);
    }
}

function lockManualModalViewport() {
    if (window.innerWidth > 768) return;
    if (document.body.dataset.manualScrollLock === '1') return;

    var scrollY = window.scrollY || window.pageYOffset || 0;
    document.body.dataset.manualScrollLock = '1';
    document.body.dataset.manualScrollTop = String(scrollY);
    document.body.style.position = 'fixed';
    document.body.style.top = '-' + scrollY + 'px';
    document.body.style.left = '0';
    document.body.style.right = '0';
    document.body.style.width = '100%';
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
}

function unlockManualModalViewport() {
    if (document.body.dataset.manualScrollLock !== '1') return;

    var scrollY = parseInt(document.body.dataset.manualScrollTop || '0', 10) || 0;
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.left = '';
    document.body.style.right = '';
    document.body.style.width = '';
    document.body.style.overflow = '';
    document.documentElement.style.overflow = '';
    delete document.body.dataset.manualScrollLock;
    delete document.body.dataset.manualScrollTop;
    window.scrollTo(0, scrollY);
}

function openManualModal(mode) {
    document.getElementById('manualModal').style.display = 'flex';
    lockManualModalViewport();
    registerModalBackTrap('manualModal', 'closeManualModal');
    var saveBtn = document.getElementById('btnSaveManual');
    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerText = '저장 및 적용';
    }
    var canonicalInput = document.getElementById('hidCanonicalPayload');
    if (canonicalInput) canonicalInput.value = "";
    if(mode !== 'edit') {
        document.getElementById('manualTitle').innerText = "품목 등록";
        document.getElementById('manualForm').reset();
        document.getElementById('hidItemID').value = "";
        document.getElementById('hidGroupID').value = "";
        if (typeof resetLocation === 'function') resetLocation();
        changeCategory(getDefaultItemCategory(), { forceRender: true });
    } else {
        document.getElementById('manualTitle').innerText = "품목 수정";
    }
}
function closeManualModal(options) {
    var opts = options || {};
    document.getElementById('manualModal').style.display = 'none';
    unlockManualModalViewport();
    releaseModalBackTrap('manualModal', opts);
    var saveBtn = document.getElementById('btnSaveManual');
    if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerText = '저장 및 적용';
    }
    var canonicalInput = document.getElementById('hidCanonicalPayload');
    if (canonicalInput) canonicalInput.value = "";
}

function editItem(id, loc, cat, prod, color, opt, w, h, qty, price, memo, sup, costPrice, productId, groupId, category1, bSize, bCount, bQtyList) {
    openManualModal('edit');
    document.getElementById('hidItemID').value = id;

    var cleanLoc = loc.replace(/\s*\(.*\)/g, "").trim();
    var selLoc = document.getElementById('selLocation');
    initializeLocationPickerUi();
    if (selLoc) {
        ensureLocationOption(cleanLoc);
        selLoc.value = cleanLoc;
    }
    var inpLoc = document.getElementById('inpLocation');
    if (inpLoc) inpLoc.value = cleanLoc;
    if (typeof syncLocationPickerLabel === 'function') syncLocationPickerLabel();

    var cleanCat = (cat || "").trim(); 
    document.getElementById('catSelect').value = cleanCat;
    var cleanCat1 = (category1 || "").trim();

    if (getItemCategoryMode(cleanCat) === 'blind') {
        changeCategory(cleanCat, { skipRender: true }); 
        if (cleanCat1) {
        var btnFound = false;
        document.querySelectorAll('.btn-kind').forEach(function(btn) {
            if (btn.innerText.trim() === cleanCat1) { 
                btn.click(); // 여기서 setBlindKind가 호출됨
                btnFound = true; 
            }
        });
        if(!btnFound) document.getElementById('blindSubKind').value = cleanCat1;
    }

        var items = [];
        var cnt = 1; 
        var useGroupLogic = false;
        
        if (groupId && typeof g_groupData !== 'undefined' && g_groupData[groupId]) {
            var grp = g_groupData[groupId];
            if (grp.length === 1 && grp[0].BlindSize && /[,/\n\r]/.test(grp[0].BlindSize)) {
                useGroupLogic = false; 
            } else {
                useGroupLogic = true;
            }
        }

        if (useGroupLogic) {
            var grpItems = g_groupData[groupId];
            items = grpItems.map(item => ({
                w: item.w, h: item.h, q: item.q,
                handle: (item.BlindSize || "").match(/\(([^)]+)\)/)?.[1] || "",
                cord: (item.BlindSize || "").match(/줄\s*([0-9]+)/)?.[1] || "150",
                prod: item.prod || prod, color: item.color || color || '', opt: item.opt || opt, p: item.p || price, memo: item.memo || memo, supplier: item.sup || sup || '', attributes: { cost_price: item.cost || costPrice || 0, product_id: item.pid || productId || 0 }, id: item.id
            }));
            cnt = items.length;
        } else {
            var parsedSizes = [];
            if (bSize && bSize.trim() !== "") {
                var rawChunks = bSize.split(/[,/\n\r]+/); 
                var chunks = rawChunks.filter(s => s && s.trim() !== ""); 
                var lastValidH = ""; 
                chunks.forEach(function(chunk) {
                    chunk = chunk.trim();
                    var cleanChunk = chunk.replace(/줄\s*[0-9]+/, "").replace(/\([^)]+\)/, "");
                    var sizeMatch = cleanChunk.match(/([0-9.]+)\s*[xX*]\s*([0-9.]+)/);
                    var tW = "", tH = "", hasH = false; 

                    if (sizeMatch) {
                        tW = sizeMatch[1]; tH = sizeMatch[2]; hasH = true; lastValidH = tH;
                    } else {
                        tW = cleanChunk.replace(/[^0-9.]/g, ""); tH = h;
                    }
                    var handMatch = chunk.match(/\(([^)]+)\)/);
                    var tHand = handMatch ? handMatch[1] : ""; 
                    var cordMatch = chunk.match(/줄\s*([0-9]+)/);
                    var tCord = cordMatch ? cordMatch[1] : "150";
                    parsedSizes.push({ w: tW, h: tH, handle: tHand, cord: tCord, hasH: hasH });
                });
                parsedSizes.forEach(function(item) {
                    if (!item.hasH && (!item.h || item.h == 0) && lastValidH) item.h = lastValidH;
                });
            }
            cnt = parsedSizes.length > 0 ? parsedSizes.length : 1;
            var parsedQtys = [];
            if (bQtyList && bQtyList.trim() !== "") {
                parsedQtys = bQtyList.split(/[,/\n\r]+/).map(s => s.trim()).filter(s => s !== "");
            }
            for(var i=0; i<cnt; i++) {
                var sizeObj = parsedSizes[i] || { w: w, h: h, handle: "", cord: "150" };
                if (!sizeObj.handle) sizeObj.handle = (cnt > 1 && i === 0) ? "좌" : "우";
                var qtyVal = parsedQtys[i] || "";
                if(!qtyVal && sizeObj.w && sizeObj.h) {
                    qtyVal = (parseFloat(sizeObj.w) * parseFloat(sizeObj.h) / 10000).toFixed(2);
                }
                items.push({ 
                    w: sizeObj.w, h: sizeObj.h, q: qtyVal,
                    handle: sizeObj.handle, cord: sizeObj.cord,     
                    prod: prod, color: color || '', opt: opt, p: price, memo: memo, supplier: sup || '', attributes: { cost_price: costPrice || 0, product_id: productId || 0 }, id: id 
                });
            }
        }

        var splitInput = document.getElementById('blindSplit');
        if(splitInput) splitInput.value = cnt;

        // 버튼 활성화 초기화
        document.querySelectorAll('.btn-blind-num').forEach(b => b.classList.remove('active'));
        var blindSelect = document.getElementById('blindSelect');
        if(blindSelect) blindSelect.classList.remove('active');

        // 개수에 따른 버튼/셀렉트 활성화 (원본 791~793 라인)
        if(cnt <= 6) { // 6창 이하는 버튼 활성화
            var targetBtn = document.getElementById('bBtn_' + cnt);
            if(targetBtn) targetBtn.classList.add('active');
            if(blindSelect) blindSelect.value = "";
        } else { // 7창 이상은 셀렉트 박스 활성화
            if(blindSelect) { 
                blindSelect.value = cnt; 
                blindSelect.classList.add('active'); 
            }
        }

        // UI 그리기 (원본 793 라인)
        // 여기서 생성되는 input들이 위 1번에서 숨긴 staticInfoBox와 ID가 겹치지 않게 됩니다.
        (window.__itemMasterRenderBlindUI || renderBlindUI)(document.getElementById('dynamicArea'), cnt, items);
        
    } else {
        changeCategory(cleanCat, { skipRender: true });
        var container = document.getElementById('dynamicArea');
        if (getItemCategoryMode(cleanCat) === 'generic') {
            document.getElementById('inpEtcKind').value = cleanCat1 || cleanCat || '기타';
        }

        if (groupId && typeof g_groupData !== 'undefined' && g_groupData[groupId]) {
            var grpItems = g_groupData[groupId];
            document.getElementById('hidGroupID').value = groupId;
            if (getItemCategoryMode(cleanCat) === 'curtain') {
                document.getElementById('typeMix').checked = true;
                var html = "";
                grpItems.forEach((item, i) => {
                    var isInner = false;
                    if (item.category1 === '속지') isInner = true;
                    else if (item.category1 === '겉지') isInner = false;
                    else if (item.loc.indexOf('속지') > -1) isInner = true;
                    else if (item.loc.indexOf('겉지') > -1) isInner = false;
                    else { if (i === 0) isInner = true; else isInner = false; }
                    var lbl = isInner ? '속지' : '겉지';
                    var cls = isInner ? 'label-inner' : 'label-outer';
                    item.supplier = item.sup || item.supplier || sup || '';
                    item.attributes = item.attributes || {};
                    if (!item.attributes.cost_price && (item.cost || costPrice)) item.attributes.cost_price = item.cost || costPrice;
                    if (!item.attributes.product_id && (item.pid || productId)) item.attributes.product_id = item.pid || productId;
                    html += (window.__itemMasterMakeRowHTML || makeRowHTML)(i+1, lbl, cls, item.opt, item, item.category1 || lbl);
                });
                container.innerHTML = html;
            } else {
                var html = "";
                grpItems.forEach((item, i) => {
                    var rowLabel = item.category1 || cleanCat1 || cleanCat || '기타';
                    item.supplier = item.sup || item.supplier || sup || '';
                    item.attributes = item.attributes || {};
                    if (!item.attributes.cost_price && (item.cost || costPrice)) item.attributes.cost_price = item.cost || costPrice;
                    if (!item.attributes.product_id && (item.pid || productId)) item.attributes.product_id = item.pid || productId;
                    html += (window.__itemMasterMakeRowHTML || makeRowHTML)(i + 1, rowLabel, 'label-badge', item.opt, item, item.category1 || rowLabel);
                });
                container.innerHTML = html;
            }
        } else {
            document.getElementById('hidGroupID').value = "";
            var defItem = { w:w, h:h, q:qty, p:price, prod:prod, color:color || '', memo:memo, supplier: sup || '', attributes: { cost_price: costPrice || 0, product_id: productId || 0 }, id:id };
            var labelName = '수정', labelClass = 'label-badge', subVal = cleanCat1;

            if (getItemCategoryMode(cleanCat) === 'curtain') {
                if (cleanCat1 === '속지') { labelName = '속지'; labelClass = 'label-inner'; document.getElementById('typeInner').checked = true; } 
                else if (cleanCat1 === '겉지') { labelName = '겉지'; labelClass = 'label-outer'; document.getElementById('typeOuter').checked = true; } 
                else if (loc.indexOf('속지') > -1) { labelName = '속지'; labelClass = 'label-inner'; subVal = '속지'; document.getElementById('typeInner').checked = true; } 
                else if (loc.indexOf('겉지') > -1) { labelName = '겉지'; labelClass = 'label-outer'; subVal = '겉지'; document.getElementById('typeOuter').checked = true; }
                else { labelName = '커튼'; document.getElementById('typeMix').checked = true; }
            } else if (getItemCategoryMode(cleanCat) === 'generic') { labelName = cleanCat1 || cleanCat || '기타'; }
            document.getElementById('dynamicArea').innerHTML = (window.__itemMasterMakeRowHTML || makeRowHTML)(1, labelName, labelClass, opt, defItem, subVal);
        }
        setTimeout(function() {
            if (groupId && typeof g_groupData !== 'undefined' && g_groupData[groupId]) {
                g_groupData[groupId].forEach((item, i) => { calcCurtainEtcTotal(i + 1); });
            } else { calcCurtainEtcTotal(1); }
        }, 50);
    }
}

function checkAndSyncSubStatus() {
    var btns = document.querySelectorAll('.item-stat-btn');
    if(btns.length === 0) return;
    var total = btns.length, cntOrder = 0, cntReceive = 0;
    btns.forEach(function(b) {
        var step = parseInt(b.getAttribute('data-step'));
        if(step === 1) cntOrder++;
        if(step === 2) cntReceive++;
    });
    if(cntOrder === total) forceActivateSubBtn('order');
    if(cntReceive === total) forceActivateSubBtn('receive');
}

function forceActivateSubBtn(type) {
    var btnId = (type === 'order') ? 'btnSub_order' : 'btnSub_receive';
    var btn = document.getElementById(btnId);
    if(!btn) return;
    var computed = window.getComputedStyle(btn).backgroundColor;
    var isActive = (computed !== 'rgb(255, 255, 255)' && computed !== 'rgba(0, 0, 0, 0)' && computed !== 'transparent');
    if (isActive) return;

    fetch(`/api/status/update?id=${g_orderId}&type=sub&val=${type}&v=${new Date().getTime()}`)
        .then(() => {
            btn.style.background = (type === 'order') ? "#5ed046" : "#448aff"; 
            btn.style.color = "#fff";
        });
}

function initSortable() {
    var el = document.querySelector('.excel-table tbody');
    if (!el) return;
    new Sortable(el, {
        handle: '.handle', animation: 150, delay: 0,
        onEnd: function (evt) {
            var ids = Array.from(document.querySelectorAll('.excel-table tbody tr')).map(row => row.getAttribute('data-id'));
            fetch('/api/item/reorder', {
                method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'ids=' + ids.join(',')
            });
        }
    });
}

function printEstimate() { window.open('/view-print/' + g_orderId, '_blank', 'width=850,height=1000,scrollbars=yes'); }

function setBlindKind(btn, kindName, minVal) {
    document.querySelectorAll('.btn-kind').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    
    var input = document.getElementById('blindSubKind');
    input.value = kindName; 
    input.setAttribute('data-min', minVal);
    
    var msgEl = document.getElementById('blindMinMsg');
    if(msgEl) msgEl.innerText = "※ " + kindName + " 기본: " + minVal + "㎡ / 세로150";
    
    document.querySelectorAll('input[name^="SubCat_"]').forEach(function(el) { el.value = kindName; });

    var cnt = parseInt(document.getElementById('blindSplit').value) || 1;
    for(var i=1; i<=cnt; i++) {
        if(typeof calcBlindRowArea === 'function') calcBlindRowArea(i); 
    }
    
    if(typeof updateBlindAggregates === 'function') updateBlindAggregates();
    if(typeof calcBlindTotalPrice === 'function') calcBlindTotalPrice();
}

function confirmGroupDelete(groupId) {
    var msg = "이 항목을 삭제하시겠습니까?";
    if (groupId && groupId !== "") msg = "⚠️ 이 항목은 그룹(세트)으로 묶여 있습니다.\n\n삭제 시 같은 그룹의 모든 항목이 함께 삭제됩니다.\n계속하시겠습니까?";
    return confirm(msg);
}

function ensureLocationOption(val) {
    var sel = document.getElementById('selLocation');
    if (!sel) return;
    var cleanVal = (val || "").trim();
    if (!cleanVal || cleanVal === 'direct') return;
    for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === cleanVal) return;
    }
    var opt = document.createElement('option');
    opt.value = cleanVal;
    opt.text = cleanVal;
    opt.dataset.tempLocation = '1';
    sel.appendChild(opt);
}
function findMatchingLocationOption(value) {
    var sel = document.getElementById('selLocation');
    var cleanValue = (value || "").trim();
    if (!sel || !cleanValue) return null;
    return Array.from(sel.options).find(function(option) {
        if (!option || option.disabled || option.value === 'direct') return false;
        return option.value === cleanValue || option.text === cleanValue;
    }) || null;
}
function syncLocationPickerFromDisplay() {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    if (!sel || !display) return;
    var typed = (display.value || "").trim();
    var placeholder = display.dataset.locationPlaceholder || '위치선택';
    clearTempLocationOptions();
    if (!typed || typed === placeholder) {
        sel.value = "";
        if (inp) inp.value = "";
        if (divDirect) divDirect.style.display = 'none';
        return;
    }
    var matched = Array.from(sel.options).find(function(option) {
        if (!option || option.disabled) return false;
        return option.value === typed || option.text === typed;
    });
    if (matched) {
        sel.value = matched.value;
    } else {
        ensureLocationOption(typed);
        sel.value = typed;
    }
    if (inp) inp.value = sel.value || typed;
    if (divDirect) divDirect.style.display = 'none';
}
function syncLocationPickerFromDirectInput() {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var display = document.getElementById('locPickerDisplay');
    if (!sel || !inp || !display) return;
    var typed = (inp.value || "").trim();
    clearTempLocationOptions();
    if (!typed) {
        if (!sel.value) {
            syncLocationPickerLabel();
            return;
        }
        var selected = findMatchingLocationOption(sel.value);
        display.value = selected ? selected.text : sel.value;
        return;
    }
    var matched = findMatchingLocationOption(typed);
    if (matched) {
        sel.value = matched.value;
        inp.value = matched.value;
        display.value = matched.text;
        return;
    }
    ensureLocationOption(typed);
    sel.value = typed;
    display.value = typed;
}
function clearTempLocationOptions() {
    var sel = document.getElementById('selLocation');
    if (!sel) return;
    Array.from(sel.options).forEach(function(option) {
        if (option.dataset && option.dataset.tempLocation === '1') option.remove();
    });
}
function getLocationPickerOptions() {
    var sel = document.getElementById('selLocation');
    if (!sel) return [];
    var options = Array.from(sel.options).filter(function(option) {
        return option && !option.disabled && option.value && option.value !== 'direct';
    });
    var savedOptions = [];
    var tempOptions = [];
    options.forEach(function(option) {
        if (option.dataset && option.dataset.tempLocation === '1') {
            tempOptions.push(option);
        } else {
            savedOptions.push(option);
        }
    });
    return savedOptions.concat(tempOptions);
}
function closeLocationPickerSuggestions() {
    if (window.__locationPickerDropdownEl && window.__locationPickerDropdownEl.parentNode) {
        window.__locationPickerDropdownEl.parentNode.removeChild(window.__locationPickerDropdownEl);
    }
    window.__locationPickerDropdownEl = null;
}
function selectLocationSuggestion(value, text) {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    if (!sel || !display) return;
    clearTempLocationOptions();
    if (value) {
        ensureLocationOption(value);
        sel.value = value;
    } else {
        sel.value = "";
    }
    display.value = text || value || "";
    display.placeholder = display.dataset.locationPlaceholder || display.placeholder || '';
    if (inp) inp.value = value || "";
    if (divDirect) divDirect.style.display = 'none';
    closeLocationPickerSuggestions();
}
function renderLocationPickerSuggestions(query) {
    var display = document.getElementById('locPickerDisplay');
    var sel = document.getElementById('selLocation');
    if (!display) return;
    closeLocationPickerSuggestions();

    var normalized = String(query || "").trim().toLowerCase();
    var options = getLocationPickerOptions().filter(function(option) {
        if (!normalized) return true;
        return String(option.text || "").toLowerCase().includes(normalized)
            || String(option.value || "").toLowerCase().includes(normalized);
    });
    if (!options.length) return;

    var dropdown = document.createElement('div');
    dropdown.className = 'smart-dropdown location-suggestion-dropdown';
    var host = display.parentNode;
    if (host && host.style) host.style.position = 'relative';
    dropdown.style.left = '0';
    dropdown.style.top = (display.offsetHeight + 6) + 'px';
    dropdown.style.width = '100%';
    dropdown.style.minWidth = '0';

    options.forEach(function(option) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'smart-dropdown-item location-suggestion-item';
        if (sel && sel.value === option.value) btn.classList.add('is-selected');
        btn.innerHTML = '<span class="location-suggestion-text">' + option.text + '</span>' +
            '<span class="location-suggestion-check"><i class="fas fa-check"></i></span>';
        btn.addEventListener('mousedown', function(event) {
            event.preventDefault();
        });
        btn.addEventListener('touchstart', function(event) {
            event.preventDefault();
            selectLocationSuggestion(option.value, option.text);
        }, { passive: false });
        btn.addEventListener('pointerdown', function(event) {
            event.preventDefault();
            selectLocationSuggestion(option.value, option.text);
        });
        btn.addEventListener('click', function() {
            selectLocationSuggestion(option.value, option.text);
        });
        dropdown.appendChild(btn);
    });

    (host || document.body).appendChild(dropdown);
    window.__locationPickerDropdownEl = dropdown;
}
function initializeLocationPickerUi() {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    if (sel && sel.value && sel.value !== 'direct') {
        ensureLocationOption(sel.value);
    }
    if (divDirect) divDirect.style.display = sel && sel.value === 'direct' ? 'flex' : 'none';
    if (inp) {
        inp.type = 'text';
        if (sel && sel.value !== 'direct' && !inp.value && sel.value) {
            inp.value = sel.value || '';
        }
    }
    if (display) {
        display.readOnly = false;
        display.removeAttribute('readonly');
        display.autocomplete = 'off';
        display.spellcheck = false;
        display.style.cursor = 'text';
        if (!display.dataset.locationPlaceholder) display.dataset.locationPlaceholder = '위치선택';
        display.placeholder = display.dataset.locationPlaceholder;
        if (!display.dataset.locationPickerBound) {
            display.dataset.locationPickerBound = '1';
            display.addEventListener('focus', function() {
                renderLocationPickerSuggestions(display.value);
            });
            display.addEventListener('click', function() {
                renderLocationPickerSuggestions(display.value);
            });
            display.addEventListener('input', function() {
                syncLocationPickerFromDisplay();
                renderLocationPickerSuggestions(display.value);
            });
            display.addEventListener('keydown', function(event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    syncLocationPickerFromDisplay();
                    closeLocationPickerSuggestions();
                } else if (event.key === 'Escape') {
                    closeLocationPickerSuggestions();
                }
            });
            display.addEventListener('blur', function() {
                setTimeout(function() {
                    syncLocationPickerFromDisplay();
                    closeLocationPickerSuggestions();
                }, 120);
            });
        }
    }
    if (!window.__locationPickerDropdownBound) {
        window.__locationPickerDropdownBound = true;
        document.addEventListener('pointerdown', function(event) {
            var dropdown = window.__locationPickerDropdownEl;
            var target = event.target;
            if (!dropdown) return;
            if (dropdown.contains(target)) return;
            if (target && target.closest && target.closest('.location-picker-row')) return;
            closeLocationPickerSuggestions();
        });
        window.addEventListener('resize', closeLocationPickerSuggestions);
        window.addEventListener('scroll', closeLocationPickerSuggestions, true);
    }
    syncLocationPickerLabel();
}
function toggleLocation(val) {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    if (val === 'direct') {
        if (sel) sel.value = 'direct';
        if (divDirect) divDirect.style.display = 'flex';
        if (display) {
            display.placeholder = display.dataset.locationPlaceholder || display.placeholder || '';
            display.value = inp ? ((inp.value || "").trim()) : "";
        }
        closeLocationPickerSuggestions();
        if (inp) {
            inp.type = 'text';
            setTimeout(function() {
                inp.focus();
                if (typeof inp.select === 'function') inp.select();
            }, 0);
        }
        if (typeof syncLocationPickerLabel === 'function') syncLocationPickerLabel();
        return;
    }
    var matched = findMatchingLocationOption(val);
    if (sel) sel.value = matched ? matched.value : (val || "");
    if (inp) inp.value = matched ? matched.value : (val || "");
    if (divDirect) divDirect.style.display = 'none';
    if (display) {
        display.placeholder = display.dataset.locationPlaceholder || display.placeholder || '';
        display.value = matched ? matched.text : (val || '');
    }
    closeLocationPickerSuggestions();
    if (typeof syncLocationPickerLabel === 'function') syncLocationPickerLabel();
}
function resetLocation() {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    clearTempLocationOptions();
    if (sel) sel.value = "";
    if (inp) inp.value = "";
    if (divDirect) divDirect.style.display = 'none';
    if (display) {
        display.value = '';
        display.placeholder = display.dataset.locationPlaceholder || display.placeholder || '';
    }
    closeLocationPickerSuggestions();
    if (typeof syncLocationPickerLabel === 'function') syncLocationPickerLabel();
}
function syncLocationPickerLabel() {
    var sel = document.getElementById('selLocation');
    var inp = document.getElementById('inpLocation');
    var divDirect = document.getElementById('divDirectLoc');
    var display = document.getElementById('locPickerDisplay');
    if (!sel || !display) return;
    var typed = inp ? (inp.value || "").trim() : "";
    display.placeholder = display.dataset.locationPlaceholder || display.placeholder || '';
    if (sel.value === 'direct') {
        if (divDirect) divDirect.style.display = 'flex';
        display.value = typed;
        return;
    }
    if (divDirect) divDirect.style.display = 'none';
    var selectedOption = sel.options[sel.selectedIndex];
    var selectedText = selectedOption ? selectedOption.text : '';
    var matched = typed ? findMatchingLocationOption(typed) : null;
    if (sel.value) {
        if (matched && matched.value === sel.value) {
            if (inp) inp.value = matched.value;
            display.value = matched.text;
        } else {
            display.value = selectedText || sel.value || '';
            if (inp && !typed) inp.value = sel.value;
        }
        return;
    }
    if (typed) {
        if (matched) {
            sel.value = matched.value;
            if (inp) inp.value = matched.value;
            display.value = matched.text;
        } else {
            ensureLocationOption(typed);
            sel.value = typed;
            display.value = typed;
        }
        return;
    }
    display.value = selectedText || '';
}
function openLocationPicker() {
    var sel = document.getElementById('selLocation');
    var display = document.getElementById('locPickerDisplay');
    if (!sel) return;
    initializeLocationPickerUi();
    if (sel.value !== 'direct' && display && display.value && display.value.trim() !== (display.dataset.locationPlaceholder || '위치선택')) {
        syncLocationPickerFromDisplay();
    }
    if (typeof window.openMobileInlineSelect === 'function' &&
        typeof window.isMobileInlineSelectMode === 'function' &&
        window.isMobileInlineSelectMode()) {
        var pickerRow = sel.closest('.control-box') ? sel.closest('.control-box').querySelector('.location-picker-row') : null;
        window.openMobileInlineSelect(sel, { anchor: pickerRow || sel });
        return;
    }
    var restore = function() {
        sel.style.position = '';
        sel.style.left = '';
        sel.style.top = '';
        sel.style.width = '';
        sel.style.height = '';
        sel.style.opacity = '';
        sel.style.pointerEvents = '';
        sel.style.zIndex = '';
    };
    var pickerRow = sel.closest('.control-box') ? sel.closest('.control-box').querySelector('.location-picker-row') : null;
    var anchor = pickerRow ? pickerRow.getBoundingClientRect() : null;
    if (anchor) {
        sel.style.position = 'fixed';
        sel.style.left = anchor.left + 'px';
        sel.style.top = anchor.top + 'px';
        sel.style.width = anchor.width + 'px';
        sel.style.height = anchor.height + 'px';
        sel.style.opacity = '0.01';
        sel.style.pointerEvents = 'auto';
        sel.style.zIndex = '100250';
    }
    var done = false;
    var cleanup = function() {
        if (done) return;
        done = true;
        restore();
        sel.removeEventListener('change', cleanup);
        sel.removeEventListener('blur', cleanup);
    };
    sel.addEventListener('change', cleanup, { once: true });
    sel.addEventListener('blur', cleanup, { once: true });
    try {
        if (typeof sel.showPicker === 'function') {
            sel.showPicker();
        } else {
            sel.focus({ preventScroll: true });
            sel.click();
        }
    } catch (e) {
        sel.focus({ preventScroll: true });
        sel.click();
    }
}
window.uploadMasterPrice = async function(idx) {
    const icon = idx === 'Master' ? document.getElementById('ActionIcon_Master') : document.getElementById(`ActionIcon_${idx}`);
    if (!icon) return;

    const originClass = icon.className;

    try {
        const prodInput = idx === 'Master'
            ? document.getElementById('Master_Prod')
            : document.querySelector(`input[name="ProdName_${idx}"]`);
        const pidInput = idx === 'Master'
            ? document.getElementById('Master_ProductID')
            : document.querySelector(`input[name="ProductMasterID_${idx}"]`);
        const colorInput = idx === 'Master'
            ? document.getElementById('Master_Color')
            : document.querySelector(`input[name="Color_${idx}"]`);
        const optInput = idx === 'Master'
            ? document.getElementById('Master_Opt')
            : document.querySelector(`input[name="Option_${idx}"]`);
        const noteInput = idx === 'Master'
            ? document.getElementById('Master_Memo')
            : document.querySelector(`input[name="Memo_${idx}"]`);
        const supplierInput = idx === 'Master'
            ? document.getElementById('Master_Supplier')
            : document.getElementById(`Supplier_${idx}`);
        const supplierIdInput = idx === 'Master'
            ? document.getElementById('Master_SupplierID')
            : document.querySelector(`input[name="SupplierID_${idx}"]`);
        const costInput = idx === 'Master'
            ? document.getElementById('Master_CostPrice')
            : document.getElementById(`CostPrice_${idx}`);
        const priceInput = idx === 'Master'
            ? document.getElementById('Master_Price')
            : document.querySelector(`input[name="Price_${idx}"]`) || document.getElementById(`Price_${idx}`);

        let p_name = (prodInput?.value || '').trim();
        let p_id = idx === 'Master'
            ? (pidInput?.value || prodInput?.dataset?.productId || 0)
            : (pidInput?.value || prodInput?.dataset?.productId || 0);
        let p_color = colorInput?.value || '';
        let p_opt = optInput?.value || '';
        let p_note = noteInput?.value || '';
        let sup = supplierInput?.value || '';
        let supId = supplierIdInput?.value || supplierInput?.dataset?.supplierId || '';
        let cost = costInput?.value || '';
        let price = priceInput?.value || '';

        if (!p_name) return;

        icon.className = 'fas fa-spinner fa-spin text-primary';

        const ctx = getProductSearchContext(idx);
        if (typeof pushItemMasterSearchDebug === 'function') {
            pushItemMasterSearchDebug('upload-start', {
                screen: buildVisibleProductSearchState(idx, { value: p_name }),
                ctx,
                supplier: sup,
                productId: p_id
            });
        }
        if (!safeCleanNum(p_id) && Array.isArray(window.__smartDB) && p_name) {
            const matched = window.__smartDB.find(function(m) {
                if ((m.name || '') !== p_name) return false;
                if (ctx.category && (m.category || '') !== ctx.category) return false;
                if (ctx.subcategory && (m.subcategory || '') !== ctx.subcategory) return false;
                if (sup && (m.supplier || '') !== sup) return false;
                return true;
            });
            if (typeof pushItemMasterSearchDebug === 'function') {
                pushItemMasterSearchDebug('upload-local-match', {
                    screen: buildVisibleProductSearchState(idx, { value: p_name }),
                    ctx,
                    top: summarizeDebugResults(matched ? [matched] : []),
                    chosen: matched ? summarizeDebugResults([matched])[0] : null
                });
            }
            if (matched && matched.product_id) p_id = matched.product_id;
        }

        const formData = new URLSearchParams();
        formData.append('ProductID', safeCleanNum(p_id));
        formData.append('ProductName', p_name);
        const normalizedCategory = normalizeCategoryForMaster(ctx.category);
        const normalizedSubCategory = normalizeSubCategoryForMaster(ctx.subcategory, normalizedCategory);
        if (normalizedCategory) formData.append('Category', normalizedCategory);
        if (normalizedSubCategory) formData.append('SubCategory', normalizedSubCategory);
        formData.append('Color', p_color);
        formData.append('Option', p_opt);
        formData.append('Note', p_note);
        formData.append('SupplierName', sup);
        formData.append('SupplierID', safeCleanNum(supId));
        formData.append('CostPrice', safeCleanNum(cost));
        formData.append('SellingPrice', safeCleanNum(price));

        const res = await fetch('/api/item/master/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });
        const responseText = await res.text();
        let responseJson = null;
        try {
            responseJson = responseText ? JSON.parse(responseText) : null;
        } catch (parseError) {}
        window.__lastMasterPriceUpload = {
            idx: idx,
            ok: res.ok,
            status: res.status,
            request: formData.toString(),
            responseText: responseText,
            responseJson: responseJson
        };
        if (!res.ok) throw new Error(`Server Error ${res.status}: ${responseText}`);

        if (responseJson && responseJson.product_id) {
            const savedProductId = String(responseJson.product_id);
            if (pidInput) pidInput.value = savedProductId;
            if (prodInput && prodInput.dataset) prodInput.dataset.productId = savedProductId;
            if (window.__productAttrCache) {
                const ensureAttrItem = function(list, value) {
                    const normalizedValue = String(value || '').trim();
                    if (!normalizedValue) return list || [];
                    const nextList = Array.isArray(list) ? list.slice() : [];
                    const existingIndex = nextList.findIndex(function(item) {
                        return String(item?.value || '').trim() === normalizedValue;
                    });
                    if (existingIndex >= 0) {
                        const existing = nextList.splice(existingIndex, 1)[0] || {};
                        nextList.unshift({
                            value: normalizedValue,
                            extra_price: Number(existing.extra_price || 0),
                            use_count: Number(existing.use_count || 0) + 1,
                        });
                    } else {
                        nextList.unshift({
                            value: normalizedValue,
                            extra_price: 0,
                            use_count: 1,
                        });
                    }
                    return nextList;
                };
                const cacheKey = String(savedProductId);
                const cachedAttrs = window.__productAttrCache[cacheKey] || { category1: [], category2: [], category3: [] };
                cachedAttrs.category1 = ensureAttrItem(cachedAttrs.category1, responseJson.color || p_color || '');
                cachedAttrs.category2 = ensureAttrItem(cachedAttrs.category2, responseJson.option || p_opt || '');
                cachedAttrs.category3 = ensureAttrItem(cachedAttrs.category3, responseJson.note || p_note || '');
                window.__productAttrCache[cacheKey] = cachedAttrs;
            }
        }

        if (responseJson && Array.isArray(window.__smartDB)) {
            const savedProductId = Number(responseJson.product_id || 0);
            const existingIndex = window.__smartDB.findIndex(function(item) {
                return Number(item.product_id || 0) === savedProductId;
            });
            const mergedItem = {
                product_id: savedProductId || Number(p_id || 0) || 0,
                supplier_id: Number(responseJson.supplier_id || 0) || 0,
                category: responseJson.category || normalizedCategory || '',
                subcategory: responseJson.subcategory || normalizedSubCategory || '',
                name: responseJson.product_name || p_name,
                color: responseJson.color || p_color || '',
                option: responseJson.option || p_opt || '',
                note: responseJson.note || p_note || '',
                cost: Number(responseJson.cost_price || 0),
                price: Number(responseJson.selling_price || 0),
                supplier: responseJson.supplier_name || sup || ''
            };
            if (existingIndex >= 0) window.__smartDB[existingIndex] = mergedItem;
            else window.__smartDB.unshift(mergedItem);
        }

        icon.className = 'fas fa-check-circle text-success';
        setTimeout(function() {
            icon.className = 'fas fa-edit text-warning';
        }, 2000);
    } catch (e) {
        try {
            console.error('[uploadMasterPrice]', e, window.__lastMasterPriceUpload || null);
        } catch (ignore) {}
        icon.className = 'fas fa-exclamation-triangle text-danger';
        setTimeout(function() {
            icon.className = originClass;
        }, 2000);
    }
};
window.__viewUiUploadMasterPrice = window.uploadMasterPrice;

function showToast(msg, isCopyContent) {
    var x = document.getElementById("toast-container"); if (!x) return;
    if (isCopyContent) {
        var preview = msg.length > 150 ? msg.substring(0, 150) + "..." : msg;
        x.innerHTML = "<div style='font-weight:bold; margin-bottom:5px;'>✅ 클립보드 복사 완료!</div><div style='font-size:12px; text-align:left; opacity:0.9; line-height:1.4;'>" + preview.replace(/\n/g, '<br>') + "</div>";
    } else { x.innerText = msg; }
    x.className = "show"; setTimeout(function(){ x.className = x.className.replace("show", ""); }, 4000);
}

function openDbModal() {
    document.getElementById('dbModal').style.display = 'flex';
    registerModalBackTrap('dbModal', 'closeDbModal');
    if(document.getElementById('mdlComplex').options.length <= 1) mdlLoadComplexes();
}
function closeDbModal(options) {
    document.getElementById('dbModal').style.display = 'none';
    releaseModalBackTrap('dbModal', options || {});
}

function markItemChanged() { sessionStorage.setItem('item_changed', 'true'); }

// 7. 서명 캔버스 UI (마우스/터치)
function openSignModal() {
    var modal = document.getElementById('signModal');
    if(modal) {
        modal.style.display = 'flex';
        registerModalBackTrap('signModal', 'closeSignModal');
        setTimeout(initCanvas, 200);
    }
}

function closeSignModal(options) {
    document.getElementById('signModal').style.display = 'none';
    releaseModalBackTrap('signModal', options || {});
}

function clearCanvas() { 
    if(ctx && canvas) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

function initCanvas() {
    var modalContent = document.querySelector('#signModal .modal-content');
    canvas = document.getElementById("sig-canvas"); 
    
    if (!canvas) { return; }

    canvas.width = modalContent ? (modalContent.clientWidth - 40) : 300;
    canvas.height = 250; 
    canvas.style.border = "2px solid red"; 
    canvas.style.background = "#fff";     

    ctx = canvas.getContext("2d");
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#000";
    ctx.lineCap = "round";
    
    addEvents();
}

function addEvents() {
    if (!canvas) return;

    canvas.onmousedown = function(e) {
        isDrawing = true; ctx.beginPath(); var pos = getPos(e); ctx.moveTo(pos.x, pos.y); 
    };
    canvas.onmousemove = function(e) {
        if (!isDrawing) return; var pos = getPos(e); ctx.lineTo(pos.x, pos.y); ctx.stroke(); 
    };
    window.addEventListener("mouseup", function() { if(isDrawing) isDrawing = false; });

    canvas.addEventListener("touchstart", function(e) {
        isDrawing = true; ctx.beginPath(); var pos = getPos(e); ctx.moveTo(pos.x, pos.y); e.preventDefault(); 
    }, { passive: false });
    canvas.addEventListener("touchmove", function(e) {
        if (!isDrawing) return; var pos = getPos(e); ctx.lineTo(pos.x, pos.y); ctx.stroke(); e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchend", function() { isDrawing = false; });
}

function getPos(e) {
    var rect = canvas.getBoundingClientRect();
    var clientX = (e.touches && e.touches.length > 0) ? e.touches[0].clientX : e.clientX;
    var clientY = (e.touches && e.touches.length > 0) ? e.touches[0].clientY : e.clientY;
    var x = Math.floor(clientX - rect.left);
    var y = Math.floor(clientY - rect.top);
    return { x: x, y: y };
}

// 8. 캘린더 UI
function openFullCalendarPicker() {
    if (typeof openCommonCalendar === 'function') {
        openCommonCalendar(function(info) {
            document.getElementById('dateInput').value = info.dateStr;
            if (typeof renderDailyTimeline === 'function') {
                renderDailyTimeline(info.dateStr);
            }
            setTimeout(function() {
                var timeInput = document.getElementById('timeInput');
                if (timeInput) timeInput.focus();
            }, 0);
            closeCommonCalendar();
        }, { disableEventNavigation: true });
        return;
    }

    var calendarEl = document.getElementById('modalCalendar');
    if (!calendarEl) {
        var container = document.querySelector('#dateModal .modal-content');
        if (!container) return; 

        calendarEl = document.createElement('div');
        calendarEl.id = 'modalCalendar';
        calendarEl.style.marginTop = '10px';
        calendarEl.style.marginBottom = '15px';
        
        var preview = document.getElementById('dailySchedulePreview');
        if (preview) container.insertBefore(calendarEl, preview); 
        else container.appendChild(calendarEl);
    }

    if (typeof calendarModalObj !== 'undefined' && calendarModalObj) {
        calendarModalObj.render();
        return;
    }

    if (typeof FullCalendar === 'undefined') {
        alert('캘린더 라이브러리가 로드되지 않았습니다.');
        return;
    }

    window.calendarModalObj = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        locale: 'ko',
        height: 350,
        headerToolbar: { left: 'prev,next', center: 'title', right: 'today' },
        selectable: true,
        dateClick: function(info) {
            document.getElementById('dateInput').value = info.dateStr;
            if (typeof renderDailyTimeline === 'function') renderDailyTimeline(info.dateStr);
            document.querySelectorAll('.fc-daygrid-day').forEach(el => el.style.backgroundColor = '');
            info.dayEl.style.backgroundColor = '#e7f5ff';
        },
        events: '/api/schedule' 
    });

    window.calendarModalObj.render();
}

function copyToClipboard(text) {
    if (!text) return;
    // [Reason] 모바일/HTTP 환경에서도 최대한 안정적으로 복사되도록 개선
    const done = () => { try { showToast("클립보드에 복사되었습니다."); } catch(e) {} };
    const fail = () => { fallbackCopyText(text); };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(fail);
    } else {
        fail();
    }
}

function fallbackCopyText(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "0";
    ta.style.top = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
        const ok = document.execCommand("copy");
        if (!ok) { prompt("복사하기(Ctrl+C)", text); }
        else { try { showToast("클립보드에 복사되었습니다."); } catch(e) {} }
    } catch (e) {
        prompt("복사하기(Ctrl+C)", text);
    }
    document.body.removeChild(ta);
}

function fallbackCopyText(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "0";
    ta.style.top = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
        const ok = document.execCommand("copy");
        if (!ok) { prompt("복사하기(Ctrl+C)", text); }
        else { try { showToast("클립보드에 복사되었습니다."); } catch(e) {} }
    } catch (e) {
        prompt("복사하기(Ctrl+C)", text);
    }
    document.body.removeChild(ta);
}

function executeCopy(text) { copyToClipboard(text); }

function clickCategory(val) {
    var sel = document.getElementById('catSelect');
    if(sel) sel.value = val;
    changeCategory(val);
}

function renderBlindListSizes() {
    var rows = document.querySelectorAll('tr[data-cat="블라인드"]');
    rows.forEach(function(row) {
        var cell = row.querySelector('.txt-size');
        if(!cell) return; 
        if(cell.querySelector('div.blind-multi-line')) return;
        var rawText = cell.innerText.trim();
        if(!rawText) return;

        if(rawText.indexOf(',') > -1) {
            var parts = rawText.split(',').map(function(s) { return s.trim(); });
            var joinedText = parts.join('<br>');
            var setInfo = "";
            var finalHtml = `
                <div class="blind-multi-line" style="display:block; width:100%; text-align:inherit; line-height:1.6;">
                    ${joinedText}
                    ${setInfo}
                </div>`;
            cell.innerHTML = finalHtml;
        }
    });
}

function goBackToDashboard() {
    const snapshot = window.DASHBOARD_SNAPSHOT;
    if (!snapshot) { 
        location.href = '/dashboard'; 
        return; 
    }

    const mainStatusEl = document.querySelector('.btn-status-main.active span');
    snapshot["js-target-status"] = mainStatusEl ? mainStatusEl.innerText.trim() : snapshot["js-target-status"];

    const subBadges = Array.from(document.querySelectorAll('.badge-btn.active')).map(btn => {
        let text = btn.innerText.trim();
        if (text.includes("주문")) text = "주문";
        else if (text.includes("수령")) text = "수령";
        else if (text.includes("입금") || text.includes("확인")) text = "입금";
        else if (text.includes("대기")) text = "대기";
        else if (text.includes("보류")) text = "보류";
        const color = window.getComputedStyle(btn).backgroundColor;
        return { text: text, color: color };
    });
    snapshot["js-target-sub-badges"] = subBadges;

    const historyMemos = Array.from(document.querySelectorAll('.history-row[data-type="메모"] .memo-text'))
                              .slice(0, 10).map(el => el.innerText.trim());

    const selectedSurfaces = Array.from(document.querySelectorAll('.check-btn.active'))
                                  .map(btn => btn.getAttribute('data-val'));
    const checklistMemo = document.getElementById('inpChecklist')?.value || "";
    const siteText = (selectedSurfaces.length > 0 ? `[${selectedSurfaces.join(',')}] ` : "") + checklistMemo;

    const payload = {
        id: snapshot.id,
        "js-target-status": snapshot["js-target-status"],
        "js-target-sub-badges": subBadges,
        "js-target-date": snapshot["js-target-date"],
        "js-target-time": snapshot["js-target-time"],
        "js-target-name": document.getElementById('customer-name')?.value || snapshot["js-target-name"],
        "js-target-address": document.getElementById('customer-addr')?.value || document.getElementById('customer-phone')?.value || snapshot["js-target-address"],
        "js-target-price": document.getElementById('live-price')?.innerText.trim() || snapshot["js-target-price"],
        "js-target-manager": document.getElementById('dispManagerName')?.innerText.trim() || snapshot["js-target-manager"],
        "js-target-site-text": siteText.trim(),
        "js-target-memo-text": document.getElementById('live-memo')?.value || snapshot["js-target-memo-text"],
        "js-target-hist-list": historyMemos 
    };

    sessionStorage.setItem('dashboard_update_payload', JSON.stringify(payload));
    
    location.href = '/dashboard'; 
}

function collectViewPaymentMarginSummary() {
    var rows = document.querySelectorAll('.excel-table tbody tr');
    var sales = 0;
    var cost = 0;
    var count = 0;

    rows.forEach(function(row) {
        var source = row.querySelector('.btn-edit[data-cost]') || row.querySelector('button[data-cost][onclick*="handleEditClick"]');
        if (!source) return;
        var qty = parseFloat(String(source.getAttribute('data-qty') || '0').replace(/,/g, '')) || 0;
        var price = parseFloat(String(source.getAttribute('data-price') || '0').replace(/,/g, '')) || 0;
        var itemCost = parseFloat(String(source.getAttribute('data-cost') || '0').replace(/,/g, '')) || 0;
        if (qty <= 0 || price <= 0) return;
        sales += price * qty;
        cost += itemCost * qty;
        count += 1;
    });

    return {
        count: count,
        sales: sales,
        cost: cost
    };
}

window.triggerPaymentMarginSummary = function(element) {
    var target = element || document.getElementById('paymentSummaryCard') || document.getElementById('pcPaymentSummaryTrigger');
    var summary = collectViewPaymentMarginSummary();
    if (!summary.count) {
        if (typeof __voiceViewToast === 'function') __voiceViewToast('마진 정보가 없습니다.');
        else if (typeof showToast === 'function') showToast('마진 정보가 없습니다.');
        return;
    }
    if (typeof window.showMarginPopup === 'function') {
        window.showMarginPopup(target, summary.sales, 1, summary.cost);
    }
};

function openInfoModal() {
    if (typeof initInfoModalSelects === 'function') initInfoModalSelects();
    document.getElementById('infoModal').style.display = 'flex';
    registerModalBackTrap('infoModal', 'closeInfoModal');
    if (arguments[0] === 'inflow') {
        setTimeout(focusInflowGuideField, 40);
    }
}
function closeInfoModal(options) {
    document.getElementById('infoModal').style.display = 'none';
    releaseModalBackTrap('infoModal', options || {});
}

function hasMissingInflowInfo() {
    var routeEl = document.getElementById('inflow-route');
    var detailEl = document.getElementById('inflow-detail');
    var route = String(routeEl?.value || '').trim();
    var detail = String(detailEl?.value || '').trim();
    if (!route) return true;
    return route === '기타' && !detail;
}

function syncInflowGuideState() {
    var missing = hasMissingInflowInfo();
    ['btnInflowGuidePc', 'btnInflowGuideMobile'].forEach(function(id) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.hidden = false;
        btn.classList.toggle('is-missing', missing);
        btn.title = missing ? '유입 정보를 먼저 입력해 주세요.' : '';
    });
}

function focusInflowGuideField() {
    var routeEl = document.getElementById('inflow-route');
    if (!routeEl) return;
    try {
        routeEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {}
    routeEl.focus();
    routeEl.style.transition = 'box-shadow 0.3s ease, border-color 0.3s ease';
    routeEl.style.borderColor = '#ff922b';
    routeEl.style.boxShadow = '0 0 0 3px rgba(255, 146, 43, 0.22)';
    clearTimeout(window.__inflowGuideFocusTimer);
    window.__inflowGuideFocusTimer = setTimeout(function() {
        routeEl.style.borderColor = '';
        routeEl.style.boxShadow = '';
    }, 1800);
}

function openInflowInfoModal() {
    openInfoModal('inflow');
}

function initInfoModalSelects() {
    var selectIds = ['inflow-route', 'as-reason', 'as-responsibility', 'as-charge-type'];
    var useMobileInlineSelect = typeof window.isMobileInlineSelectMode === 'function' && window.isMobileInlineSelectMode();

    selectIds.forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        var shell = el.closest('.customer-info-select-shell') || el;

        if (useMobileInlineSelect) {
            if (el.tomselect) el.tomselect.destroy();
            if (el.dataset.infoInlineBound === '1') return;
            el.dataset.infoInlineBound = '1';
            var openInline = function() {
                if (typeof window.openMobileInlineSelect === 'function') {
                    window.openMobileInlineSelect(el, { anchor: shell });
                }
            };
            el.addEventListener('focus', openInline);
            el.addEventListener('click', openInline);
            return;
        }

        if (!window.TomSelect || el.tomselect) return;

        new TomSelect(el, {
            create: false,
            persist: false,
            allowEmptyOption: true,
            searchField: ['text'],
            openOnFocus: true,
            maxOptions: el.options.length,
            dropdownClass: 'touch-select-shell',
            onChange: function() {
                if (id === 'inflow-route' && typeof syncInflowGuideState === 'function') {
                    syncInflowGuideState();
                }
            }
        });
    });
}

function syncInflowGuideState() {
    var missing = hasMissingInflowInfo();
    ['btnInflowGuidePc', 'btnInflowGuideMobile'].forEach(function(id) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.hidden = false;
        btn.classList.toggle('is-missing', missing);
        btn.title = missing ? '유입 정보를 먼저 입력해 주세요' : '유입 정보 수정';
    });
}

function focusInflowGuideField() {
    var routeEl = document.getElementById('inflow-route');
    if (!routeEl) return;
    var focusTarget = routeEl.tomselect && routeEl.tomselect.wrapper ? routeEl.tomselect.wrapper : routeEl;
    try {
        focusTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {}
    if (typeof window.openMobileInlineSelect === 'function' &&
        typeof window.isMobileInlineSelectMode === 'function' &&
        window.isMobileInlineSelectMode()) {
        window.openMobileInlineSelect(routeEl, { anchor: focusTarget });
    } else if (routeEl.tomselect) {
        routeEl.tomselect.focus();
        routeEl.tomselect.open();
    } else {
        routeEl.focus();
    }
    focusTarget.style.transition = 'box-shadow 0.3s ease, border-color 0.3s ease';
    focusTarget.style.borderColor = '#ff922b';
    focusTarget.style.boxShadow = '0 0 0 3px rgba(255, 146, 43, 0.22)';
    clearTimeout(window.__inflowGuideFocusTimer);
    window.__inflowGuideFocusTimer = setTimeout(function() {
        focusTarget.style.borderColor = '';
        focusTarget.style.boxShadow = '';
    }, 1800);
}

function syncInflowGuideState() {
    var missing = hasMissingInflowInfo();
    ['btnInflowGuidePc', 'btnInflowGuideMobile'].forEach(function(id) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.hidden = false;
        btn.classList.toggle('is-missing', missing);
        btn.title = missing
            ? '\uC720\uC785 \uC815\uBCF4\uB97C \uBA3C\uC800 \uC785\uB825\uD574 \uC8FC\uC138\uC694'
            : '\uC720\uC785 \uC815\uBCF4 \uC218\uC815';
    });
}

function initFontControl() {
    var root = document.documentElement;
    var currentSize = (window.innerWidth <= 768) ? 16 : 14;
    var updateSize = (val) => {
        currentSize = (val === 0) ? ((window.innerWidth <= 768) ? 16 : 14) : Math.min(35, Math.max(12, currentSize + val));
        root.style.setProperty('--base-font', currentSize + "px");
    };
    updateSize(0);
    document.getElementById('btn-zoom-in')?.addEventListener('click', () => updateSize(1));
    document.getElementById('btn-zoom-out')?.addEventListener('click', () => updateSize(-1));
    document.getElementById('btn-zoom-reset')?.addEventListener('click', () => updateSize(0));
}

function handleEditClick(btn) {
    var d = btn.dataset;
    var clean = function(v) {
        return (v === undefined || v === null || v === 'undefined' || v === 'null') ? '' : v;
    };
    editItem(
        clean(d.id), clean(d.loc), clean(d.cat), clean(d.prod), clean(d.color), clean(d.opt),
        clean(d.w), clean(d.h), clean(d.qty), clean(d.price), clean(d.memo), clean(d.sup),
        clean(d.cost), clean(d.pid), clean(d.group), clean(d.sub), clean(d.bsize), clean(d.bcount), clean(d.bqty)
    );
}

document.addEventListener('click', function(e) {
    var container = document.querySelector('.no-print > div[style*="relative"]'); 
    if (container && !container.contains(e.target)) {
        var drop = document.getElementById('dropManagerList');
        if (drop) drop.style.display = 'none';
    }
});

function toggleManagerDrop() {
    var list = document.getElementById('dropManagerList');
    if(list) list.style.display = (list.style.display === 'block') ? 'none' : 'block';
}

function toggleLBracket(chk) {
    var optInput = document.getElementById('Master_Opt');
    var current = optInput.value;
    var tag = " [ㄱ자 꺽쇠]";
    if(chk.checked) { if(current.indexOf("[ㄱ자 꺽쇠]") === -1) optInput.value = current + tag; } 
    else { optInput.value = current.replace(tag, "").replace("ㄱ자 꺽쇠", "").trim(); }
    var count = parseInt(document.getElementById('blindSplit').value) || 1;
    syncBlindData(count, 'Option');
}

function toggleCheckItem(el) {
    el.classList.toggle('active');
    if(typeof saveSiteInfo === 'function') saveSiteInfo(true); 
}

function escapeSiteCheckHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function buildSiteCheckFullValue(item) {
    var name = (item.item_name || '').trim();
    var sub = (item.sub_text || '').trim();
    return sub ? (name + ' (' + sub + ')') : name;
}

function getCurrentSiteCheckSelections() {
    return Array.from(document.querySelectorAll('#section-site .check-btn.active'))
        .map(function(btn) { return btn.getAttribute('data-val') || ''; })
        .filter(Boolean);
}

function renderSiteCheckGrid(items) {
    var grid = document.querySelector('#section-site .check-grid');
    if (!grid) return;

    var selected = new Set(getCurrentSiteCheckSelections());
    grid.innerHTML = (items || []).map(function(item) {
        var fullVal = buildSiteCheckFullValue(item);
        var active = selected.has(fullVal) ? ' active' : '';
        var subHtml = item.sub_text ? ('<span class="check-sub">' + escapeSiteCheckHtml(item.sub_text) + '</span>') : '';
        return '' +
            '<div class="check-btn' + active + '" data-val="' + escapeSiteCheckHtml(fullVal) + '" onclick="toggleCheckItem(this)">' +
                '<span class="check-title">' + escapeSiteCheckHtml(item.item_name) + '</span>' +
                subHtml +
            '</div>';
    }).join('');
}

function renderSiteCheckManageList(items) {
    var listEl = document.getElementById('siteCheckManageList');
    if (!listEl) return;
    if (!items || !items.length) {
        listEl.innerHTML = '<div style="padding:18px; border:1px dashed #cbd5e1; border-radius:14px; text-align:center; color:#64748b; font-size:0.9rem;">등록된 체크항목이 없습니다.</div>';
        return;
    }

    listEl.innerHTML = items.map(function(item) {
        var subText = item.sub_text ? ('<div style="font-size:0.82rem; color:#64748b; margin-top:4px;">' + escapeSiteCheckHtml(item.sub_text) + '</div>') : '';
        return '' +
            '<div style="border:1px solid #e2e8f0; border-radius:14px; padding:12px 14px; display:flex; justify-content:space-between; gap:10px; align-items:flex-start; background:#fff;">' +
                '<div style="min-width:0; flex:1;">' +
                    '<div style="font-size:0.95rem; font-weight:800; color:#0f172a;">' + escapeSiteCheckHtml(item.item_name) + '</div>' +
                    subText +
                '</div>' +
                '<div style="display:flex; gap:6px; flex-shrink:0;">' +
                    '<button type="button" onclick="editSiteCheckManageItem(' + Number(item.item_id || 0) + ')" style="width:34px; height:34px; border:none; border-radius:10px; background:#e7f1ff; color:#0d6efd; cursor:pointer;"><i class="fas fa-pen"></i></button>' +
                    '<button type="button" onclick="deleteSiteCheckManageItem(' + Number(item.item_id || 0) + ')" style="width:34px; height:34px; border:none; border-radius:10px; background:#fff1f2; color:#e03131; cursor:pointer;"><i class="fas fa-trash"></i></button>' +
                '</div>' +
            '</div>';
    }).join('');
}

window.__siteCheckManageItems = window.__siteCheckManageItems || [];

async function loadSiteCheckManageItems() {
    var res = await fetch('/api/admin/checkitems', { credentials: 'include' });
    var data = await res.json();
    if (!res.ok || data.status !== 'ok') {
        throw new Error((data && (data.msg || data.detail)) || 'checkitems_load_failed');
    }
    window.__siteCheckManageItems = data.items || [];
    renderSiteCheckGrid(window.__siteCheckManageItems);
    renderSiteCheckManageList(window.__siteCheckManageItems);
}

function resetSiteCheckManageForm() {
    var idEl = document.getElementById('siteCheckManageId');
    var nameEl = document.getElementById('siteCheckManageName');
    var subEl = document.getElementById('siteCheckManageSub');
    if (idEl) idEl.value = '';
    if (nameEl) nameEl.value = '';
    if (subEl) subEl.value = '';
    if (nameEl) nameEl.focus();
}

function flashSiteCheckManageNotice(message) {
    var notice = document.getElementById('siteCheckManageNotice');
    if (!notice) return;
    notice.innerText = message || '저장되었습니다.';
    notice.style.display = 'block';
    clearTimeout(window.__siteCheckManageNoticeTimer);
    window.__siteCheckManageNoticeTimer = setTimeout(function() {
        notice.style.display = 'none';
    }, 1400);
}

function flashSiteDeductNotice(message) {
    var notice = document.getElementById('siteDeductMsg');
    if (!notice) return;
    notice.innerText = message || '저장되었습니다.';
    notice.style.display = 'block';
    clearTimeout(window.__siteDeductNoticeTimer);
    window.__siteDeductNoticeTimer = setTimeout(function() {
        notice.style.display = 'none';
    }, 1400);
}

async function loadSiteCurtainDeductions() {
    var sokjiEl = document.getElementById('siteDeductSokji');
    var geotjiEl = document.getElementById('siteDeductGeotji');
    if (!sokjiEl || !geotjiEl) return;

    var res = await fetch('/api/admin/curtain-deductions', { credentials: 'include' });
    var data = await res.json();
    if (!res.ok || !data.ok) {
        throw new Error((data && (data.msg || data.detail)) || 'curtain_deductions_load_failed');
    }

    var payload = data.data || {};
    var values = Object.values(payload);
    sokjiEl.value = payload['속지'] ?? values[0] ?? 4;
    geotjiEl.value = payload['겉지'] ?? values[1] ?? 3.5;
}

async function saveSiteCurtainDeductions() {
    var sokji = parseFloat(document.getElementById('siteDeductSokji')?.value || '0');
    var geotji = parseFloat(document.getElementById('siteDeductGeotji')?.value || '0');

    var res = await fetch('/api/admin/curtain-deductions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ sokji: sokji, geotji: geotji })
    });
    var data = await res.json();
    if (!res.ok || !data.ok) {
        alert((data && (data.msg || data.detail)) || '보정값 저장에 실패했습니다.');
        return;
    }
    flashSiteDeductNotice('보정값이 저장되었습니다.');
    triggerModalSuccessFeedback();
}

function copySiteCurtainDeductions() {
    var sokji = document.getElementById('siteDeductSokji')?.value || '';
    var geotji = document.getElementById('siteDeductGeotji')?.value || '';
    var text = '속지 보정값: ' + sokji + '\n겉지 보정값: ' + geotji;
    if (typeof copyToClipboard === 'function') {
        copyToClipboard(text);
    } else {
        window.prompt('아래 내용을 복사하세요.', text);
    }
}

function editSiteCheckManageItem(itemId) {
    var item = (window.__siteCheckManageItems || []).find(function(row) { return Number(row.item_id) === Number(itemId); });
    if (!item) return;
    document.getElementById('siteCheckManageId').value = item.item_id || '';
    document.getElementById('siteCheckManageName').value = item.item_name || '';
    document.getElementById('siteCheckManageSub').value = item.sub_text || '';
    document.getElementById('siteCheckManageName').focus();
}

async function submitSiteCheckManageForm(e) {
    if (e) e.preventDefault();
    var id = document.getElementById('siteCheckManageId')?.value || '';
    var name = (document.getElementById('siteCheckManageName')?.value || '').trim();
    var sub = (document.getElementById('siteCheckManageSub')?.value || '').trim();
    if (!name) {
        alert('항목명을 입력해주세요.');
        return;
    }

    var formData = new FormData();
    formData.append('name', name);
    formData.append('sub', sub);
    var url = '/api/admin/checkitem/add';
    if (id) {
        url = '/api/admin/checkitem/update';
        formData.append('item_id', id);
    }

    var res = await fetch(url, { method: 'POST', body: formData, credentials: 'include' });
    var data = await res.json();
    if (!res.ok || data.status !== 'ok') {
        alert((data && (data.msg || data.detail)) || '저장에 실패했습니다.');
        return;
    }
    await loadSiteCheckManageItems();
    resetSiteCheckManageForm();
    triggerModalSuccessFeedback();
    flashSiteCheckManageNotice(id ? '항목이 수정되었습니다.' : '항목이 추가되었습니다.');
}

async function deleteSiteCheckManageItem(itemId) {
    if (!itemId) return;
    if (!confirm('체크항목을 삭제하시겠습니까?')) return;

    var formData = new FormData();
    formData.append('item_id', itemId);
    var res = await fetch('/api/admin/checkitem/delete', { method: 'POST', body: formData, credentials: 'include' });
    var data = await res.json();
    if (!res.ok || data.status !== 'ok') {
        alert((data && (data.msg || data.detail)) || '삭제에 실패했습니다.');
        return;
    }
    await loadSiteCheckManageItems();
    resetSiteCheckManageForm();
    triggerModalSuccessFeedback();
    flashSiteCheckManageNotice('항목이 삭제되었습니다.');
}

async function openSiteCheckManageModal() {
    var modal = document.getElementById('siteCheckManageModal');
    if (!modal) return;
    modal.style.display = 'flex';
    registerModalBackTrap('siteCheckManageModal', 'closeSiteCheckManageModal');
    resetSiteCheckManageForm();
    try {
        await Promise.all([
            loadSiteCheckManageItems(),
            loadSiteCurtainDeductions()
        ]);
    } catch (e) {
        console.error(e);
        alert('현장체크 설정 정보를 불러오지 못했습니다.');
    }
}

function closeSiteCheckManageModal(options) {
    var modal = document.getElementById('siteCheckManageModal');
    if (!modal) return;
    modal.style.display = 'none';
    releaseModalBackTrap('siteCheckManageModal', options || {});
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeSiteCheckManageModal();
    }
});

function toggleBankInputs(val) {
    var area = document.getElementById('bankInfoArea'), vatChk = document.getElementById('payVatInput');
    if (val === '계좌') area.style.display = 'block'; else { area.style.display = 'none'; document.getElementById('payBank').value = ""; document.getElementById('payDepositor').value = ""; }
    vatChk.checked = (val === '카드');
    calcModalPrice();
}

function openPayModal() {
    var modal = document.getElementById('payModal'); 
    if (!modal) { alert("오류: 모달 없음"); return; }
    
    document.getElementById('payMethodInput').value = "계좌";
    toggleBankInputs("계좌"); 
    
    var mainVat = document.getElementById('chk-vat');
    var modalVat = document.getElementById('payVatInput');
    if (mainVat && modalVat) modalVat.checked = mainVat.checked;
    
    calcModalPrice();
    modal.style.display = 'flex';
    registerModalBackTrap('payModal', 'closePayModal');
}

function closePayModal(options) {
    document.getElementById('payModal').style.display = 'none';
    releaseModalBackTrap('payModal', options || {});
}

// [view_ui.js] 수정 부분
function openDateModal(type, currentVal) {
    var modal = document.getElementById('dateModal');
    if(!modal) return;
    
    document.getElementById('targetStatus').value = type;
    document.getElementById('modalTitle').innerText = type + " 일정 수정";
    
    // [변경 이유] 인자가 유효하지 않을 경우를 대비해 기본값 설정 로직 강화
    var targetVal = currentVal;
    
    // 만약 currentVal이 없거나 숫자인 경우(잘못된 호출), JSON에서 다시 한번 찾음
    if (!targetVal || typeof targetVal !== 'string' || targetVal.length < 5) {
        try {
            const scriptTag = document.getElementById('srv-saved-schedules');
            if (scriptTag) {
                const saved = JSON.parse(scriptTag.textContent);
                targetVal = saved[type] || "";
            }
        } catch(e) { targetVal = ""; }
    }

    var defDate = new Date().toISOString().split('T')[0];
    var defTime = "10:00";

    // [변경 이유] 기존 값이 존재하면 날짜와 시간을 정확히 분리하여 입력칸에 삽입
    if(targetVal && targetVal.includes(' ')) {
        var parts = targetVal.split(' ');
        defDate = parts[0]; 
        defTime = parts[1].substring(0, 5); // 초 단위 제외 (HH:mm)
    }

    document.getElementById('dateInput').value = defDate;
    document.getElementById('timeInput').value = defTime;
    
    modal.style.display = 'flex';
    registerModalBackTrap('dateModal', 'closeDateModal');
    
    // 모달이 열린 후 해당 날짜의 타임라인을 바로 보여줌
    if (typeof renderDailyTimeline === 'function') {
        renderDailyTimeline(defDate);
    }
}

function closeDateModal(options) {
    document.getElementById('dateModal').style.display = 'none';
    releaseModalBackTrap('dateModal', options || {});
}

/* [view_ui.js] renderDailyTimeline 함수 수정 */
function renderDailyTimeline(dateStr) {
    var con = document.getElementById('dailySchedulePreview');
    if (!con) return;

    con.innerHTML = '<div style="text-align:center; padding:50px; color:#666;"><i class="fas fa-spinner fa-spin"></i> 조회 중...</div>';
    
    var nextDate = new Date(dateStr);
    nextDate.setDate(nextDate.getDate() + 1);
    var nextDateStr = nextDate.toISOString().split('T')[0];

    fetch(`/api/schedule?start=${dateStr}&end=${nextDateStr}`)
        .then(res => res.json())
        .then(data => {
            // [변경 이유] 현재 날짜에 해당하는 이벤트만 필터링 (기존 로직)
            var events = data.filter(e => e.start.startsWith(dateStr));

            // ★ [핵심 수정] 현재 보고 있는 주문(g_orderId)은 제외함
            // [Reason] 내 일정을 제외해야 다른 사람/다른 장소의 스케줄만 명확히 보입니다.
            var filteredEvents = events.filter(evt => String(evt.id) !== String(g_orderId));

            if (filteredEvents.length === 0) {
                con.innerHTML = `<div style="text-align:center; padding-top:60px; color:#aaa;">
                    <i class="far fa-calendar-check" style="font-size:24px; margin-bottom:10px;"></i><br>
                    <span style="font-weight:bold; color:#333;">${dateStr}</span><br>다른 일정이 없습니다.
                </div>`;
                return;
            }
            
            filteredEvents.sort((a, b) => (a.time || "00:00").localeCompare(b.time || "00:00"));

            // [변경 이유] 필터링된 결과만 화면에 출력
            var html = filteredEvents.map(evt => makeScheduleItemHtml(evt)).join('');
            con.innerHTML = html;
        })
        .catch(err => {
            con.innerHTML = '<div style="text-align:center; padding:20px; color:red;">일정 로드 실패</div>';
            console.error(err);
        });
}

/* [view_ui.js] 일정 아이템 HTML 생성 (대시보드 카드 스타일 리뉴얼) */
function makeScheduleItemHtml(evt) {
    // 1. 데이터 추출 (FullCalendar 및 API 데이터 통합 대응)
    var props = evt.extendedProps || evt; 
    var items = props.items || evt.items || "";
    var price = props.price || evt.price || "";
    var time = props.time || evt.time || "-";
    var addr = props.address || evt.address || props.addr || evt.addr || "";
    
    // 2. 메인 상태 및 색상 결정
    var status = props.status || evt.status || '일정';
    var statBg = "#6f8672"; // 기본값 (bg-req)
    if (status.includes('방문')) statBg = "#39b114";      // b-visit
    else if (status.includes('시공')) statBg = "#1472ec"; // b-inst
    else if (status.includes('AS'))   statBg = "#9e1dbe"; // b-as
    else if (status.includes('완료')) statBg = "#333333"; // b-done
    else if (status.includes('견적')) statBg = "#fd7e14"; // bg-req(orange)

    // 3. 서브 배지 생성 (대시보드 스타일 소형 배지)
    var subBadges = '';
    var subStyle = 'padding:2px 5px; border-radius:8px; font-size:0.75rem; font-weight:500; color:#fff; margin-right:2px;';
    if (props.IsOrdered === 'Y') subBadges += `<span style="${subStyle} background:#3cce10;">주문</span>`;
    if (props.IsReceived === 'Y') subBadges += `<span style="${subStyle} background:#4e98fa;">수령</span>`;
    if (props.PaymentStatus === '미결제') subBadges += `<span style="${subStyle} background:#eb4646;">미납</span>`;
    if (props.IsWaiting === 'Y') subBadges += `<span style="${subStyle} background:#9775fa;">대기</span>`;
    if (props.IsHold === 'Y') subBadges += `<span style="${subStyle} background:#868e96;">보류</span>`;

    // 4. 품목 태그 분리 생성
    var itemsPills = "";
    if (items) {
        itemsPills = items.split(',').map(item => 
            `<div style="border:1px solid #ced4da; border-radius:4px; padding:2px 5px; background:#fff; color:#495057; font-size:0.8rem; font-weight:500; margin-right:3px; margin-bottom:0px;">${item.strip ? item.strip() : item.trim()}</div>`
        ).join('');
    }

    // 5. 최종 HTML 조립 (대시보드 task-card 구조)
    return `
    <div class="task-card" style="padding:8px; background:#fff; border-radius:12px; border:1px solid #ececee; margin-bottom:5px; box-shadow:0 2px 8px rgba(0,0,0,0.05); cursor:default;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">
            <div style="display:flex; align-items:center; gap:2px; flex-wrap:wrap;">
                <span style="background:${statBg}; color:#fff; padding:2px 4px; border-radius:6px; font-size:0.8rem; font-weight:800; letter-spacing:-0.5px;">${status}</span>
                ${subBadges}
            </div>
            <div style="text-align:right;">
                <span style="background:#eef2ff; color:#4361ee; padding:1px 4px; border-radius:12px; font-size:1rem; font-weight:600;">${time}</span>
            </div>
        </div>

        <div style="margin-bottom:4px; display:flex; justify-content:space-between; align-items:baseline;">
            <div style="font-size:1.1rem; font-weight:800; color:#222; letter-spacing:-0.5px;">
                ${props.CustomerName || evt.title.split(' (')[0]}
                <span style="font-size:0.9rem; font-weight:normal; color:#888; margin-left:4px;">(${addr || '주소없음'})</span>
            </div>
            ${price ? `<div style="font-size:1.1rem; font-weight:800; color:#d63384; letter-spacing:-0.5px;">${price}</div>` : ''}
        </div>

        ${itemsPills ? `
        <div style="display:flex; flex-wrap:wrap;">
            ${itemsPills}
        </div>` : ''}
    </div>`;
}




/* ==========================================================================
   [PATCH v4] 모바일 입력 UX + 모달 음성 토글 + 고객명 툴팁 + 품목 이미지 업로드 UX
   ========================================================================== */

// [1] 고객명(상단) 잘림: 클릭하면 전체 이름 툴팁 표시
(function initCustomerNameTooltip(){
    function showBubble(el, text){
        if(!el || !text) return;
        let bubble = document.getElementById('custNameBubble');
        if(!bubble){
            bubble = document.createElement('div');
            bubble.id = 'custNameBubble';
            bubble.style.position = 'fixed';
            bubble.style.zIndex = '99999';
            bubble.style.maxWidth = '90vw';
            bubble.style.background = '#111';
            bubble.style.color = '#fff';
            bubble.style.padding = '8px 10px';
            bubble.style.borderRadius = '10px';
            bubble.style.fontSize = '14px';
            bubble.style.boxShadow = '0 6px 18px rgba(0,0,0,0.25)';
            bubble.style.display = 'none';
            document.body.appendChild(bubble);
        }
        bubble.textContent = text;
        const r = el.getBoundingClientRect();
        bubble.style.left = Math.max(10, Math.min(window.innerWidth - bubble.offsetWidth - 10, r.left)) + 'px';
        bubble.style.top = (r.bottom + 8) + 'px';
        bubble.style.display = 'block';
        clearTimeout(bubble._t);
        bubble._t = setTimeout(()=>{ bubble.style.display='none'; }, 2500);
    }
    document.addEventListener('click', function(e){
        const el = e.target.closest('.cust-name, .m-name');
        if(!el) return;
        const txt = el.getAttribute('data-fulltext') || el.textContent || '';
        showBubble(el, txt.trim());
    });
})();

// [2] 모달 입력 포커스 하이라이트 + 자동 스크롤(키보드 가림 완화)
(function initModalFocusUX(){
    function isInModal(el){
        return !!el.closest('.modal, .db-modal');
    }
    document.addEventListener('focusin', function(e){
        const el = e.target;
        if(!(el instanceof HTMLElement)) return;
        if(!isInModal(el)) return;
        el.classList.add('is-focused-input');
        setTimeout(()=>{ try{ el.scrollIntoView({block:'center', behavior:'smooth'});}catch(_){} }, 50);
        setTimeout(()=>{ try{ el.scrollIntoView({block:'center', behavior:'smooth'});}catch(_){} }, 250);
    });
    document.addEventListener('focusout', function(e){
        const el = e.target;
        if(el && el.classList) el.classList.remove('is-focused-input');
    });
})();

// ✅ 품목 사진 업로드 모달 오픈(단일 함수로 통일)
window.openItemPhotoChooser = function(itemId){
  if(!itemId) return;
  const modal = document.getElementById('itemPhotoStepModal');
  if(!modal){ alert("itemPhotoStepModal이 없습니다(view.html 패치 필요)."); return; }

  document.getElementById('itemPhotoTargetItemId').value = String(itemId);
  modal.style.display = 'flex';
  registerModalBackTrap('itemPhotoStepModal', 'closeItemPhotoStepModal');
};

function closeItemPhotoStepModal(options) {
  const modal = document.getElementById('itemPhotoStepModal');
  if (!modal) return;
  modal.style.display = 'none';
  releaseModalBackTrap('itemPhotoStepModal', options || {});
}

// ✅ 전/중/후 버튼 클릭 → 파일 선택 → 업로드
document.addEventListener('click', function(e){
  const btn = e.target.closest('#itemPhotoStepModal .photo-step-btn');
  if(!btn) return;

  const stage = btn.getAttribute('data-step'); // before|during|after
  const itemId = parseInt(document.getElementById('itemPhotoTargetItemId')?.value || '0', 10);
  if(!itemId || !stage){ alert("품목ID/단계가 없습니다."); return; }

  const fileInput = document.getElementById('itemPhotoHiddenFile');
  if(!fileInput){ alert("파일 입력창이 없습니다."); return; }

    fileInput.onchange = async function(){
    try{
      const files = fileInput.files; 
      if(!files || files.length === 0) return;
      
      const fileCount = files.length; // ★ 파일 목록이 날아가기 전에 개수를 안전하게 저장!

      // 로딩 표시 UI (버튼 비활성화 및 스피너)
      const originalText = btn.innerHTML;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
      btn.style.pointerEvents = 'none';

      // 여러 파일 한 번에 전송
      await uploadItemPhotoFile(itemId, stage, files); 

      // 작업기록 자동 등록
      try{ await addAutoHistoryPhotoLog(itemId, stage); }catch(_){}

      fileInput.value = ''; // 여기서 리스트가 날아감
      closeItemPhotoStepModal();
      
      // 버튼 상태 복구
      btn.innerHTML = originalText;
      btn.style.pointerEvents = 'auto';

      if(typeof loadPhotos === 'function') loadPhotos();
      triggerModalSuccessFeedback();

      // ★ 저장해둔 fileCount를 사용하여 출력
      try { showToast(fileCount + '장의 사진 업로드 완료'); } catch(e) { triggerModalSuccessFeedback(); }
    }catch(err){
      alert(err?.message || '업로드 실패');
      fileInput.value = '';
      btn.innerHTML = (stage === 'before' ? '전' : stage === 'during' ? '중' : '후');
      btn.style.pointerEvents = 'auto';
    }
  };

  fileInput.click();
});

// [5] 모바일 키보드 '다음' 대응: 가로사이즈(RawW_#)에서 Enter/Next 시 다음 RawW로 이동
document.addEventListener('keydown', function(e){
    const el = e.target;
    if(!el || !el.id) return;
    if(!/^RawW_\d+$/.test(el.id)) return;
    if(e.key === 'Enter' || e.keyCode === 13){
        e.preventDefault();
        const n = parseInt(el.id.split('_')[1],10);
        const next = document.getElementById('RawW_' + (n+1));
        if(next){ next.focus(); next.select?.(); }
    }
}, true);


// ==========================================================================
// [모바일 & PC 완벽 대응] 가로사이즈(RawW_#)에서 다음(Next)/Tab/Enter 시 다음 줄로 이동
// ==========================================================================
(function initWtoWJump(){
    // --- [핵심] 포커스 하이재킹 (모바일 키패드 '다음' 버튼 강제 이동 무력화) ---
    var isManualAction = false;
    var manualTimer = null;
    var lastFocusedW = null;

    // 1. 사용자가 손가락/마우스로 직접 화면을 터치했는지 감지
    function setManual(e) {
        isManualAction = true;
        clearTimeout(manualTimer);
        // 터치 후 0.3초 이내에 발생하는 포커스만 '수동 터치'로 인정
        manualTimer = setTimeout(function() { isManualAction = false; }, 300);
    }
    document.addEventListener('touchstart', setManual, {capture: true, passive: true});
    document.addEventListener('mousedown', setManual, {capture: true, passive: true});

    // 2. 가로(W) 창에서 커서가 나갈 때, 방금까지 가로 창에 있었다는 것을 기억
    document.addEventListener('focusout', function(e) {
        if(e.target && e.target.id && /^RawW_\d+$/.test(e.target.id)) {
            lastFocusedW = e.target;
            // 0.1초 뒤 기억 삭제 (정상적인 탭 이동 외의 상황 방지)
            setTimeout(function() { if(lastFocusedW === e.target) lastFocusedW = null; }, 100);
        }
    }, true);

    // 3. 세로(H) 창으로 커서가 꽂히는 찰나를 가로채기!
    document.addEventListener('focusin', function(e) {
        var t = e.target;
        if(t && t.id && /^RawH_(\d+)$/.test(t.id)) {
            // "화면을 직접 터치한 것도 아닌데, 방금 전까지 가로(W) 창에 있었다면?" 
            // = 이것은 100% 모바일 키보드에서 '다음'을 누른 것이다!
            if(!isManualAction && lastFocusedW) {
                var n = parseInt(t.id.split('_')[1], 10);
                var prevN = parseInt(lastFocusedW.id.split('_')[1], 10);
                
                if(n === prevN) {
                    var nextW = document.getElementById('RawW_' + (n+1));
                    if(nextW) {
                        e.preventDefault(); // 세로(H)로 가는 것을 막음
                        lastFocusedW = null; 
                        
                        // 즉시 다음 줄의 가로(W) 창으로 강제 순간이동
                        setTimeout(function() {
                            nextW.focus();
                            if(nextW.select) nextW.select();
                        }, 10);
                    }
                }
            }
        }
    }, true);

    // --- [보조] 명시적 Enter 키 감지 (PC 및 특정 안드로이드 보완) ---
    document.addEventListener('keydown', function(e){
        var t = e.target;
        if(!t || !t.id || !/^RawW_\d+$/.test(t.id)) return;
        
        if(e.key === 'Enter' || e.keyCode === 13){
            e.preventDefault();
            var n = parseInt(t.id.split('_')[1], 10);
            var nextW = document.getElementById('RawW_' + (n+1));
            if(nextW){ 
                nextW.focus(); 
                if(nextW.select) nextW.select(); 
            }
        }
    }, true);
})();


// ✅ 하단 고정 버튼(현장/결제/사진/기록)에서 쓰는 통합 탭 이동 함수
function switchTab(type){
    // Swiper가 활성화(모바일)일 때만 동작
    if (typeof _mobileSwiper === 'undefined' || !_mobileSwiper) {
        // PC에서는 해당 섹션으로 스크롤(안전망)
        const idMap = { site:'#section-site', payment:'#section-payment', photos:'#section-photos', log:'#section-log' };
        const sel = idMap[type];
        if(sel){
            const el = document.querySelector(sel);
            if(el) el.scrollIntoView({behavior:'smooth', block:'start'});
        }
        return;
    }

    const map = { site: 0, payment: 1, photos: 2, log: 3 };
    const idx = map[type];

    if (idx === undefined) return;

    try{
        _mobileSwiper.slideToLoop(idx);
        if (typeof scrollToMobileSwiper === 'function') scrollToMobileSwiper();
    }catch(e){
        console.error("switchTab error:", e);
    }
}

// 페이지 로딩 시 초기화 실행
document.addEventListener('DOMContentLoaded', () => {
    initSmartDatalist();
});

// ==========================================
// [스마트 폼] 말풍선 툴팁 제어 로직 (검증/최적화 완료)
// ==========================================

function toggleDetailTooltip() {
    const tooltip = document.getElementById('detailTooltip');
    if (!tooltip) return;
    
    if (tooltip.style.display === 'none' || tooltip.style.display === '') {
        tooltip.style.display = 'block';
        // 부모 모달이 있다면 overflow 속성을 임시로 풀어주어 툴팁이 짤리지 않게 함
        const parentModalBody = tooltip.closest('.modal-body');
        if (parentModalBody) parentModalBody.style.overflow = 'visible';
    } else {
        tooltip.style.display = 'none';
    }
}

// [안전장치] 외부 클릭 감지 함수 (메모리 누수 방지를 위한 기명 함수)
function closeTooltipOnOutsideClick(event) {
    const tooltip = document.getElementById('detailTooltip');
    const toggleBtn = document.querySelector('button[onclick="toggleDetailTooltip()"]');
    
    if (tooltip && tooltip.style.display === 'block') {
        if (!tooltip.contains(event.target) && toggleBtn && !toggleBtn.contains(event.target)) {
            tooltip.style.display = 'none';
        }
    }
}

// 이벤트 리스너 중복 방지 (기존 찌꺼기 제거 후 1개만 부착)
document.removeEventListener('click', closeTooltipOnOutsideClick);
document.addEventListener('click', closeTooltipOnOutsideClick);


// 합계 금액 클릭 시 마진율 말풍선 표시 함수 (view_ui.js 추가용)
// ==========================================================================
// [마법의 커스텀 자동완성 & 마진 팝업 엔진]
// ==========================================================================

window.__smartDB = [];
let activeCustomDropdown = null;

function getSmartDbContext(inputEl) {
    const category = (document.getElementById('catSelect')?.value || '').trim();
    const isMaster = inputEl && inputEl.id === 'Master_Prod';
    let subcategory = '';
    if (isMaster) {
        subcategory = (document.getElementById('blindSubKind')?.value || '').trim();
    } else {
        const inputName = inputEl?.getAttribute('name') || inputEl?.id || '';
        const rowMatch = inputName.match(/ProdName_(\d+)/);
        const rowIdx = rowMatch ? rowMatch[1] : '';
        if (rowIdx) {
            subcategory = (document.querySelector(`[name="SubCat_${rowIdx}"]`) || {}).value || '';
            subcategory = String(subcategory || '').trim();
        }
    }
    return { category, subcategory };
}

// 1. 서버에서 데이터 가져와서 캐싱 (화면 켜질 때 1번만 실행)
async function initSmartDatalist() {
    try {
        const res = await fetch('/api/supplier/smart-db');
        if (res.ok) window.__smartDB = await res.json();
    } catch (err) { console.error("스마트 DB 로딩 실패"); }
}

// 2. 글자 칠 때마다 커스텀 말풍선 띄우기
window.handleCustomAuto = function(inputEl) {
    const keyword = (inputEl.value || '').trim().toLowerCase();
    closeCustomAuto();

    const inputName = inputEl.getAttribute('name') || inputEl.id || '';
    const isMaster = inputEl.id === 'Master_Prod';
    const rowMatch = inputName.match(/ProdName_(\d+)/);
    const rowIdx = rowMatch ? rowMatch[1] : '';
    if (inputEl && inputEl.dataset) inputEl.dataset.productId = "";
    if (isMaster) {
        var masterPid = document.getElementById('Master_ProductID');
        if (masterPid) masterPid.value = "";
        document.querySelectorAll('.sync-pid').forEach(function(el) { el.value = ""; });
    } else if (rowIdx) {
        var rowPid = document.querySelector(`[name="ProductMasterID_${rowIdx}"]`);
        if (rowPid) rowPid.value = "";
    }
    if (!keyword || !Array.isArray(window.__smartDB) || window.__smartDB.length === 0) return;

    const findRowField = function(fieldName) {
        if (!rowIdx) return null;
        return document.querySelector(`[name="${fieldName}_${rowIdx}"]`);
    };
    const colorEl = isMaster ? document.getElementById('Master_Color') : findRowField('Color');
    const optEl = isMaster ? document.getElementById('Master_Opt') : findRowField('Option');
    const memoEl = isMaster ? document.getElementById('Master_Memo') : findRowField('Memo');
    const supplierEl = isMaster ? document.getElementById('Master_Supplier') : findRowField('Supplier');
    const costEl = isMaster ? document.getElementById('Master_CostPrice') : findRowField('CostPrice');

    const currentColor = (colorEl?.value || '').trim().toLowerCase();
    const currentOpt = (optEl?.value || '').trim().toLowerCase();
    const currentMemo = (memoEl?.value || '').trim().toLowerCase();
    const ctx = getSmartDbContext(inputEl);

    const matches = window.__smartDB.filter(item => {
        const pName = (item.name || '').toLowerCase();
        const pCategory = (item.category || '').trim();
        const pSubcategory = (item.subcategory || '').trim();
        const pColor = (item.color || '').toLowerCase();
        const pOpt = (item.option || '').toLowerCase();
        const pNote = (item.note || '').toLowerCase();

        const keywordHit = pName.includes(keyword) || pColor.includes(keyword) || pOpt.includes(keyword) || pNote.includes(keyword);
        if (!keywordHit) return false;
        if (ctx.category && pCategory && pCategory !== ctx.category) return false;
        if (ctx.subcategory && pSubcategory && pSubcategory !== ctx.subcategory) return false;
        if (currentColor && pColor && !pColor.includes(currentColor)) return false;
        if (currentOpt && pOpt && !pOpt.includes(currentOpt)) return false;
        if (currentMemo && pNote && !pNote.includes(currentMemo)) return false;
        return true;
    }).sort((a, b) => {
        const aCat = (a.category || '').trim();
        const bCat = (b.category || '').trim();
        const aSub = (a.subcategory || '').trim();
        const bSub = (b.subcategory || '').trim();

        const aSubScore = ctx.subcategory && aSub === ctx.subcategory ? 1 : 0;
        const bSubScore = ctx.subcategory && bSub === ctx.subcategory ? 1 : 0;
        if (aSubScore !== bSubScore) return bSubScore - aSubScore;

        const aCatScore = ctx.category && aCat === ctx.category ? 1 : 0;
        const bCatScore = ctx.category && bCat === ctx.category ? 1 : 0;
        if (aCatScore !== bCatScore) return bCatScore - aCatScore;

        const aName = (a.name || '').toLowerCase();
        const bName = (b.name || '').toLowerCase();
        return aName.localeCompare(bName);
    }).slice(0, 20);

    if (matches.length === 0) return;

    const applyField = function(el, value, forceFill) {
        if (!el || value === undefined || value === null) return;
        const next = String(value);
        if (!next && !forceFill) return;
        if (!forceFill && String(el.value || '').trim() !== '') return;
        el.value = next;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const drop = document.createElement('div');
    drop.className = 'smart-dropdown';

    matches.forEach(m => {
        const div = document.createElement('div');
        div.className = 'smart-dropdown-item';

        const costStr = m.cost ? m.cost.toLocaleString() + '원' : '';
        const supStr = m.supplier ? m.supplier : '미지정';
        const metaParts = [m.category, m.subcategory, m.color, m.option, m.note].filter(Boolean);
        const metaHtml = metaParts.length ? `<div class="sd-meta" style="font-size:11px; color:#868e96; margin-top:2px;">${metaParts.join(' / ')}</div>` : '';

        div.innerHTML = `
            <div class="sd-left">
                <span class="sd-sup">${supStr}</span>
                <span class="sd-prod">${m.name}</span>
                ${metaHtml}
            </div>
            <span class="sd-cost">${costStr}</span>
        `;

        div.onclick = function(e) {
            e.stopPropagation();
            inputEl.value = m.name || '';
            if (inputEl && inputEl.dataset) inputEl.dataset.productId = String(m.product_id || "");
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            inputEl.dispatchEvent(new Event('change', { bubbles: true }));

            if (isMaster) {
                var masterPid = document.getElementById('Master_ProductID');
                if (masterPid) masterPid.value = String(m.product_id || "");
                document.querySelectorAll('.sync-pid').forEach(function(el) {
                    el.value = String(m.product_id || "");
                });
            } else if (rowIdx) {
                var rowPid = document.querySelector(`[name="ProductMasterID_${rowIdx}"]`);
                if (rowPid) rowPid.value = String(m.product_id || "");
            }

            applyField(colorEl, m.color || '', isMaster);
            applyField(optEl, m.option || '', isMaster);
            applyField(memoEl, m.note || '', false);

            applyField(supplierEl, m.supplier || '', false);
            applyField(costEl, m.cost ? formatComma(m.cost) : '', false);

            if (isMaster && typeof syncBlindData === 'function') {
                const count = parseInt(document.getElementById('blindSplit')?.value) || 1;
                syncBlindData(count, 'ALL');
            }

            closeCustomAuto();
        };
        drop.appendChild(div);
    });

    const parentPos = inputEl.parentNode.style.position;
    if(parentPos !== 'relative' && parentPos !== 'absolute') {
        inputEl.parentNode.style.position = 'relative';
    }

    inputEl.parentNode.appendChild(drop);
    drop.style.top = (inputEl.offsetTop + inputEl.offsetHeight + 4) + 'px';

    activeCustomDropdown = drop;
};

window.closeCustomAuto = function() {
    if (activeCustomDropdown) {
        activeCustomDropdown.remove();
        activeCustomDropdown = null;
    }
};

// 바깥 바탕 화면 터치 시 자동완성 닫기
document.addEventListener('click', function(e) {
    if (activeCustomDropdown && !activeCustomDropdown.contains(e.target) && !e.target.classList.contains('inp-prod')) {
        closeCustomAuto();
    }
});


// 3. 금액 터치 시 마진율 말풍선 표시 엔진
/* ==========================================================================
   [Voice Draft /view panel] - safe review flow
   ========================================================================== */
window.__currentVoiceDraft = null;

function __voiceViewToast(msg) {
    try { showToast(msg); } catch(e) { alert(msg); }
}

function getViewVoiceContext() {
    let siteName = '';
    let customerId = null;
    let currentItems = [];
    try {
        const nm = document.querySelector('.cust-name, .m-name');
        siteName = nm ? (nm.textContent || '').trim() : '';
        customerId = window.g_customerId || null;
        document.querySelectorAll('tr[data-id]').forEach(tr => {
            const txt = tr.innerText || '';
            currentItems.push({ raw: txt.slice(0, 140) });
        });
    } catch(e) {}
    return {
        orderId: (typeof g_orderId !== 'undefined') ? g_orderId : null,
        customerId,
        siteName,
        mainStatus: window.g_progressStatus || '',
        currentItems
    };
}

function __normalizeVoiceText(raw) {
    return String(raw || '').replace(/\s+/g, ' ').trim();
}

function __parseVoiceTime(text) {
    const now = new Date();
    let m = text.match(/내일\s*(오전|오후)?\s*(\d{1,2})시/);
    if (m) {
        let hour = parseInt(m[2], 10);
        if (m[1] === '오후' && hour < 12) hour += 12;
        const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, hour, 0, 0);
        return d.toISOString().slice(0,16).replace('T',' ');
    }
    m = text.match(/오늘\s*(오전|오후)?\s*(\d{1,2})시/);
    if (m) {
        let hour = parseInt(m[2], 10);
        if (m[1] === '오후' && hour < 12) hour += 12;
        const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hour, 0, 0);
        return d.toISOString().slice(0,16).replace('T',' ');
    }
    return null;
}

function __buildLocalVoiceDraft(rawText, context) {
    const text = __normalizeVoiceText(rawText);
    const locations = ['거실','안방','작은방','주방','베란다','드레스룸'];
    const products = ['차르르','암막커튼','쉬폰','블라인드','롤스크린','허니콤'];

    let intentType = 'EXISTING_CUSTOMER';
    let actionType = 'WORK_LOG_ADD';

    if (/(변경|바꿔|연기|방문요청|내일|모레|오늘\s*\d|오전|오후)/.test(text)) {
        actionType = 'SCHEDULE_UPDATE';
    }
    if (/(추가|차르르|암막|블라인드|롤스크린|허니콤)/.test(text)) {
        actionType = actionType === 'SCHEDULE_UPDATE' ? 'SCHEDULE_UPDATE+ITEM_ADD' : 'ITEM_ADD';
    }
    if (/(A\/S|AS|수선|고장)/i.test(text)) {
        actionType = 'AS_REQUEST';
    }

    const scheduleUpdates = [];
    const t = __parseVoiceTime(text);
    if (t) {
        scheduleUpdates.push({
            field: 'visit_datetime',
            currentValue: null,
            proposedValue: t,
            status: 'pending'
        });
    }

    const foundLocs = locations.filter(v => text.includes(v));
    const foundProds = products.filter(v => text.includes(v));
    const itemAdds = [];
    if (foundLocs.length && foundProds.length) {
        foundLocs.forEach((loc, i) => {
            const prod = foundProds[i] || foundProds[0];
            itemAdds.push({ location: loc, product: prod, status: 'pending' });
        });
    } else if (foundProds.length) {
        foundProds.forEach(prod => itemAdds.push({ location: '', product: prod, status: 'pending' }));
    }

    const memoAdds = [{ text, status: 'pending' }];

    let confidence = 0.55;
    if (scheduleUpdates.length) confidence += 0.10;
    if (itemAdds.length) confidence += 0.15;
    if (context?.orderId) confidence += 0.10;
    confidence = Math.min(confidence, 0.90);

    return {
        localOnly: true,
        draftId: null,
        intentType,
        actionType,
        pageContext: 'view',
        confidence,
        rawText: text,
        context: context || {},
        proposals: { scheduleUpdates, itemAdds, memoAdds }
    };
}

async function openVoiceInputForView() {
    const rawText = prompt('현재 일정에 남길 음성 내용을 입력하세요.\n예) 거실 블라인드 추가 내일 12시 방문요청');
    if (!rawText || !String(rawText).trim()) return;

    const payload = {
        pageContext: 'view',
        rawText: rawText,
        context: getViewVoiceContext()
    };

    let draft = null;
    try {
        const res = await apiCreateVoiceDraft(payload);
        draft = res && (res.draft || res.DraftJSON || res);
        if (draft) draft.draftId = res.draftId || res.DraftID || null;
    } catch(e) {
        draft = __buildLocalVoiceDraft(rawText, payload.context);
    }

    if (!draft) {
        __voiceViewToast('음성 초안을 생성하지 못했습니다.');
        return;
    }

    window.__currentVoiceDraft = draft;
    renderVoiceDraftPanel(draft);
    openVoiceDraftPanel();
}

function openVoiceDraftPanel() {
    document.getElementById('voiceDraftOverlay')?.classList.add('open');
    const panel = document.getElementById('voiceDraftPanel');
    if (panel) {
        panel.classList.add('open');
        panel.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }
}

function closeVoiceDraftPanel() {
    document.getElementById('voiceDraftOverlay')?.classList.remove('open');
    const panel = document.getElementById('voiceDraftPanel');
    if (panel) {
        panel.classList.remove('open');
        panel.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }
}

function __renderVoiceProposalList(containerId, items, type) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!items || !items.length) {
        el.innerHTML = '<div class="voice-empty">제안 없음</div>';
        return;
    }

    el.innerHTML = items.map((item, idx) => {
        if (type === 'schedule') {
            return `
            <div class="voice-proposal-card schedule">
              <label class="voice-proposal-main">
                <input type="checkbox" data-voice-type="scheduleUpdates" data-voice-idx="${idx}" checked>
                <div class="voice-proposal-content">
                  <div class="voice-proposal-title">방문 일정 변경 제안</div>
                  <div class="voice-proposal-sub">현재: ${item.currentValue || '미지정'}</div>
                  <div class="voice-proposal-sub">제안: ${item.proposedValue || '-'}</div>
                </div>
              </label>
            </div>`;
        }
        if (type === 'item') {
            return `
            <div class="voice-proposal-card item">
              <label class="voice-proposal-main">
                <input type="checkbox" data-voice-type="itemAdds" data-voice-idx="${idx}" checked>
                <div class="voice-proposal-content">
                  <div class="voice-proposal-title">${item.location ? item.location + ' / ' : ''}${item.product || '-'}</div>
                  <div class="voice-proposal-sub">품목 추가 제안</div>
                </div>
              </label>
            </div>`;
        }
        return `
        <div class="voice-proposal-card memo">
          <label class="voice-proposal-main">
            <input type="checkbox" data-voice-type="memoAdds" data-voice-idx="${idx}" checked>
            <div class="voice-proposal-content">
              <div class="voice-proposal-title">메모 제안</div>
              <div class="voice-proposal-sub">${item.text || '-'}</div>
            </div>
          </label>
        </div>`;
    }).join('');
}

function renderVoiceDraftPanel(draft) {
    const proposals = draft.proposals || {};
    document.getElementById('voiceRawText').textContent = draft.rawText || '-';
    document.getElementById('voiceIntentType').textContent = draft.intentType || '-';
    document.getElementById('voiceActionType').textContent = draft.actionType || '-';
    document.getElementById('voiceConfidence').textContent = Math.round((draft.confidence || 0) * 100) + '%';

    __renderVoiceProposalList('voiceScheduleUpdates', proposals.scheduleUpdates || [], 'schedule');
    __renderVoiceProposalList('voiceItemAdds', proposals.itemAdds || [], 'item');
    __renderVoiceProposalList('voiceMemoAdds', proposals.memoAdds || [], 'memo');
}

function collectVoiceDraftSelections() {
    const payload = { scheduleUpdates: [], itemAdds: [], memoAdds: [] };
    document.querySelectorAll('#voiceDraftPanel input[type="checkbox"][data-voice-type]').forEach(chk => {
        if (!chk.checked) return;
        const t = chk.getAttribute('data-voice-type');
        const idx = parseInt(chk.getAttribute('data-voice-idx'), 10);
        if (!Number.isNaN(idx) && Array.isArray(payload[t])) payload[t].push(idx);
    });
    return payload;
}

async function applyVoiceDraftSelections() {
    const draft = window.__currentVoiceDraft;
    if (!draft) return;

    const sels = collectVoiceDraftSelections();
    const total = sels.scheduleUpdates.length + sels.itemAdds.length + sels.memoAdds.length;
    if (!total) {
        __voiceViewToast('선택된 항목이 없습니다.');
        return;
    }

    const oid = (typeof g_orderId !== 'undefined') ? g_orderId : null;

    // 1) 가장 안전한 실제 반영: 작업기록/메모 저장
    if (oid) {
        for (const idx of sels.memoAdds) {
            const item = draft.proposals?.memoAdds?.[idx];
            if (item?.text) {
                try { await addVoiceHistoryLog(oid, '메모', `[음성반영] ${item.text}`); } catch(e) {}
            }
        }
        for (const idx of sels.scheduleUpdates) {
            const item = draft.proposals?.scheduleUpdates?.[idx];
            if (item?.proposedValue) {
                try { await addVoiceHistoryLog(oid, '상태변경', `[음성초안/일정변경제안] 방문시간 제안: ${item.proposedValue}`); } catch(e) {}
            }
        }
        for (const idx of sels.itemAdds) {
            const item = draft.proposals?.itemAdds?.[idx];
            const line = `${item?.location ? item.location + ' / ' : ''}${item?.product || ''}`.trim();
            if (line) {
                try { await addVoiceHistoryLog(oid, '상태변경', `[음성초안/품목추가제안] ${line}`); } catch(e) {}
            }
        }
    }

    // 2) 초안 상태 변경 / 로그 저장
    try {
        if (draft.draftId) {
            await apiApplyVoiceDraft({
                draftId: draft.draftId,
                applySelections: sels
            });
        }
    } catch(e) {
        console.warn('voice apply api failed', e);
    }

    __voiceViewToast('선택한 음성 제안을 작업기록으로 반영했습니다.');
    closeVoiceDraftPanel();
}

async function saveVoiceDraftAsMemoOnly() {
    const draft = window.__currentVoiceDraft;
    if (!draft) return;
    const oid = (typeof g_orderId !== 'undefined') ? g_orderId : null;
    if (!oid) {
        __voiceViewToast('주문 번호를 찾지 못했습니다.');
        return;
    }
    try {
        await addVoiceHistoryLog(oid, '메모', `[음성원문] ${draft.rawText || ''}`);
        if (draft.draftId) {
            await apiApplyVoiceDraft({ draftId: draft.draftId, applySelections: { memoOnly: true } });
        }
        __voiceViewToast('음성 원문을 메모로 저장했습니다.');
        closeVoiceDraftPanel();
    } catch(e) {
        console.error(e);
        __voiceViewToast('메모 저장 중 오류가 발생했습니다.');
    }
}

async function discardCurrentVoiceDraft() {
    const draft = window.__currentVoiceDraft;
    try {
        if (draft?.draftId) {
            await apiDiscardVoiceDraft(draft.draftId);
        }
    } catch(e) {
        console.warn('discard failed', e);
    }
    closeVoiceDraftPanel();
    __voiceViewToast('음성 초안을 폐기했습니다.');
}

/* margin popup final override */
window.showMarginPopup = function(element, price, qty, explicitCost) {
    const cleanNum = (v) => parseFloat(String(v || '').replace(/,/g, '')) || 0;
    const cost = cleanNum(explicitCost);
    document.querySelectorAll('.margin-bubble').forEach(el => el.remove());

    if (cost <= 0) {
        __voiceViewToast('매입 원가가 입력되지 않았습니다.');
        return;
    }

    const p = cleanNum(price);
    const q = cleanNum(qty);
    const totalSales = p * q;
    const totalCost = cost * q;
    const margin = totalSales - totalCost;
    const marginRate = totalSales > 0 ? Math.round((margin / totalSales) * 100) : 0;

    const bubble = document.createElement('div');
    bubble.className = 'margin-bubble';
    bubble.innerHTML = `✨ 마진: ${margin.toLocaleString()}원 <span style="color:${margin >= 0 ? '#ffd43b' : '#ff6b6b'};">(${marginRate}%)</span>`;
    bubble.style.cssText = "position:absolute; background:#212529; color:#fff; padding:6px 12px; border-radius:8px; font-size:12px; font-weight:bold; z-index:9999; bottom:100%; right:0; margin-bottom:5px; white-space:nowrap;";
    element.style.position = "relative";
    element.appendChild(bubble);
    setTimeout(() => { if (bubble) bubble.remove(); }, 1600);
};

window.triggerMarginPopup = function(el, idx) {
    const get = (sel) => document.querySelector(sel);
    const price = get(`input[name="Price_${idx}"]`)?.value || "0";
    const qty = get(`input[name="Qty_${idx}"]`)?.value || "0";
    const rowCost = get(`input[name="CostPrice_${idx}"]`)?.value || get(`#CostPrice_${idx}`)?.value || '';
    const masterCost = document.getElementById('Master_CostPrice')?.value || '';
    window.showMarginPopup(el, price, qty, rowCost || masterCost || '0');
};

window.triggerBlindMarginPopup = function(el) {
    const cleanNum = (v) => parseFloat(String(v || '').replace(/,/g, '')) || 0;
    const price = document.getElementById('Master_Price')?.value || "0";
    const masterCost = document.getElementById('Master_CostPrice')?.value || "0";
    let totalQty = 0;
    const cnt = parseInt(document.getElementById('blindSplit')?.value) || 1;
    for (let i = 1; i <= cnt; i++) {
        const qStr = document.getElementById('Qty_' + i)?.value || "0";
        totalQty += cleanNum(qStr);
    }
    window.showMarginPopup(el, price, totalQty, masterCost);
};



/* ========================================================================== 
   [Voice Draft /view panel] - phase2 save connection override
   ========================================================================== */
function __voiceBuildHistoryLinesFromSelections(draft, sels) {
    const lines = [];
    const p = (draft && draft.proposals) || {};
    (sels.memoAdds || []).forEach(idx => {
        const item = p.memoAdds && p.memoAdds[idx];
        if (item && item.text) lines.push({type:'메모', text:`[음성반영] ${item.text}`});
    });
    (sels.scheduleUpdates || []).forEach(idx => {
        const item = p.scheduleUpdates && p.scheduleUpdates[idx];
        if (item && item.proposedValue) {
            lines.push({type:'상태변경', text:`[음성초안/일정변경제안] ${item.field || 'schedule'} -> ${item.proposedValue}`});
        }
    });
    (sels.itemAdds || []).forEach(idx => {
        const item = p.itemAdds && p.itemAdds[idx];
        if (!item) return;
        const line = `${item.location ? item.location + ' / ' : ''}${item.product || ''}`.trim();
        if (line) lines.push({type:'상태변경', text:`[음성초안/품목추가제안] ${line}`});
    });
    return lines;
}

async function applyVoiceDraftSelections() {
    const draft = window.__currentVoiceDraft;
    if (!draft) return;

    const sels = collectVoiceDraftSelections();
    const total = (sels.scheduleUpdates || []).length + (sels.itemAdds || []).length + (sels.memoAdds || []).length;
    if (!total) {
        __voiceViewToast('선택된 항목이 없습니다.');
        return;
    }

    const oid = (typeof g_orderId !== 'undefined') ? g_orderId : null;
    const applyBtn = document.getElementById('voiceApplyBtn');
    if (applyBtn) { applyBtn.disabled = true; applyBtn.dataset.loading = '1'; }

    try {
        let apiRes = null;
        if (draft.draftId) {
            apiRes = await apiApplyVoiceDraft({ draftId: draft.draftId, applySelections: sels });
        }

        const historyLines = __voiceBuildHistoryLinesFromSelections(draft, sels);
        if (oid && historyLines.length) {
            for (const row of historyLines) {
                await addVoiceHistoryLog(oid, row.type, row.text);
            }
        }

        __voiceViewToast('선택한 음성 제안을 작업기록으로 반영했습니다.');
        window.__currentVoiceDraft = null;
        closeVoiceDraftPanel();

        try {
            if (typeof filterHistory === 'function') {
                const btnMemo = document.getElementById('btnTabMemo');
                filterHistory('메모', btnMemo || null);
            }
        } catch(e) {}

        return apiRes;
    } catch(e) {
        console.error(e);
        __voiceViewToast('음성 반영 중 오류가 발생했습니다.');
    } finally {
        if (applyBtn) { applyBtn.disabled = false; delete applyBtn.dataset.loading; }
    }
}

async function saveVoiceDraftAsMemoOnly() {
    const draft = window.__currentVoiceDraft;
    if (!draft) return;
    const oid = (typeof g_orderId !== 'undefined') ? g_orderId : null;
    if (!oid) {
        __voiceViewToast('주문 번호를 찾지 못했습니다.');
        return;
    }

    const btn = document.getElementById('voiceMemoOnlyBtn');
    if (btn) { btn.disabled = true; btn.dataset.loading = '1'; }
    try {
        await addVoiceHistoryLog(oid, '메모', `[음성원문] ${draft.rawText || ''}`);
        if (draft.draftId) {
            await apiApplyVoiceDraft({ draftId: draft.draftId, applySelections: { memoOnly: true } });
        }
        __voiceViewToast('음성 원문을 메모로 저장했습니다.');
        window.__currentVoiceDraft = null;
        closeVoiceDraftPanel();
    } catch(e) {
        console.error(e);
        __voiceViewToast('메모 저장 중 오류가 발생했습니다.');
    } finally {
        if (btn) { btn.disabled = false; delete btn.dataset.loading; }
    }
}

async function discardCurrentVoiceDraft() {
    const draft = window.__currentVoiceDraft;
    const btn = document.getElementById('voiceDiscardBtn');
    if (btn) { btn.disabled = true; btn.dataset.loading = '1'; }
    try {
        if (draft && draft.draftId) {
            await apiDiscardVoiceDraft(draft.draftId);
        }
        window.__currentVoiceDraft = null;
        closeVoiceDraftPanel();
        __voiceViewToast('음성 초안을 폐기했습니다.');
    } catch(e) {
        console.warn('discard failed', e);
        __voiceViewToast('폐기 중 오류가 발생했습니다.');
    } finally {
        if (btn) { btn.disabled = false; delete btn.dataset.loading; }
    }
}
