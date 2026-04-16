window.isMobileInlineSelectMode = window.isMobileInlineSelectMode || function() {
    try {
        if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) return true;
    } catch (e) {}
    return window.innerWidth <= 768;
};

window.closeMobileInlineSelect = window.closeMobileInlineSelect || function() {
    if (window.__mobileInlineSelectResizeHandler) {
        window.removeEventListener('resize', window.__mobileInlineSelectResizeHandler);
        window.__mobileInlineSelectResizeHandler = null;
    }
    var panel = document.getElementById('mobileInlineSelectPanel');
    var scrim = document.getElementById('mobileInlineSelectScrim');
    if (panel) panel.remove();
    if (scrim) scrim.remove();
    window.__mobileInlineSelectAnchor = null;
    window.__mobileInlineSelectTarget = null;
};

window.positionMobileInlineSelect = window.positionMobileInlineSelect || function(anchorEl, panel) {
    if (!anchorEl || !panel) return;
    var rect = anchorEl.getBoundingClientRect();
    var width = Math.max(rect.width, 220);
    width = Math.min(width, window.innerWidth - 16);
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    var top = rect.bottom + 6;
    var maxTop = window.innerHeight - panel.offsetHeight - 8;
    if (top > maxTop) {
        top = Math.max(8, rect.top - panel.offsetHeight - 6);
    }
    panel.style.width = width + 'px';
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
};

window.openMobileInlineSelect = window.openMobileInlineSelect || function(selectEl, options) {
    if (!selectEl) return false;
    if (!window.isMobileInlineSelectMode()) return false;
    if (window.__mobileInlineSelectIgnoreUntil && Date.now() < window.__mobileInlineSelectIgnoreUntil) return true;

    var opts = options || {};
    var anchorEl = opts.anchor || selectEl;
    var optionList = Array.from(selectEl.options || []).filter(function(opt) {
        return !opt.disabled && String(opt.text || '').trim() !== '';
    });
    if (!optionList.length) return false;

    window.closeMobileInlineSelect();

    var scrim = document.createElement('button');
    scrim.type = 'button';
    scrim.id = 'mobileInlineSelectScrim';
    scrim.className = 'mobile-inline-select__scrim';
    scrim.setAttribute('aria-label', '닫기');
    scrim.onclick = function() {
        if (window.__mobileInlineSelectIgnoreUntil && Date.now() < window.__mobileInlineSelectIgnoreUntil) return;
        window.closeMobileInlineSelect();
    };
    document.body.appendChild(scrim);

    var panel = document.createElement('div');
    panel.id = 'mobileInlineSelectPanel';
    panel.className = 'mobile-inline-select';
    panel.innerHTML = optionList.map(function(opt) {
        var selected = String(opt.value) === String(selectEl.value) ? ' is-selected' : '';
        return '<button type="button" class="mobile-inline-select__item' + selected + '" data-value="' + String(opt.value).replace(/"/g, '&quot;') + '">' + String(opt.text) + '</button>';
    }).join('');
    panel.addEventListener('click', function(event) {
        var btn = event.target.closest('.mobile-inline-select__item');
        if (!btn) return;
        var nextValue = btn.getAttribute('data-value');
        if (String(selectEl.value) !== String(nextValue)) {
            selectEl.value = nextValue;
            selectEl.dispatchEvent(new Event('change', { bubbles: true }));
            selectEl.dispatchEvent(new Event('input', { bubbles: true }));
        }
        window.closeMobileInlineSelect();
    });
    document.body.appendChild(panel);
    window.__mobileInlineSelectIgnoreUntil = Date.now() + 360;

    window.__mobileInlineSelectAnchor = anchorEl;
    window.__mobileInlineSelectTarget = selectEl;
    window.__mobileInlineSelectResizeHandler = function() {
        var currentPanel = document.getElementById('mobileInlineSelectPanel');
        if (!currentPanel || !window.__mobileInlineSelectAnchor) return;
        window.positionMobileInlineSelect(window.__mobileInlineSelectAnchor, currentPanel);
    };
    window.addEventListener('resize', window.__mobileInlineSelectResizeHandler);
    window.positionMobileInlineSelect(anchorEl, panel);
    return true;
};

window.handleMobileInlineSelectTrigger = window.handleMobileInlineSelectTrigger || function(event) {
    var selectEl = event.target.closest('select');
    if (!selectEl) return false;
    if (!window.isMobileInlineSelectMode()) return false;
    if (selectEl.classList.contains('hidden-picker-select')) return false;
    if (selectEl.dataset.nativeSelect === 'true') return false;
    if (selectEl.multiple) return false;
    if (selectEl.disabled) return false;
    if (window.__mobileInlineSelectTarget === selectEl && document.getElementById('mobileInlineSelectPanel')) {
        if (event.cancelable) event.preventDefault();
        event.stopPropagation();
        return true;
    }
    if (window.__mobileInlineSelectIgnoreUntil && Date.now() < window.__mobileInlineSelectIgnoreUntil) {
        if (event.cancelable) event.preventDefault();
        event.stopPropagation();
        return true;
    }
    if (event.cancelable) event.preventDefault();
    event.stopPropagation();
    window.openMobileInlineSelect(selectEl);
    return true;
};

document.addEventListener('pointerdown', function(event) {
    window.handleMobileInlineSelectTrigger(event);
}, true);

document.addEventListener('touchstart', function(event) {
    window.handleMobileInlineSelectTrigger(event);
}, true);

document.addEventListener('click', function(event) {
    window.handleMobileInlineSelectTrigger(event);
}, true);

window.__mobileInlineSelectGlobalBound = true;
