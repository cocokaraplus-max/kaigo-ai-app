// translation-v1: 翻訳レンズ（長押し方式）
// テキストを長押し（600ms）すると母国語に翻訳してツールチップ表示
// クリック・ナビゲーションには一切干渉しない
(function () {
  'use strict';

  var tooltip = null;
  var highlightEl = null;
  var cache = {};
  var userLang = null;
  var pressTimer = null;
  var pressEl = null;
  var LONG_PRESS_MS = 600;

  var LANG_FLAGS = {
    'en':'🇺🇸','zh-CN':'🇨🇳','zh-TW':'🇹🇼','ko':'🇰🇷',
    'vi':'🇻🇳','tl':'🇵🇭','id':'🇮🇩','pt':'🇧🇷',
    'es':'🇪🇸','th':'🇹🇭','my':'🇲🇲'
  };

  // ===== 翻訳機能ON/OFF =====
  var TT_KEY = 'tt_enabled';
  function isTTEnabled() { return localStorage.getItem(TT_KEY) !== '0'; }

  window.ttSetEnabled = function (on) {
    localStorage.setItem(TT_KEY, on ? '1' : '0');
    var btn = document.getElementById('tt-lens-btn');
    if (!on) {
      hideTooltip();
      applySelectOff(false);
      if (btn) btn.style.display = 'none';
      document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.display = 'none'; });
    } else {
      applySelectOff(true);
      if (btn) btn.style.display = '';
      document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.display = ''; });
      updateBtn();
    }
  };

  // ===== 言語設定 =====
  async function loadUserLang() {
    var cached = localStorage.getItem('tt_ui_lang');
    if (cached) { userLang = cached; return cached; }
    try {
      var r = await fetch('/api/settings/ui_language');
      var d = await r.json();
      if (d.status === 'success' && d.language) {
        userLang = d.language;
        localStorage.setItem('tt_ui_lang', d.language);
        return d.language;
      }
    } catch (e) {}
    return null;
  }

  async function saveUserLang(lang) {
    userLang = lang;
    if (lang) localStorage.setItem('tt_ui_lang', lang);
    else localStorage.removeItem('tt_ui_lang');
    try {
      await fetch('/api/settings/ui_language', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({language: lang || ''})
      });
    } catch (e) {}
  }

  // ===== ボタン表示更新 =====
  function updateBtn() {
    var btn = document.getElementById('tt-lens-btn');
    if (!btn) return;
    btn.style.background = '';
    btn.style.color = '';
    if (userLang) {
      btn.innerHTML = '<span style="font-size:1.25rem;line-height:1;">' + (LANG_FLAGS[userLang] || '🌐') + '</span>';
    } else {
      btn.innerHTML = '<span class="material-symbols-outlined">translate</span>';
    }
  }

  // ===== テキスト取得 =====
  function getCleanText(el) {
    var clone = el.cloneNode(true);
    clone.querySelectorAll('.material-symbols-outlined,.material-icons,.dw-badge,.sm-rec-dot,[aria-hidden="true"]')
      .forEach(function (e) { e.remove(); });
    return (clone.innerText || clone.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function findTarget(target) {
    var el = target;
    for (var i = 0; i < 6; i++) {
      if (!el || el === document.body) break;
      var text = getCleanText(el);
      if (text && /[぀-ヿ一-鿿]/.test(text) && text.length <= 200) {
        return {el: el, text: text};
      }
      el = el.parentElement;
    }
    return null;
  }

  // ===== ツールチップ =====
  function showTooltip(el, html) {
    hideTooltip();
    if (highlightEl) highlightEl.classList.remove('tt-lens-highlight');
    el.classList.add('tt-lens-highlight');
    highlightEl = el;

    var t = document.createElement('div');
    t.id = 'tt-lens-tip';
    t.style.cssText = [
      'position:fixed;z-index:9900;',
      'background:#202124;color:#fff;border-radius:14px;',
      'padding:10px 14px;font-size:0.82rem;line-height:1.5;',
      'max-width:300px;max-height:45vh;overflow-y:auto;',
      'word-break:break-word;',
      'box-shadow:0 4px 20px rgba(0,0,0,0.4);',
    ].join('');
    t.innerHTML = html;
    document.body.appendChild(t);
    tooltip = t;

    var rect = el.getBoundingClientRect();
    var th = t.offsetHeight || 80;
    var tw = t.offsetWidth || 300;
    var spaceAbove = rect.top - 8;
    var spaceBelow = window.innerHeight - rect.bottom - 8;
    var top;
    if (spaceAbove >= th || spaceAbove >= spaceBelow) {
      top = Math.max(8, rect.top - th - 10);
    } else {
      top = Math.min(rect.bottom + 10, window.innerHeight - th - 8);
    }
    var left = rect.left + (rect.width - tw) / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
    t.style.top = top + 'px';
    t.style.left = left + 'px';

    // 外タップで閉じる（リスナーを一元管理して多重登録を防ぐ）
    setupDismiss();
  }

  var dismissHandler = null;
  function setupDismiss() {
    clearDismiss();
    dismissHandler = function (e) {
      if (tooltip && tooltip.contains(e.target)) return;
      clearDismiss();
      hideTooltip();
    };
    // 長押し終了後の touchend が先に来るので少し遅らせる
    setTimeout(function () {
      if (dismissHandler) {
        document.addEventListener('touchend', dismissHandler, {capture: true, passive: true});
      }
    }, 350);
  }

  function clearDismiss() {
    if (dismissHandler) {
      document.removeEventListener('touchend', dismissHandler, {capture: true});
      dismissHandler = null;
    }
  }

  function hideTooltip() {
    clearDismiss();
    if (tooltip) { tooltip.remove(); tooltip = null; }
    if (highlightEl) { highlightEl.classList.remove('tt-lens-highlight'); highlightEl = null; }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ===== 読み上げ =====
  function speak(text, lang) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    window.speechSynthesis.speak(u);
  }

  // ===== 翻訳 =====
  async function translate(el, text) {
    if (!userLang) return;
    var key = userLang + ':' + text;
    if (cache[key]) { showTooltip(el, tipHtml(text, cache[key])); return; }
    showTooltip(el, '<div style="opacity:0.6;font-size:0.78rem;">翻訳中...</div>');
    try {
      var r = await fetch('/api/translate/ui', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text, target_lang: userLang})
      });
      var d = await r.json();
      if (d.status === 'success') {
        cache[key] = d.translated;
        showTooltip(el, tipHtml(text, d.translated));
      } else { hideTooltip(); }
    } catch (e) { hideTooltip(); }
  }

  function tipHtml(orig, trans) {
    var flag = LANG_FLAGS[userLang] || '🌐';
    var lang = userLang || 'en';
    window._ttSpeak = function () { speak(trans, lang); };
    return '<div style="font-size:0.68rem;opacity:0.55;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.12);padding-bottom:6px;">' + esc(orig) + '</div>' +
           '<div style="display:flex;align-items:flex-start;gap:8px;">' +
             '<div style="flex:1;font-weight:700;font-size:0.9rem;">' + flag + ' ' + esc(trans) + '</div>' +
             '<button onclick="_ttSpeak()" style="flex-shrink:0;background:rgba(255,255,255,0.15);border:none;color:#fff;border-radius:8px;padding:4px 8px;font-size:0.8rem;cursor:pointer;white-space:nowrap;">🔊</button>' +
           '</div>';
  }

  // ===== 長押しハンドラ =====
  var startX = 0, startY = 0;

  document.addEventListener('touchstart', function (e) {
    if (!isTTEnabled() || !userLang) return;
    // 翻訳UI自体・ボタン類は除外
    if (e.target.closest('#tt-lang-picker-modal,#tt-lens-btn,.tt-panel,.tt-field-btn,#tt-lens-tip')) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    pressEl = e.target;
    pressTimer = setTimeout(function () {
      pressTimer = null;
      if (!pressEl) return;
      // iOSはnavigator.vibrate非対応 → パルスアニメーションで代替
      var found = findTarget(pressEl);
      if (found) {
        found.el.classList.add('tt-lens-pulse');
        setTimeout(function () { found.el.classList.remove('tt-lens-pulse'); }, 400);
        translate(found.el, found.text);
      }
    }, LONG_PRESS_MS);
  }, {passive: true});

  document.addEventListener('touchmove', function (e) {
    if (!pressTimer) return;
    var dx = e.touches[0].clientX - startX;
    var dy = e.touches[0].clientY - startY;
    // 10px以上動いたらキャンセル（スクロール中）
    if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
      clearTimeout(pressTimer);
      pressTimer = null;
      pressEl = null;
    }
  }, {passive: true});

  document.addEventListener('touchend', function () {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
    pressEl = null;
  }, {passive: true});

  document.addEventListener('touchcancel', function () {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
    pressEl = null;
  }, {passive: true});

  // ===== 言語ピッカー =====
  window.ttLensToggle = async function () {
    var lang = await loadUserLang();
    var modal = document.getElementById('tt-lang-picker-modal');
    var keepBtn = document.getElementById('tt-lens-keep-btn');
    if (keepBtn) keepBtn.style.display = lang ? '' : 'none';
    modal.classList.add('open');
  };

  window.ttLensPickLang = async function (lang) {
    await saveUserLang(lang);
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
    updateBtn();
  };

  window.ttLensKeepLang = function () {
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
  };

  window.ttLensClearLang = async function () {
    await saveUserLang('');
    updateBtn();
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
  };

  window.ttLensOpenPicker = function () {
    document.getElementById('tt-lang-picker-modal').classList.add('open');
  };

  // ===== CSS =====
  var s = document.createElement('style');
  s.textContent =
    '.tt-lens-highlight { outline:2.5px solid #1a73e8 !important; outline-offset:2px !important;' +
    '  background:rgba(26,115,232,0.10) !important; border-radius:4px !important; }' +
    '@keyframes tt-pulse { 0%{box-shadow:0 0 0 0 rgba(26,115,232,0.5)} 70%{box-shadow:0 0 0 12px rgba(26,115,232,0)} 100%{box-shadow:0 0 0 0 rgba(26,115,232,0)} }' +
    '.tt-lens-pulse { animation: tt-pulse 0.4s ease-out !important; border-radius:4px !important; }' +
    // 翻訳ON時：iOSネイティブ選択メニューを抑制（入力欄は除外）
    '.tt-select-off, .tt-select-off *:not(input):not(textarea):not([contenteditable]) {' +
    '  -webkit-user-select: none !important; user-select: none !important; }';
  document.head.appendChild(s);

  function applySelectOff(on) {
    document.body.classList.toggle('tt-select-off', on);
  }

  // ===== 初期化 =====
  document.addEventListener('DOMContentLoaded', async function () {
    var btn = document.getElementById('tt-lens-btn');
    if (!isTTEnabled()) {
      if (btn) btn.style.display = 'none';
      return;
    }
    applySelectOff(true);
    await loadUserLang();
    updateBtn();
  });
})();
