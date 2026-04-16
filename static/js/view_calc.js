/* ==========================================================================
   [view_calc.js] 계산 로직, 유틸리티, 전역 변수
   (원본 view.js의 로직을 그대로 이관함)
   ========================================================================== */

// 1. 전역 변수 및 초기화 (모든 파일에서 공유됨)
var g_orderId = null;
var g_fpInstance = null;
var g_scheduleData = {};
var g_blindHeightState = {};
var isProcessing = false;

// 서명 관련 전역 변수
var canvas = null;
var ctx = null;
var isDrawing = false;
var debugEl = null;

// 대시보드 스냅샷 (전역 객체)
window.DASHBOARD_SNAPSHOT = window.DASHBOARD_SNAPSHOT || {};

// 2. 유틸리티 함수 (포맷팅)
function formatComma(str) { 
    if (str === null || str === undefined || str === "") return "";
    const normalized = String(str).replace(/,/g, "").replace(/[^\d.-]/g, "").trim();
    if (!normalized || normalized === "-" || normalized === "." || normalized === "-.") return "";

    const sign = normalized.startsWith("-") ? "-" : "";
    const unsigned = normalized.replace(/^-/, "");
    const parts = unsigned.split(".");
    const intPart = (parts[0] || "0").replace(/^0+(?=\d)/, "");
    const fracPart = parts.length > 1 ? parts.slice(1).join("").replace(/[^\d]/g, "") : "";
    const formattedInt = (intPart || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    const trimmedFrac = fracPart.replace(/0+$/, "");

    return sign + formattedInt + (trimmedFrac ? "." + trimmedFrac : "");
}

function cleanNum(str) { 
    return parseFloat(String(str).replace(/,/g, "")) || 0; 
}

function normalizeDiscountAmount(discount, isVat) {
    var raw = parseFloat(discount) || 0;
    if (!isVat) return raw;
    return Math.round(raw / 1.1);
}

function calcPaymentAmounts(subTotal, discountInput, deposit, isVat) {
    var normalizedDiscount = normalizeDiscountAmount(discountInput, isVat);
    var supplyPrice = subTotal - normalizedDiscount;
    if (supplyPrice < 0) supplyPrice = 0;

    var vat = isVat ? Math.round(supplyPrice * 0.1) : 0;
    var finalTotal = supplyPrice + vat;
    var balance = finalTotal - deposit;

    return {
        normalizedDiscount: normalizedDiscount,
        supplyPrice: supplyPrice,
        vat: vat,
        finalTotal: finalTotal,
        balance: balance
    };
}

function smartFloat(val, precision) {
    if (val === undefined || val === null || val === "") return "";
    let n = parseFloat(String(val).replace(/,/g, ""));
    if (isNaN(n)) return val;
    return parseFloat(n.toFixed(precision)).toString();
}

function formatPhoneDot(el) {
    // input element인 경우와 문자열인 경우 분기 처리
    var str = (el.value !== undefined) ? el.value : String(el);
    str = str.replace(/[^0-9]/g, ''); 
    var tmp = '';
    if(str.length < 4) tmp = str;
    else if(str.length < 7) tmp = str.substr(0, 3) + '.' + str.substr(3);
    else if(str.length < 11) tmp = str.substr(0, 3) + '.' + str.substr(3, 3) + '.' + str.substr(6);
    else tmp = str.substr(0, 3) + '.' + str.substr(3, 4) + '.' + str.substr(7);
    
    if(el.value !== undefined) el.value = tmp;
    return tmp;
}

// 3. 금액 계산 (메인 견적)
function calcFinalPrice() {
    var getNum = function(id) { 
        var el = document.getElementById(id); 
        return el ? (parseFloat(String(el.value).replace(/,/g, "")) || 0) : 0; 
    };

    var subTotal = getNum('raw-total-amt'); 
    var discount = getNum('inp-discount');  
    var deposit  = getNum('inp-deposit');   
    var isVat = document.getElementById('chk-vat') ? document.getElementById('chk-vat').checked : false;
    
    var amounts = calcPaymentAmounts(subTotal, discount, deposit, isVat);
    var vat = amounts.vat;
    var finalTotal = amounts.finalTotal;
    var balance = amounts.balance;
    
    var strTotal = finalTotal.toLocaleString() + "원";
    var strBalance = balance.toLocaleString() + "원";

    // 화면 업데이트
    if(document.getElementById('live-price')) document.getElementById('live-price').innerText = finalTotal.toLocaleString();
    
    if(document.getElementById('pcDispFinal') && !document.getElementById('live-price')) {
        document.getElementById('pcDispFinal').innerText = strTotal;
    }
    if(document.getElementById('mobileDispFinal')) document.getElementById('mobileDispFinal').innerText = strTotal;
    
    if(document.getElementById('dispFinal')) document.getElementById('dispFinal').innerText = strBalance;
    if(document.getElementById('dispSubTotal')) document.getElementById('dispSubTotal').innerText = subTotal.toLocaleString() + "원";
    if(document.getElementById('dispVat')) document.getElementById('dispVat').innerText = isVat ? vat.toLocaleString() + "원" : "별도";
}

// 4. 모달창(수정/결제) 금액 계산
function calcModalPrice() {
    // 결제 모달 계산
    if(document.getElementById('payModal') && document.getElementById('payModal').style.display !== 'none') {
        var getNum = function(id) { 
            var el = document.getElementById(id); 
            return el ? (parseFloat(String(el.value).replace(/,/g, "")) || 0) : 0; 
        };
        var subTotal = getNum('raw-total-amt');
        var discount = getNum('inp-discount');
        var deposit  = getNum('inp-deposit');
        var isVat = document.getElementById('payVatInput').checked;
        
        var amounts = calcPaymentAmounts(subTotal, discount, deposit, isVat);
        var amountToPay = amounts.balance;

        var dispEl = document.getElementById('modalFinalPrice');
        if (dispEl) dispEl.innerText = amountToPay.toLocaleString() + "원";
        return;
    }

    // 품목 수정 모달 계산 (기존 로직 유지용)
    // view.js 원본에는 이 함수 내부에 분기 처리는 없었으나, 
    // calcModalPrice가 호출되는 컨텍스트에 따라 다를 수 있어 보존함.
}

// 5. 커튼/블라인드 수량 및 합계 계산 (동기화 로직 포함)
function syncBlindData(count, type, isInit) {
    var fieldMap = {
        ProdName: { suffix: 'Prod', cls: 'sync-prod' },
        Color: { suffix: 'Color', cls: 'sync-color' },
        Option: { suffix: 'Opt', cls: 'sync-opt' },
        Price: { suffix: 'Price', cls: 'sync-price' },
        Memo: { suffix: 'Memo', cls: 'sync-memo' },
        H: { suffix: 'H', cls: null }
    };
    var types = (type === 'ALL') ? ['ProdName', 'Color', 'Option', 'Price', 'Memo', 'H'] : [type];

    types.forEach(function(t) {
        var meta = fieldMap[t];
        if (!meta) return;

        var masterInput = document.getElementById('Master_' + meta.suffix);
        if (!masterInput) return;
        var masterVal = masterInput.value;

        if (t === 'H') {
            for (var i = 1; i <= count; i++) {
                var hidden = document.querySelector(`input[name="H_${i}"]`);
                if (hidden) hidden.value = masterVal;
                if (!isInit && typeof calcBlindRowArea === 'function') {
                    calcBlindRowArea(i);
                }
            }
            return;
        }

        document.querySelectorAll('.' + meta.cls).forEach(function(el) {
            el.value = masterVal;
        });
        if (t === 'Price' && typeof calcBlindTotalPrice === 'function') {
            calcBlindTotalPrice();
        }
    });
}

function syncInput(el, idx, type) {
    var cat = document.getElementById('catSelect').value;
    var val = el.value;
    if (type === 'H') {
        checkLadderSafety(val);
    }

    if (cat === '커튼' && document.getElementById('typeMix').checked && idx == '1') {
        if(type === 'W') { document.querySelector(`input[name="W_2"]`).value = val; calcQty(2); }
        if(type === 'H') { document.querySelector(`input[name="H_2"]`).value = val; calcQty(2); }
    }
    if (cat === '블라인드') {
        var cnt = parseInt(document.getElementById('blindSplit').value);
        if(el.name.indexOf('ProdName') > -1 || el.name.indexOf('Color') > -1 || el.name.indexOf('Price') > -1 || el.name.indexOf('H_') > -1) {
            var targetName = el.name.split('_')[0];
            for(var i=1; i<=cnt; i++) {
                if(i != idx) {
                    var target = document.querySelector(`input[name="${targetName}_${i}"]`);
                    if(target) { target.value = val; if(targetName==='H') calcQty(i); }
                }
            }
        }
    }
}

function syncEtcData() {
    var val = document.getElementById('inpEtcKind').value.trim();
    var hiddenInput = document.querySelector('input[name="SubCat_1"]');
    if(hiddenInput) hiddenInput.value = val || "기타";
    var badge = document.querySelector('#dynamicArea .item-row-badge') || document.querySelector('.dynamic-row .label-badge');
    if(badge) badge.innerText = val || "기타";
}

function calcQty(idx) {
    var w = parseFloat(document.querySelector(`input[name="W_${idx}"]`).value) || 0;
    var h = parseFloat(document.querySelector(`input[name="H_${idx}"]`).value) || 0;
    var cat = document.getElementById('catSelect').value;
    var qtyField = document.getElementById(`Qty_${idx}`);
    
    if (w > 0) {
        if (cat === '커튼') {
            var optElem = document.querySelector(`select[name="Option_${idx}"]`);
            var ratio = 1.5; 
            if(optElem) { if(optElem.value.indexOf('나비') > -1) ratio = 2.0; }
            else { 
                var optInput = document.querySelector(`input[name="Option_${idx}"]`);
                if(optInput && optInput.value.indexOf('나비') > -1) ratio = 2.0;
            }
            qtyField.value = Math.ceil((w * ratio) / 150); 
        } else if (cat === '블라인드') {
            // 블라인드는 calcBlindRowArea에서 처리됨
            if (h > 0) qtyField.value = ((w * h) / 10000).toFixed(2);
        }
    }
    if (cat !== '블라인드') calcCurtainEtcTotal(idx);
}

function reCalcBlindQty() {
    var cnt = parseInt(document.getElementById('blindSplit').value) || 1;
    for(var i=1; i<=cnt; i++) {
        calcBlindRowArea(i);
    }
}

function calcBlindRowArea(idx) {
    var elW = document.getElementById('RawW_' + idx);
    var elH = document.getElementById('RawH_' + idx);
    var elQty = document.getElementById('Qty_' + idx);
    if(!elW || !elH || !elQty) return;

    var w = parseFloat(elW.value) || 0;
    var h = parseFloat(elH.value) || 0;
    
    checkLadderSafety(h);

    if (w > 0 && h > 0) {
        var calcH = (h < 150) ? 150 : h;
        var rawQty = (w * calcH) / 10000;
        var minInput = document.getElementById('blindSubKind');
        var minVal = minInput ? (parseFloat(minInput.getAttribute('data-min')) || 0) : 0;
        var finalQty = (rawQty < minVal) ? minVal : rawQty;
        elQty.value = parseFloat(finalQty.toFixed(2));
    } else {
        elQty.value = "";
    }
    calcBlindTotalPrice();
}

function calcBlindTotalPrice() {
    var totalQty = 0.0;
    var priceStr = document.getElementById('Master_Price').value;
    var price = parseFloat(priceStr.replace(/,/g, "")) || 0;
    document.querySelectorAll('input[name^="Qty_"]').forEach(function(el) {
        totalQty += parseFloat(el.value) || 0;
    });
    var totalAmt = Math.round(totalQty * price);
    var disp = document.getElementById('blindRealtimeTotal');
    if(disp) {
        if(totalAmt > 0) disp.innerText = totalAmt.toLocaleString() + "원";
        else disp.innerText = "0원";
    }
}

function calcCurtainEtcTotal(idx) {
    var qtyInput = document.getElementById(`Qty_${idx}`);
    var qty = parseFloat(qtyInput ? qtyInput.value : 0) || 0;
    var priceInput = document.querySelector(`input[name="Price_${idx}"]`);
    var priceStr = priceInput ? priceInput.value : "0";
    var price = parseFloat(priceStr.replace(/,/g, "")) || 0;
    var total = Math.round(qty * price);
    var span = document.getElementById(`RowTotal_${idx}`);
    if (span) {
        if (total > 0) span.innerText = total.toLocaleString() + "원";
        else span.innerText = "0원";
    }
}

function syncBlindHeight(val) {
    var count = parseInt(document.getElementById('blindSplit').value) || 1;
    for(var i=2; i<=count; i++) {
        if(!g_blindHeightState[i]) {
            var el = document.getElementById('RawH_'+i);
            if(el) { el.value = val; calcBlindRowArea(i); }
        }
    }
    updateBlindAggregates();
}

function updateBlindAggregates() {
    var count = parseInt(document.getElementById('blindSplit').value) || 1;
    var sizeParts = [];
    var qtyParts = [];
    
    for(var i=1; i<=count; i++) {
        var w = document.getElementById('RawW_' + i).value;
        var h = document.getElementById('RawH_' + i).value;
        var handle = document.getElementById('Handle_' + i).value;
        var cord = document.getElementById('CordLen_' + i).value; 
        var qty = document.getElementById('Qty_' + i).value;
        
        if(w && w.trim() !== "") {
            var hVal = h ? h : "0";
            var sizeStr = `${w}x${hVal}(${handle})`;
            if(cord && cord.trim() !== "") sizeStr += ` 줄${cord.trim()}`;
            sizeParts.push(sizeStr);
            var qVal = qty ? parseFloat(qty) : 0;
            qtyParts.push(qVal);
        }
    }
    
    var inputSize = document.getElementById('TotalBlindSize');
    var inputQty = document.getElementById('TotalBlindQty');
    
    if(inputSize) inputSize.value = sizeParts.join(", ");
    if(inputQty) inputQty.value = qtyParts.join(", ");
}

// 6. 안전 체크 (긴사다리)
function checkLadderSafety(h) {
    var val = parseFloat(h);
    if (val >= 270) {
        var btns = document.querySelectorAll('.check-btn');
        var targetBtn = null;
        
        btns.forEach(function(b) {
            var text = b.innerText || "";
            var dataVal = b.getAttribute('data-val') || "";
            if (text.indexOf('긴사다리') > -1 || dataVal.indexOf('긴사다리') > -1) {
                targetBtn = b;
            }
        });

        if (targetBtn && !targetBtn.classList.contains('active')) {
            targetBtn.classList.add('active');
            if (typeof saveSiteInfo === 'function') {
                saveSiteInfo(true); 
            }
            if (typeof showToast === 'function') {
                showToast("⚠️ 높이 270cm 이상: [긴사다리] 항목이 자동 체크되었습니다.");
            }
        }
    }
}

// 7. 자동 레일 계산
function autoCalcRails() {
    var rows = document.querySelectorAll('.excel-table tbody tr');
    var railCounts = {}; 
    var hasCurtain = false;

    rows.forEach(function(row) {
        var cat = row.getAttribute('data-cat');
        var widthVal = parseFloat(row.getAttribute('data-width')) || 0;
        
        if (cat === '커튼' && widthVal > 0) {
            hasCurtain = true;
            var ja = Math.ceil(widthVal / 30);
            if (ja < 6) ja = 6; 
            if (!railCounts[ja]) railCounts[ja] = 0;
            railCounts[ja]++;
        }
    });

    var inp = document.getElementById('inpChecklist');
    if (!inp) return;

    var newRailStr = "";
    if (hasCurtain) {
        var parts = [];
        Object.keys(railCounts).sort(function(a,b){return a-b}).forEach(function(ja) {
            parts.push(ja + "자(" + railCounts[ja] + ")");
        });
        newRailStr = "레일: " + parts.join(", ");
    }

    var currentText = inp.value;
    var updatedText = currentText;

    if (currentText.indexOf("레일:") > -1) {
        updatedText = currentText.replace(/레일:.*?(?=\/|$|\n)/, newRailStr);
    } else {
        if (newRailStr !== "") updatedText = (currentText.trim() === "") ? newRailStr : newRailStr + " / " + currentText;
    }
    
    if (newRailStr === "레일: ") updatedText = updatedText.replace("레일: ", "").replace(" / ", "").trim();

    if (currentText !== updatedText) {
        inp.value = updatedText;
        if(typeof saveSiteInfo === 'function') saveSiteInfo(true); 
    }
}

// [view_calc.js 또는 관련 스크립트] 
function updatePaymentLiveUI(finalTotal, deposit) {
    // 최종 금액에서 선입금을 뺀 잔액 계산
    const balance = finalTotal - deposit;
    
    // UI 업데이트
    const dispFinal = document.getElementById('dispFinal');
    if (dispFinal) {
        dispFinal.innerText = formatComma(balance) + "원";
    }
}
