
(function(){
  if (window.__voiceCoreInitialized_v5) return;
  window.__voiceCoreInitialized_v5 = true;

  const DIRECT_STATE = {
    enabled: false,
    running: false,
    activeTarget: null,
    recognition: null,
    config: {},
    lastTriggeredAt: 0,
    lastTarget: null
  };

  const DIRECT_VOICE_STORAGE_KEY = 'direct_voice_enabled_v1';
  const PRODUCT_WORDS = Array.from(new Set([
    '차르르','암막커튼','쉬폰','블라인드','롤스크린','허니콤','커튼','콤비블라인드','암막블라인드','암막허니콤',
    ...(Array.isArray(window.ITEM_CATEGORIES) ? window.ITEM_CATEGORIES : [])
  ]));

  const DIGIT_WORDS = {
    '영':'0','공':'0',
    '일':'1','하나':'1','한':'1',
    '이':'2','둘':'2','두':'2',
    '삼':'3','셋':'3','세':'3',
    '사':'4','넷':'4','네':'4',
    '오':'5',
    '육':'6','륙':'6',
    '칠':'7',
    '팔':'8',
    '구':'9'
  };
  const SMALL_UNITS = {'십':10,'백':100,'천':1000};
  const LARGE_UNITS = {'만':10000,'억':100000000};

  function showToast(message){
    document.querySelectorAll('.voice-toast').forEach(x => x.remove());
    const el = document.createElement('div');
    el.className = 'voice-toast';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1800);
  }

  function normalizeSpeechText(raw){
    let t = String(raw || '').trim();
    t = t.replace(/\s+/g, ' ');
    t = t.replace(/온/g, '원');
    t = t.replace(/쩜/g, '점');
    t = t.replace(/스무/g, '이십')
         .replace(/서른/g, '삼십')
         .replace(/마흔/g, '사십')
         .replace(/쉰/g, '오십')
         .replace(/예순/g, '육십')
         .replace(/일흔/g, '칠십')
         .replace(/여든/g, '팔십')
         .replace(/아흔/g, '구십');
    return t;
  }

  function currentPageContext(){
    const path = (window.location.pathname || '').toLowerCase();
    if (path.includes('/view')) return 'view';
    if (path.includes('/dashboard')) return 'dashboard';
    if (path.includes('/ledger')) return 'ledger';
    return 'unsupported';
  }

  function buildContext(pageContext){
    const ctx = { pageContext: pageContext };
    try {
      if (pageContext === 'view') {
        const orderIdEl = document.querySelector('[data-order-id]') || document.getElementById('srv-order-id') || document.getElementById('OrderID') || document.getElementById('orderId');
        if (orderIdEl) ctx.orderId = orderIdEl.dataset.orderId || orderIdEl.value || null;
      } else if (pageContext === 'ledger') {
        const suppliers = Array.from(document.querySelectorAll('#inputSupplier option'))
          .map(o => String(o.textContent || '').trim())
          .filter(Boolean)
          .slice(0, 20);
        const categories = (Array.isArray(window.expenseCategories) ? window.expenseCategories : [])
          .map(x => (x && (x.id || x.CategoryName)) ? String(x.id || x.CategoryName).trim() : '')
          .filter(Boolean)
          .slice(0, 20);
        if (suppliers.length) ctx.recentSuppliers = suppliers;
        if (categories.length) ctx.recentCategories = categories;
      } else if (pageContext === 'dashboard') {
        const siteNames = Array.from(document.querySelectorAll('.task-address, .addr, .address, .customer-address'))
          .map(el => String(el.textContent || '').trim())
          .filter(Boolean)
          .slice(0, 20);
        if (siteNames.length) ctx.recentSiteNames = siteNames;
        ctx.recentProducts = PRODUCT_WORDS.slice(0, 20);
      }
    } catch(e){}
    return ctx;
  }

  async function apiCreateDraft(pageContext, rawText, context){
    const res = await fetch('/api/voice/draft', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ pageContext, rawText, context })
    });
    if (!res.ok) {
      const txt = await res.text().catch(()=>'');
      throw new Error(txt || ('HTTP ' + res.status));
    }
    return res.json();
  }

  async function apiTranscribeAudio(blob, filename='voice.webm'){
    const form = new FormData();
    form.append('audio', blob, filename);
    form.append('language', 'ko');
    const res = await fetch('/api/voice/stt', { method:'POST', body: form });
    if (!res.ok) {
      const txt = await res.text().catch(()=>'');
      throw new Error(txt || ('HTTP ' + res.status));
    }
    return res.json();
  }

  async function captureVoiceByServerStt(options={}){
    const maxMs = Number(options.maxMs || 6000);
    const startMessage = options.startMessage || '음성 듣는 중…';
    const endMessage = options.endMessage || '음성 인식 중…';
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
      return null;
    }

    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      const recorder = new MediaRecorder(stream);

      const stopped = new Promise((resolve, reject) => {
        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) chunks.push(e.data);
        };
        recorder.onerror = (e) => reject(e?.error || new Error('recorder_error'));
        recorder.onstop = () => resolve();
      });

      showToast(startMessage);
      recorder.start();
      setTimeout(() => {
        try { if (recorder.state !== 'inactive') recorder.stop(); } catch(_) {}
      }, maxMs);

      await stopped;
      if (!chunks.length) return null;
      showToast(endMessage);
      const mime = recorder.mimeType || 'audio/webm';
      const ext = mime.includes('ogg') ? 'ogg' : 'webm';
      const blob = new Blob(chunks, { type: mime });
      const result = await apiTranscribeAudio(blob, `voice.${ext}`);
      return String(result?.text || '').trim() || null;
    } catch(_) {
      return null;
    } finally {
      if (stream) {
        try { stream.getTracks().forEach(t => t.stop()); } catch(_) {}
      }
    }
  }

  function tokenizeNumberText(text){
    const src = normalizeSpeechText(text).replace(/\s+/g,'');
    const tokens = [];
    let i = 0;
    while (i < src.length) {
      const rest = src.slice(i);
      const multi = ['하나','둘','셋','넷'].find(w => rest.startsWith(w));
      if (multi) {
        tokens.push(multi);
        i += multi.length;
        continue;
      }
      const ch = src[i];
      if (/[\d,]/.test(ch)) {
        let j = i;
        while (j < src.length && /[\d,]/.test(src[j])) j++;
        tokens.push(src.slice(i, j).replace(/,/g,''));
        i = j;
        continue;
      }
      tokens.push(ch);
      i++;
    }
    return tokens;
  }

  function parseKoreanInteger(text){
    const tokens = tokenizeNumberText(text);
    let total = 0, section = 0, number = 0;
    for (const tok of tokens) {
      if (/^\d+$/.test(tok)) {
        number = parseInt(tok, 10);
        continue;
      }
      if (DIGIT_WORDS[tok] !== undefined) {
        number = parseInt(DIGIT_WORDS[tok], 10);
        continue;
      }
      if (SMALL_UNITS[tok]) {
        if (number === 0) number = 1;
        section += number * SMALL_UNITS[tok];
        number = 0;
        continue;
      }
      if (LARGE_UNITS[tok]) {
        if (section === 0 && number === 0) section = 1;
        else section += number;
        total += section * LARGE_UNITS[tok];
        section = 0;
        number = 0;
      }
    }
    return total + section + number;
  }

  function fractionDigitsFromKorean(text){
    const src = normalizeSpeechText(text).replace(/\s+/g,'');
    let out = '';
    let i = 0;
    while (i < src.length) {
      const rest = src.slice(i);
      const multi = ['하나','둘','셋','넷'].find(w => rest.startsWith(w));
      if (multi) {
        out += DIGIT_WORDS[multi];
        i += multi.length;
        continue;
      }
      const ch = src[i];
      if (/\d/.test(ch)) {
        out += ch;
        i++;
        continue;
      }
      if (DIGIT_WORDS[ch] !== undefined) out += DIGIT_WORDS[ch];
      i++;
    }
    return out;
  }

  function parseGenericNumber(raw){
    const text = normalizeSpeechText(raw).replace(/,/g,'').trim();
    if (!text) return null;

    if (/^-?\d+(\.\d+)?$/.test(text)) return parseFloat(text);

    if (/[만억천백십]/.test(text) || /[영공일이삼사오육륙칠팔구하나둘셋넷]/.test(text)) {
      const parts = text.split('점');
      const intPart = parseKoreanInteger(parts[0]);
      if (parts.length > 1) {
        const frac = fractionDigitsFromKorean(parts[1]);
        if (frac) return parseFloat(String(intPart) + '.' + frac);
      }
      return intPart;
    }

    const simple = text.match(/-?\d+(?:\.\d+)?/);
    if (simple) return parseFloat(simple[0]);

    return null;
  }

  function parseSpokenAmount(raw){
    if (!raw) return null;
    const text = normalizeSpeechText(raw);
    const direct = text.match(/(\d[\d,]*(?:\.\d+)?)\s*원?/);
    if (direct && !/[만억천백십]/.test(text)) {
      const n = parseFloat(direct[1].replace(/,/g,''));
      return Number.isFinite(n) ? Math.round(n) : null;
    }
    const amountExpr = text.replace(/원/g, '').trim();
    const n = parseGenericNumber(amountExpr);
    return Number.isFinite(n) ? Math.round(n) : null;
  }

  function weekdayIndex(name){
    const map = {'일':0,'월':1,'화':2,'수':3,'목':4,'금':5,'토':6};
    return map[name] ?? null;
  }

  function nextWeekday(baseDate, targetDay, forceNextWeek){
    const d = new Date(baseDate);
    const cur = d.getDay();
    let diff = targetDay - cur;
    if (diff <= 0) diff += 7;
    if (forceNextWeek) diff += 7;
    d.setDate(d.getDate() + diff);
    return d;
  }

  function parseDateText(raw, mode){
    const text = normalizeSpeechText(raw);
    if (!text) return null;
    let d = new Date();
    d.setSeconds(0,0);

    let m = text.match(/(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일/);
    if (m) {
      const year = m[1] ? parseInt(m[1],10) : d.getFullYear();
      d = new Date(year, parseInt(m[2],10)-1, parseInt(m[3],10));
    } else if (/모레/.test(text)) {
      d.setDate(d.getDate() + 2);
    } else if (/내일/.test(text)) {
      d.setDate(d.getDate() + 1);
    } else if (/오늘/.test(text)) {
      d.setDate(d.getDate());
    } else {
      const w = text.match(/(다음주\s*)?([일월화수목금토])요일/);
      if (w) {
        const idx = weekdayIndex(w[2]);
        if (idx !== null) d = nextWeekday(new Date(), idx, !!w[1]);
      }
    }

    let hm = text.match(/(오전|오후)?\s*(\d{1,2})시(?:\s*반|\s*(\d{1,2})분)?/);
    if (hm) {
      let hour = parseInt(hm[2],10);
      let minute = hm[0].includes('반') ? 30 : (hm[3] ? parseInt(hm[3],10) : 0);
      if (hm[1] === '오후' && hour < 12) hour += 12;
      if (hm[1] === '오전' && hour === 12) hour = 0;
      d.setHours(hour, minute, 0, 0);
    } else if (mode === 'datetime-local') {
      d.setHours(9, 0, 0, 0);
    }

    const yyyy = d.getFullYear();
    const mm = String(d.getMonth()+1).padStart(2,'0');
    const dd = String(d.getDate()).padStart(2,'0');
    const hh = String(d.getHours()).padStart(2,'0');
    const mi = String(d.getMinutes()).padStart(2,'0');

    return mode === 'datetime-local'
      ? `${yyyy}-${mm}-${dd}T${hh}:${mi}`
      : `${yyyy}-${mm}-${dd}`;
  }

  function normalizeProductText(raw){
    const text = normalizeSpeechText(raw).trim();
    if (/^콤비\s*블라인드$/i.test(text)) return '콤비블라인드';
    if (/^암막\s*커튼$/i.test(text)) return '암막커튼';
    if (/^우드\s*블라인드$/i.test(text)) return '우드블라인드';
    if (/^롤\s*스크린$/i.test(text)) return '롤스크린';
    if (/^허니\s*콤$/i.test(text) || /^허니콤$/i.test(text)) return '허니콤';
    if (/^암막블라인드$/i.test(text)) return '암막블라인드';
    if (/^암막허니콤$/i.test(text)) return '암막허니콤';
    if (/^차르르$/i.test(text)) return '차르르';
    if (/^쉬폰$/i.test(text)) return '쉬폰';
    if (/^블라인드$/i.test(text)) return '블라인드';
    if (/^커튼$/i.test(text)) return '커튼';
    return text;
  }

  function detectFieldRole(target){
    const explicit = target.getAttribute && target.getAttribute('data-direct-voice-role');
    if (explicit) return explicit;

    const meta = [target.id, target.name, target.placeholder, target.className].filter(Boolean).join(' ').toLowerCase();

    let labelText = '';
    try {
      if (target.id) {
        const label = document.querySelector(`label[for="${target.id}"]`);
        if (label) labelText = label.textContent.toLowerCase();
      }
      if (!labelText) {
        const wrap = target.closest('.field, .form-group, .mb-3, .mb-2, td, th, tr, .row, .col, .input-group');
        if (wrap) labelText = wrap.textContent.slice(0, 120).toLowerCase();
      }
    } catch(e){}
    const text = (meta + ' ' + labelText).trim();

    if (target.type === 'datetime-local') return 'datetime';
    if (target.type === 'date') return 'date';
    if (/amount|price|cost|unitprice|sellingprice|displayamount|realamount|금액|원가|단가|매입|판매가|마진/.test(text)) return 'amount';
    if (target.type === 'number' || /qty|quantity|width|height|w\b|h\b|size|cm|mm|수량|폭|너비|높이|가로|세로|사이즈/.test(text)) return 'number';
    if (/product|prod|cate1|품목|제품/.test(text)) return 'product';
    if (/memo|note|record|remark|기록|메모|참고/.test(text)) return 'memo';

    return 'generic';
  }

  function normalizeByField(target, transcript){
    const role = detectFieldRole(target);
    const raw = normalizeSpeechText(transcript);
    if (!raw) return '';

    if (role === 'amount') {
      const n = parseSpokenAmount(raw);
      if (n !== null && !Number.isNaN(n)) {
        if (target.type === 'number') return String(n);
        return n.toLocaleString('ko-KR');
      }
      return raw;
    }

    if (role === 'number') {
      const n = parseGenericNumber(raw);
      if (n !== null && !Number.isNaN(n)) return String(n);
      return raw;
    }

    if (role === 'date') {
      return parseDateText(raw, 'date') || raw;
    }

    if (role === 'datetime') {
      return parseDateText(raw, 'datetime-local') || raw;
    }

    if (role === 'product') {
      return normalizeProductText(raw);
    }

    return raw;
  }

  function setValueByRole(target, value){
    const role = detectFieldRole(target);
    if (!target) return;

    if (target.isContentEditable) {
      target.focus();
      document.execCommand('insertText', false, value);
      return;
    }

    if (role === 'memo') {
      const start = typeof target.selectionStart === 'number' ? target.selectionStart : target.value.length;
      const end = typeof target.selectionEnd === 'number' ? target.selectionEnd : target.value.length;
      const before = target.value.slice(0, start);
      const after = target.value.slice(end);
      const spacer = before && !before.endsWith(' ') ? ' ' : '';
      target.value = before + spacer + value + after;
    } else {
      target.value = value;
    }

    if (role === 'amount') {
      const hidden = document.getElementById('realAmount');
      const n = parseSpokenAmount(value);
      if (hidden && n !== null) hidden.value = String(n);
    }

    if (target.dataset && target.dataset.dvReadonlyApplied === '1') {
      target.removeAttribute('readonly');
      target.removeAttribute('inputmode');
      delete target.dataset.dvReadonlyApplied;
    }

    target.dispatchEvent(new Event('input', { bubbles: true }));
    target.dispatchEvent(new Event('change', { bubbles: true }));
    target.focus();
  }

  function isEditableTarget(el){
    if (!el) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName === 'INPUT') {
      const t = (el.type || 'text').toLowerCase();
      return ['text','search','url','tel','email','number','date','datetime-local',''].includes(t);
    }
    return false;
  }

  function suppressKeyboard(target){
    if (!target || target.isContentEditable) return;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
      if (!target.hasAttribute('readonly')) {
        target.dataset.dvReadonlyApplied = '1';
        target.setAttribute('readonly', 'readonly');
        target.setAttribute('inputmode', 'none');
      }
    }
  }

  async function beginDirectVoiceFor(target){
    if (!DIRECT_STATE.enabled || DIRECT_STATE.running || !isEditableTarget(target)) return;

    const now = Date.now();
    if (DIRECT_STATE.lastTarget === target && now - DIRECT_STATE.lastTriggeredAt < 500) return;
    DIRECT_STATE.lastTarget = target;
    DIRECT_STATE.lastTriggeredAt = now;

    DIRECT_STATE.activeTarget = target;
    suppressKeyboard(target);

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SR) {
      const sttText = await captureVoiceByServerStt({
        maxMs: 5000,
        startMessage: '직접 음성 듣는 중…',
        endMessage: '직접 음성 인식 중…'
      });
      const fallbackText = sttText || prompt('직접 음성입력(임시): 입력할 내용을 텍스트로 적어주세요.');
      if (fallbackText && fallbackText.trim()) {
        const normalized = normalizeByField(target, fallbackText.trim());
        setValueByRole(target, normalized);
      } else if (target.dataset && target.dataset.dvReadonlyApplied === '1') {
        target.removeAttribute('readonly');
        target.removeAttribute('inputmode');
        delete target.dataset.dvReadonlyApplied;
      }
      return;
    }

    try {
      const recognition = new SR();
      DIRECT_STATE.recognition = recognition;
      DIRECT_STATE.running = true;
      recognition.lang = 'ko-KR';
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;

      showToast('말씀하세요…');
      recognition.onresult = (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript || '';
        if (transcript.trim()) {
          const normalized = normalizeByField(target, transcript.trim());
          setValueByRole(target, normalized);
        }
      };
      recognition.onerror = () => {
        showToast('음성 입력을 다시 시도해 주세요.');
        if (target.dataset && target.dataset.dvReadonlyApplied === '1') {
          target.removeAttribute('readonly');
          target.removeAttribute('inputmode');
          delete target.dataset.dvReadonlyApplied;
        }
      };
      recognition.onend = () => {
        DIRECT_STATE.running = false;
        DIRECT_STATE.recognition = null;
        if (target.dataset && target.dataset.dvReadonlyApplied === '1') {
          target.removeAttribute('readonly');
          target.removeAttribute('inputmode');
          delete target.dataset.dvReadonlyApplied;
        }
      };
      recognition.start();
    } catch(e) {
      DIRECT_STATE.running = false;
      DIRECT_STATE.recognition = null;
      const sttText = await captureVoiceByServerStt({
        maxMs: 5000,
        startMessage: '직접 음성 듣는 중…',
        endMessage: '직접 음성 인식 중…'
      });
      const fallbackText = sttText || prompt('직접 음성입력(임시): 입력할 내용을 텍스트로 적어주세요.');
      if (fallbackText && fallbackText.trim()) {
        const normalized = normalizeByField(target, fallbackText.trim());
        setValueByRole(target, normalized);
      } else if (target.dataset && target.dataset.dvReadonlyApplied === '1') {
        target.removeAttribute('readonly');
        target.removeAttribute('inputmode');
        delete target.dataset.dvReadonlyApplied;
      }
    }
  }

  function persistDirectState(){
    localStorage.setItem(DIRECT_VOICE_STORAGE_KEY, DIRECT_STATE.enabled ? '1' : '0');
  }

  function applyDirectStateToFields(){
    if (!DIRECT_STATE.enabled) return;
    document.querySelectorAll('input, textarea').forEach(el => {
      if (!isEditableTarget(el)) return;
      suppressKeyboard(el);
    });
  }

  function clearDirectStateFromFields(){
    document.querySelectorAll('[data-dv-readonly-applied="1"]').forEach(el => {
      el.removeAttribute('readonly');
      el.removeAttribute('inputmode');
      delete el.dataset.dvReadonlyApplied;
    });
  }

  function toggleDirectVoice(btn, forceValue){
    DIRECT_STATE.enabled = typeof forceValue === 'boolean' ? forceValue : !DIRECT_STATE.enabled;
    if (btn) btn.classList.toggle('is-on', DIRECT_STATE.enabled);
    persistDirectState();

    if (DIRECT_STATE.enabled) {
      applyDirectStateToFields();
      showToast('입력창 직접 음성입력 켜짐');
    } else {
      if (DIRECT_STATE.recognition) {
        try { DIRECT_STATE.recognition.stop(); } catch(e){}
      }
      clearDirectStateFromFields();
      showToast('입력창 직접 음성입력 꺼짐');
    }
  }

  async function createDraft(pageContext, text, context={}){
    try { return await apiCreateDraft(pageContext, text, context); }
    catch(e){ return { ok:true, draftId:'local-'+Date.now(), draft:{ pageContext, rawText:text, context, confidence:0.7, proposals:{} }, __local:true }; }
  }

  async function apiApplyDraft(payload){
    const res = await fetch('/api/voice/apply', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify(payload || {})
    });
    const raw = await res.text().catch(()=>'');
    let data = null;
    try { data = raw ? JSON.parse(raw) : null; } catch(_){}
    if (!res.ok) {
      const msg = (data && (data.detail || data.msg || data.message)) || raw || ('HTTP ' + res.status);
      throw new Error(msg);
    }
    return data || {};
  }

  async function apiDiscardDraft(draftId){
    const res = await fetch('/api/voice/discard', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ draftId })
    });
    if (!res.ok) throw new Error('draft_discard_failed');
    return res.json().catch(()=>({ok:true}));
  }

  const VOICE_REVIEW_STATE = { result: null, draft: null };
  const VOICE_REVIEW_IDS = {
    overlay: 'voiceCoreDraftOverlay',
    panel: 'voiceCoreDraftPanel',
    body: 'voiceCoreDraftBody',
    raw: 'voiceCoreRawText',
    meta: 'voiceCoreMeta',
    applyBtn: 'voiceCoreApplyBtn',
    memoBtn: 'voiceCoreMemoBtn',
    discardBtn: 'voiceCoreDiscardBtn'
  };

  function __escapeHtml(value){
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function ensureVoiceReviewPanel(){
    if (document.getElementById(VOICE_REVIEW_IDS.overlay)) return;

    const style = document.createElement('style');
    style.textContent = `
      #${VOICE_REVIEW_IDS.overlay}{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:100040;display:none}
      #${VOICE_REVIEW_IDS.overlay}.open{display:block}
      #${VOICE_REVIEW_IDS.panel}{position:fixed;right:16px;bottom:16px;width:min(480px,calc(100vw - 24px));max-height:85vh;overflow:auto;background:#fff;border-radius:14px;border:1px solid #dee2e6;z-index:100041;display:none;box-shadow:0 16px 40px rgba(0,0,0,.22)}
      #${VOICE_REVIEW_IDS.panel}.open{display:block}
      .vc-head{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #edf2f7;font-weight:800}
      .vc-body{padding:12px 14px}
      .vc-meta{font-size:12px;color:#5c6773;margin:6px 0 10px}
      .vc-raw{font-size:13px;background:#f8f9fa;border:1px solid #e9ecef;border-radius:8px;padding:8px 10px;white-space:pre-wrap}
      .vc-sec{margin-top:10px}
      .vc-sec h4{font-size:13px;margin:0 0 6px}
      .vc-card{display:flex;gap:8px;align-items:flex-start;border:1px solid #edf2f7;border-radius:8px;padding:8px 9px;margin-bottom:6px}
      .vc-card small{display:block;color:#6b7280;margin-top:2px}
      .vc-foot{position:sticky;bottom:0;background:#fff;border-top:1px solid #edf2f7;padding:10px;display:flex;gap:8px}
      .vc-btn{border:none;border-radius:8px;padding:9px 10px;font-weight:700;cursor:pointer}
      .vc-btn.apply{background:#2563eb;color:#fff;flex:1}
      .vc-btn.memo{background:#e5edff;color:#1e40af}
      .vc-btn.discard{background:#f3f4f6;color:#374151}
      .vc-close{border:none;background:transparent;font-size:20px;line-height:1;cursor:pointer;color:#6b7280}
      @media (max-width:768px){#${VOICE_REVIEW_IDS.panel}{right:8px;left:8px;bottom:8px;width:auto;max-height:88vh}}
    `;
    document.head.appendChild(style);

    const overlay = document.createElement('div');
    overlay.id = VOICE_REVIEW_IDS.overlay;
    overlay.addEventListener('click', closeVoiceReviewPanel);
    document.body.appendChild(overlay);

    const panel = document.createElement('div');
    panel.id = VOICE_REVIEW_IDS.panel;
    panel.innerHTML = `
      <div class="vc-head">
        <span>자비스 음성 초안</span>
        <button type="button" class="vc-close" id="voiceCoreCloseBtn" aria-label="닫기">&times;</button>
      </div>
      <div class="vc-body">
        <div id="${VOICE_REVIEW_IDS.meta}" class="vc-meta"></div>
        <div id="${VOICE_REVIEW_IDS.raw}" class="vc-raw"></div>
        <div id="${VOICE_REVIEW_IDS.body}"></div>
      </div>
      <div class="vc-foot">
        <button type="button" id="${VOICE_REVIEW_IDS.applyBtn}" class="vc-btn apply">선택 반영</button>
        <button type="button" id="${VOICE_REVIEW_IDS.memoBtn}" class="vc-btn memo">원문메모</button>
        <button type="button" id="${VOICE_REVIEW_IDS.discardBtn}" class="vc-btn discard">폐기</button>
      </div>
    `;
    document.body.appendChild(panel);

    document.getElementById('voiceCoreCloseBtn')?.addEventListener('click', closeVoiceReviewPanel);
    document.getElementById(VOICE_REVIEW_IDS.applyBtn)?.addEventListener('click', applyVoiceReviewSelection);
    document.getElementById(VOICE_REVIEW_IDS.memoBtn)?.addEventListener('click', applyVoiceReviewMemoOnly);
    document.getElementById(VOICE_REVIEW_IDS.discardBtn)?.addEventListener('click', discardVoiceReviewDraft);
  }

  function openVoiceReviewPanel(){
    ensureVoiceReviewPanel();
    document.getElementById(VOICE_REVIEW_IDS.overlay)?.classList.add('open');
    document.getElementById(VOICE_REVIEW_IDS.panel)?.classList.add('open');
  }

  function closeVoiceReviewPanel(){
    document.getElementById(VOICE_REVIEW_IDS.overlay)?.classList.remove('open');
    document.getElementById(VOICE_REVIEW_IDS.panel)?.classList.remove('open');
  }

  function renderVoiceProposalCards(draft){
    const body = document.getElementById(VOICE_REVIEW_IDS.body);
    if (!body) return;
    const p = (draft && draft.proposals) || {};
    const page = draft?.pageContext || currentPageContext();
    const blocks = [];

    if (Array.isArray(p.scheduleUpdates) && p.scheduleUpdates.length) {
      const html = p.scheduleUpdates.map((row, idx) => `
        <label class="vc-card">
          <input type="checkbox" data-vc-type="scheduleUpdates" data-vc-idx="${idx}" checked>
          <div><strong>일정 변경</strong><small>${__escapeHtml(row.proposedValue || '-')}</small></div>
        </label>
      `).join('');
      blocks.push(`<section class="vc-sec"><h4>일정 제안</h4>${html}</section>`);
    }

    if (Array.isArray(p.itemAdds) && p.itemAdds.length) {
      const html = p.itemAdds.map((row, idx) => `
        <label class="vc-card">
          <input type="checkbox" data-vc-type="itemAdds" data-vc-idx="${idx}" checked>
          <div><strong>품목 추가</strong><small>${__escapeHtml((row.location ? row.location + ' / ' : '') + (row.product || '-'))}</small></div>
        </label>
      `).join('');
      blocks.push(`<section class="vc-sec"><h4>품목 제안</h4>${html}</section>`);
    }

    if (p.expenseDraft && page === 'ledger') {
      const e = p.expenseDraft;
      blocks.push(`
        <section class="vc-sec">
          <h4>지출 저장 제안</h4>
          <label class="vc-card">
            <input type="checkbox" data-vc-type="expenseDraft" checked>
            <div>
              <strong>${__escapeHtml((e.category || e.item || '기타'))} / ${(Number(e.amount || 0) || 0).toLocaleString()}원</strong>
              <small>${__escapeHtml(e.vendorCandidate || '')}${e.status ? ' | ' + __escapeHtml(e.status) : ''}${e.payerType ? ' | ' + __escapeHtml(e.payerType) : ''}</small>
            </div>
          </label>
        </section>
      `);
    }

    if (Array.isArray(p.memoAdds) && p.memoAdds.length) {
      const html = p.memoAdds.map((row, idx) => `
        <label class="vc-card">
          <input type="checkbox" data-vc-type="memoAdds" data-vc-idx="${idx}" checked>
          <div><strong>메모</strong><small>${__escapeHtml(row.text || '-')}</small></div>
        </label>
      `).join('');
      blocks.push(`<section class="vc-sec"><h4>메모 제안</h4>${html}</section>`);
    }

    body.innerHTML = blocks.length ? blocks.join('') : `<div class="vc-sec"><small>반영 가능한 제안을 찾지 못했습니다.</small></div>`;
  }

  function collectVoiceReviewSelections(){
    const sels = { scheduleUpdates: [], itemAdds: [], memoAdds: [], expenseDraft: false };
    document.querySelectorAll(`#${VOICE_REVIEW_IDS.panel} input[type="checkbox"][data-vc-type]`).forEach(chk => {
      if (!chk.checked) return;
      const t = chk.getAttribute('data-vc-type');
      if (t === 'expenseDraft') {
        sels.expenseDraft = true;
        return;
      }
      const idx = parseInt(chk.getAttribute('data-vc-idx'), 10);
      if (!Number.isNaN(idx) && Array.isArray(sels[t])) sels[t].push(idx);
    });
    return sels;
  }

  function renderVoiceDraftPanelFromCore(result){
    ensureVoiceReviewPanel();
    const draft = (result && (result.draft || result.DraftJSON || result)) || {};
    if (!draft.pageContext) draft.pageContext = currentPageContext();
    if (result && result.draftId && !draft.draftId) draft.draftId = result.draftId;
    if (result && result.DraftID && !draft.draftId) draft.draftId = result.DraftID;

    VOICE_REVIEW_STATE.result = result || null;
    VOICE_REVIEW_STATE.draft = draft;

    const intent = __escapeHtml(draft.intentType || '-');
    const action = __escapeHtml(draft.actionType || '-');
    const conf = Math.round((Number(draft.confidence || 0) || 0) * 100);
    const metaEl = document.getElementById(VOICE_REVIEW_IDS.meta);
    if (metaEl) metaEl.textContent = `의도 ${intent} · 액션 ${action} · 신뢰도 ${conf}%`;

    const rawEl = document.getElementById(VOICE_REVIEW_IDS.raw);
    if (rawEl) rawEl.textContent = String(draft.rawText || '').trim() || '-';

    const memoBtn = document.getElementById(VOICE_REVIEW_IDS.memoBtn);
    if (memoBtn) memoBtn.style.display = (draft.pageContext === 'view') ? '' : 'none';

    renderVoiceProposalCards(draft);
    openVoiceReviewPanel();
  }

  async function applyVoiceReviewSelection(){
    const draft = VOICE_REVIEW_STATE.draft;
    if (!draft) return;

    const sels = collectVoiceReviewSelections();
    const selectedCount = (sels.scheduleUpdates || []).length + (sels.itemAdds || []).length + (sels.memoAdds || []).length + (sels.expenseDraft ? 1 : 0);
    if (!selectedCount) {
      showToast('선택된 항목이 없습니다.');
      return;
    }

    if (!draft.draftId || String(draft.draftId).startsWith('local-')) {
      showToast('서버 초안이 없어 실제 저장을 진행할 수 없습니다.');
      return;
    }

    const applyBtn = document.getElementById(VOICE_REVIEW_IDS.applyBtn);
    if (applyBtn) applyBtn.disabled = true;
    try {
      const res = await apiApplyDraft({ draftId: draft.draftId, applySelections: sels });
      closeVoiceReviewPanel();
      showToast('음성 초안을 실제 데이터로 반영했습니다.');

      const entries = Array.isArray(res?.appliedEntries) ? res.appliedEntries : [];
      const page = draft.pageContext || currentPageContext();
      if (page === 'dashboard') {
        const lead = entries.find(x => x && x.targetType === 'new_order');
        if (lead && lead.targetId) {
          window.location.href = `/view/${lead.targetId}`;
          return;
        }
        window.location.reload();
        return;
      }
      if (page === 'ledger') {
        if (typeof window.refreshData === 'function') {
          await window.refreshData();
        } else {
          window.location.reload();
        }
        return;
      }
      if (page === 'view') {
        window.location.reload();
      }
    } catch (e) {
      console.error(e);
      showToast('음성 반영 중 오류가 발생했습니다.');
    } finally {
      if (applyBtn) applyBtn.disabled = false;
    }
  }

  async function applyVoiceReviewMemoOnly(){
    const draft = VOICE_REVIEW_STATE.draft;
    if (!draft || draft.pageContext !== 'view') return;
    if (!draft.draftId || String(draft.draftId).startsWith('local-')) {
      showToast('서버 초안이 없어 메모 저장을 진행할 수 없습니다.');
      return;
    }
    const btn = document.getElementById(VOICE_REVIEW_IDS.memoBtn);
    if (btn) btn.disabled = true;
    try {
      await apiApplyDraft({ draftId: draft.draftId, applySelections: { memoOnly: true } });
      closeVoiceReviewPanel();
      showToast('음성 원문을 메모로 저장했습니다.');
      window.location.reload();
    } catch (e) {
      console.error(e);
      showToast('메모 저장 중 오류가 발생했습니다.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function discardVoiceReviewDraft(){
    const draft = VOICE_REVIEW_STATE.draft;
    if (!draft) return;
    const btn = document.getElementById(VOICE_REVIEW_IDS.discardBtn);
    if (btn) btn.disabled = true;
    try {
      if (draft.draftId && !String(draft.draftId).startsWith('local-')) {
        await apiDiscardDraft(draft.draftId);
      }
      closeVoiceReviewPanel();
      showToast('음성 초안을 폐기했습니다.');
    } catch (e) {
      console.error(e);
      showToast('폐기 중 오류가 발생했습니다.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function promptAndOpenVoiceDraft(options={}){
    const page = options.pageContext || currentPageContext();
    if (page === 'unsupported') {
      alert('현재 페이지에서는 자비스 음성 기능을 사용할 수 없습니다.');
      return;
    }
    const sttText = await captureVoiceByServerStt({
      maxMs: Number(options.maxMs || 7000),
      startMessage: options.startMessage || '자비스 음성 듣는 중…',
      endMessage: options.endMessage || '자비스 음성 인식 중…'
    });
    const fallbackPrompt = options.promptText || '자비스 음성(임시): 말씀하신 내용을 텍스트로 입력해 주세요.';
    const text = sttText || prompt(fallbackPrompt);
    if (!text || !String(text).trim()) return;

    const context = Object.assign({}, buildContext(page), options.context || {});
    const result = await createDraft(page, String(text).trim(), context);
    renderVoiceDraftPanelFromCore(result);
    return result;
  }

  function initDirectVoiceHandlers(directBtn){
    document.addEventListener('pointerdown', function(e){
      if (!DIRECT_STATE.enabled) return;
      const target = e.target && e.target.closest ? e.target.closest('input, textarea, [contenteditable="true"]') : null;
      if (!isEditableTarget(target)) return;
      e.preventDefault();
      e.stopPropagation();
      if (document.activeElement && document.activeElement !== target) {
        try { document.activeElement.blur(); } catch(_){}
      }
      setTimeout(() => {
        try { target.focus({ preventScroll:true }); } catch(_) {}
        beginDirectVoiceFor(target);
      }, 20);
    }, true);

    document.addEventListener('focusin', function(e){
      if (!DIRECT_STATE.enabled) return;
      const target = e.target && e.target.closest ? e.target.closest('input, textarea, [contenteditable="true"]') : null;
      if (!isEditableTarget(target)) return;
      suppressKeyboard(target);
      setTimeout(() => beginDirectVoiceFor(target), 30);
    }, true);

    window.addEventListener('pageshow', function(){
      const persisted = localStorage.getItem(DIRECT_VOICE_STORAGE_KEY) === '1';
      DIRECT_STATE.enabled = persisted;
      if (directBtn) directBtn.classList.toggle('is-on', persisted);
      if (persisted) applyDirectStateToFields();
    });
  }

  window.voiceWidget = {
    init(config={}){
      DIRECT_STATE.config = config;
      const directBtn = document.getElementById(config.directBtnId || 'zoomDirectVoiceBtn');
      const jarvisBtn = document.getElementById(config.jarvisBtnId || 'jarvisVoiceBtn');

      const persisted = localStorage.getItem(DIRECT_VOICE_STORAGE_KEY) === '1';
      DIRECT_STATE.enabled = persisted;
      if (directBtn) directBtn.classList.toggle('is-on', persisted);

      if (directBtn) {
        directBtn.addEventListener('click', function(e){
          e.preventDefault();
          toggleDirectVoice(directBtn);
        });
      }

      initDirectVoiceHandlers(directBtn);
      if (persisted) applyDirectStateToFields();

      if (jarvisBtn) {
        const page = currentPageContext();
        if (page === 'unsupported') {
          jarvisBtn.classList.add('is-disabled');
          jarvisBtn.title = '현재 페이지에서는 자비스 음성 기능을 사용할 수 없습니다.';
        } else {
          jarvisBtn.classList.remove('is-disabled');
          jarvisBtn.title = '자비스 음성';
        }
        jarvisBtn.addEventListener('click', async function(e){
          e.preventDefault();
          await window.voiceWidget.handleClick();
        });
      }
    },

    async handleClick(){
      const page = currentPageContext();
      if (page === 'unsupported') {
        alert('현재 페이지에서는 자비스 음성 기능을 사용할 수 없습니다.');
        return;
      }
      const prompts = {
        dashboard: '예: 운정 푸르지오 103동 차르르 견적 문의, 토요일 오후 방문 가능',
        ledger: '예: 식대 12000원 / 금강상사 자재 8만5천원 외상 / 내 돈으로 주유 5만원',
        view: '예: 거실 블라인드 추가, 내일 오후 2시 방문으로 변경'
      };
      await promptAndOpenVoiceDraft({
        pageContext: page,
        promptText: prompts[page] || '자비스 음성 입력'
      });
    }
  };

  window.renderVoiceDraftPanelFromCore = renderVoiceDraftPanelFromCore;
  window.voiceSystem = {
    promptAndOpen: promptAndOpenVoiceDraft,
    renderVoiceDraftPanelFromCore
  };
})();
