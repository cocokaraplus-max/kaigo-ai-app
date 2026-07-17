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
  function showTooltip(el, html) {
    hideTooltip();
    var t = document.createElement('div');
    t.id = 'tt-lens-tip';
    t.style.cssText = [
      'position:fixed;z-index:9900;pointer-events:none;',
      'background:#202124;color:#fff;border-radius:12px;',
      'padding:10px 14px;font-size:0.82rem;line-height:1.5;',
      'max-width:260px;word-break:break-word;',
      'box-shadow:0 4px 20px rgba(0,0,0,0.32);',
    ].join('');
    t.innerHTML = html;
    document.body.appendChild(t);
    tooltip = t;

    // 位置計算（要素の上 or 下）
    var rect = el.getBoundingClientRect();
    var th = t.offsetHeight || 60;
    var tw = t.offsetWidth || 260;
    var top = rect.top - th - 10;
    if (top < 8) top = rect.bottom + 10;
    var left = rect.left + (rect.width - tw) / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
    t.style.top = top + 'px';
    t.style.left = left + 'px';
  }

  function hideTooltip() {
    if (tooltip) { tooltip.remove(); tooltip = null; }
  }

  function esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ===== 翻訳 =====
  async function translate(el, text) {
    if (!userLang) return;
    var key = userLang + ':' + text;
    if (cache[key]) {
      showTooltip(el, tipHtml(text, cache[key]));
      return;
    }
    showTooltip(el, '<span style="opacity:0.6;font-size:0.78rem;">翻訳中...</span>');
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
    return '<div style="font-size:0.68rem;opacity:0.55;margin-bottom:4px;">' + esc(orig) + '</div>' +
           '<div style="font-weight:700;font-size:0.88rem;">' + flag + ' ' + esc(trans) + '</div>';
  }

  // ===== レンズクリックハンドラ =====
  function handleClick(e) {
    if (!lensActive) return;
    // 翻訳バー・モーダル・レンズボタン自体は通過させる
    if (e.target.closest('#tt-bar,#tt-lang-modal,#tt-lang-picker-modal,#tt-lens-btn')) return;
    if (tooltip && tooltip.contains(e.target)) { hideTooltip(); return; }

    e.preventDefault();
    e.stopPropagation();

    var found = findTarget(e.target);
    if (found) translate(found.el, found.text);
    else hideTooltip();
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
    // 言語が設定済みならフラグを表示
    if (!active && userLang) {
      btn.innerHTML = '<span style="font-size:1.25rem;line-height:1;">' + (LANG_FLAGS[userLang] || '🌐') + '</span>';
    } else if (!userLang) {
      btn.innerHTML = '<span class="material-symbols-outlined">search</span>';
    }
  }

  // ===== 言語ピッカーモーダル =====
  window.ttLensToggle = async function () {
    var lang = await loadUserLang();
    if (!lang) {
      document.getElementById('tt-lang-picker-modal').classList.add('open');
      return;
    }
    if (lensActive) disableLens();
    else enableLens();
  };

  window.ttLensPickLang = async function (lang) {
    await saveUserLang(lang);
    document.getElementById('tt-lang-picker-modal').classList.remove('open');
    updateBtn(false);
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

  // ===== CSS =====
  var s = document.createElement('style');
  s.textContent =
    'body.tt-lens-on { cursor: crosshair !important; }' +
    'body.tt-lens-on *:not(#tt-bar):not(#tt-lens-btn):not(#tt-lang-picker-modal) { cursor: crosshair !important; }' +
    'body.tt-lens-on::before { content:""; position:fixed; inset:0; z-index:9700;' +
    '  background:rgba(26,115,232,0.07); pointer-events:none; border:2.5px solid rgba(26,115,232,0.25); box-sizing:border-box; }';
  document.head.appendChild(s);

  // ===== 初期化 =====
  document.addEventListener('DOMContentLoaded', async function () {
    await loadUserLang();
    updateBtn(false);
  });
})();
