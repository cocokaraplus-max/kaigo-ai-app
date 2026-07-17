// translation-v1: 翻訳レンズ
// 🔍ボタンをタップ → レンズモードON → UI要素をタップ → 母国語に翻訳してツールチップ表示
(function () {
  'use strict';

  var lensActive = false;
  var tooltip = null;
  var cache = {};  // "lang:text" → translated string
  var userLang = null;

  var LANG_FLAGS = {
    'en':'🇺🇸','zh-CN':'🇨🇳','zh-TW':'🇹🇼','ko':'🇰🇷',
    'vi':'🇻🇳','tl':'🇵🇭','id':'🇮🇩','pt':'🇧🇷',
    'es':'🇪🇸','th':'🇹🇭','my':'🇲🇲'
  };
  var LANG_NAMES = {
    'en':'English','zh-CN':'中文(简体)','zh-TW':'中文(繁體)','ko':'한국어',
    'vi':'Tiếng Việt','tl':'Filipino','id':'Bahasa Indonesia',
    'pt':'Português','es':'Español','th':'ภาษาไทย','my':'မြန်မာဘာသာ'
  };

  // ===== 言語設定の読み込み・保存 =====
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

  // ===== 翻訳対象テキストの取得 =====
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
      // 日本語文字を含み、200文字以内のもの
      if (text && /[぀-ヿ一-鿿]/.test(text) && text.length <= 200) {
        return {el: el, text: text};
      }
      el = el.parentElement;
    }
    return null;
  }

  // ===== ツールチップ =====
  var highlightEl = null;

  function showTooltip(el, html) {
    hideTooltip();
    // タップ要素をハイライト
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

    // 位置計算：上下どちらにスペースが多いか
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
  }

  function hideTooltip() {
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
    if (cache[key]) {
      showTooltip(el, tipHtml(text, cache[key]));
      return;
    }
    showTooltip(el, '<div style="opacity:0.6;font-size:0.78rem;pointer-events:none;">翻訳中...</div>');
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
    // 読み上げボタン（onclick属性でIIFE外から呼ばれるためwindowに登録）
    window._ttSpeak = function () { speak(trans, lang); };
    return '<div style="font-size:0.68rem;opacity:0.55;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.12);padding-bottom:6px;">' + esc(orig) + '</div>' +
           '<div style="display:flex;align-items:flex-start;gap:8px;">' +
             '<div style="flex:1;font-weight:700;font-size:0.9rem;">' + flag + ' ' + esc(trans) + '</div>' +
             '<button onclick="_ttSpeak()" style="flex-shrink:0;background:rgba(255,255,255,0.15);border:none;color:#fff;border-radius:8px;padding:4px 8px;font-size:0.8rem;cursor:pointer;white-space:nowrap;">🔊</button>' +
           '</div>';
  }

  // ===== レンズクリックハンドラ =====
  // ナビゲーション・アクション要素は翻訳対象から除外（常に通過）
  var LENS_PASS = [
    '#tt-bar','#tt-lang-modal','#tt-lang-picker-modal','#tt-lens-btn',
    '.bottom-nav-item','.bottom-nav','a[href]','form','button[type="submit"]',
    '#user-settings-modal','.settings-fab','.tt-panel','.tt-field-btn',
    '.dw-overlay','#drawer-wrapper'
  ].join(',');

  function handleClick(e) {
    if (!lensActive) return;
    if (e.target.closest(LENS_PASS)) return;
    if (tooltip && tooltip.contains(e.target)) { hideTooltip(); return; }

    var found = findTarget(e.target);
    if (found) {
      // 日本語テキストが見つかった場合のみクリックをブロックして翻訳
      e.preventDefault();
      e.stopPropagation();
      translate(found.el, found.text);
    } else {
      // テキストなし → ツールチップを閉じてレンズOFF（ナビ操作として扱う）
      hideTooltip();
      disableLens();
    }
  }

  // ===== レンズモード ON/OFF =====
  function enableLens() {
    lensActive = true;
    document.body.classList.add('tt-lens-on');
    document.addEventListener('click', handleClick, true);
    updateBtn(true);
  }

  function disableLens() {
    lensActive = false;
    document.body.classList.remove('tt-lens-on');
    hideTooltip();
    document.removeEventListener('click', handleClick, true);
    updateBtn(false);
  }

  function updateBtn(active) {
    var btn = document.getElementById('tt-lens-btn');
    if (!btn) return;
    if (active) {
      btn.style.background = '#1a73e8';
      btn.style.color = '#fff';
      btn.querySelector('span').style.color = '#fff';
    } else {
      btn.style.background = '';
      btn.style.color = '';
      if (btn.querySelector('span')) btn.querySelector('span').style.color = '';
    }
    // ボタン表示: ON中はフラグ+虫眼鏡、OFF+言語設定済みはフラグのみ、未設定は虫眼鏡
    if (active && userLang) {
      btn.innerHTML = '<span style="font-size:1rem;line-height:1;">' + (LANG_FLAGS[userLang] || '🌐') + '</span>';
      btn.style.color = '#fff';
    } else if (!active && userLang) {
      btn.innerHTML = '<span style="font-size:1.25rem;line-height:1;">' + (LANG_FLAGS[userLang] || '🌐') + '</span>';
    } else {
      btn.innerHTML = '<span class="material-symbols-outlined">search</span>';
    }
  }

  // ===== 言語ピッカーモーダル =====
  window.ttLensToggle = async function () {
    var lang = await loadUserLang();
    if (lensActive) {
      // レンズON中 → OFF
      disableLens();
      return;
    }
    // レンズOFF → 言語ピッカーを開く（言語設定済みでも「このまま使う」ボタンで即起動できる）
    var modal = document.getElementById('tt-lang-picker-modal');
    var keepBtn = document.getElementById('tt-lens-keep-btn');
    if (keepBtn) keepBtn.style.display = lang ? '' : 'none';
    modal.classList.add('open');
  };

  window.ttLensPickLang = async function (lang) {
    await saveUserLang(lang);
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
    updateBtn(false);
    enableLens();
  };

  window.ttLensKeepLang = function () {
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
    enableLens();
  };

  window.ttLensClearLang = async function () {
    await saveUserLang('');
    disableLens();
    updateBtn(false);
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
  };

  window.ttLensOpenPicker = function () {
    disableLens();
    document.getElementById('tt-lang-picker-modal').classList.add('open');
  };

  // ===== 翻訳機能ON/OFF =====
  var TT_KEY = 'tt_enabled';
  function isTTEnabled() { return localStorage.getItem(TT_KEY) !== '0'; }

  window.ttSetEnabled = function (on) {
    localStorage.setItem(TT_KEY, on ? '1' : '0');
    var btn = document.getElementById('tt-lens-btn');
    if (!on) {
      disableLens();
      if (btn) btn.style.display = 'none';
      // tt_input.jsのボタンも非表示
      document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.display = 'none'; });
    } else {
      if (btn) btn.style.display = '';
      document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.display = ''; });
      updateBtn(false);
    }
  };

  // ===== CSS =====
  var s = document.createElement('style');
  s.textContent =
    'body.tt-lens-on { cursor: crosshair !important; }' +
    'body.tt-lens-on *:not(#tt-bar):not(#tt-lens-btn):not(#tt-lang-picker-modal) { cursor: crosshair !important; }' +
    'body.tt-lens-on .bottom-nav-item,.bottom-nav-item { cursor: pointer !important; }' +
    'body.tt-lens-on::before { content:""; position:fixed; inset:0; z-index:9700;' +
    '  background:rgba(26,115,232,0.07); pointer-events:none; border:2.5px solid rgba(26,115,232,0.25); box-sizing:border-box; }' +
    '.tt-lens-highlight { outline:2.5px solid #1a73e8 !important; outline-offset:2px !important;' +
    '  background:rgba(26,115,232,0.10) !important; border-radius:4px !important; }';
  document.head.appendChild(s);

  // ===== 初期化 =====
  document.addEventListener('DOMContentLoaded', async function () {
    var btn = document.getElementById('tt-lens-btn');
    if (!isTTEnabled()) {
      if (btn) btn.style.display = 'none';
      return;
    }
    await loadUserLang();
    updateBtn(false);
  });
})();
