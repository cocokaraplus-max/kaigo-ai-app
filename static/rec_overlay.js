/* rec-overlay-v1: 録音したまま、TASUKARUの他の画面を使う。
   ------------------------------------------------------------------
   ★なぜこの作りなのか（次に触る人へ）
   録音は「そのページのJavaScript」が持っている（getUserMedia + MediaRecorder）。
   リンクを押して画面を移動すると、ブラウザはページごと捨てるので録音も消える。
   これはブラウザの決まりで、どう書いても避けられない。

   そこで、録音している画面を「土台」として残したまま、
   他の画面を全画面のiframeで“上にかぶせて”開く。
   土台は生きたままなので、
     ・録音が1秒も途切れない
     ・マイクの許可を出し直さない
     ・文字起こしの区切り(チャンク)もそのまま続く

   ★別ウィンドウで開く方式は採らなかった。
   iPad/iPhone の Safari は、裏に回ったタブの録音を止めてしまうため。
   Android と iOS の両方で確実に動くのは、この“重ねる”方式だけ。

   ★iframe に sandbox は付けていない。
   付けると土台への移動を禁止できるが、ServiceWorker や保存まわりで
   予期しない壊れ方をする恐れがある。
   templates/ と static/ を全部調べて target="_top" / target="_parent" /
   window.top への代入が1件も無いことを確認したうえで、付けない判断をした。
   ★もし将来そういう書き方を足すなら、ここに sandbox を戻すか、その書き方をやめること。

   使い方:
     recOverlay.start({ label:'担当者会議' });   // 録音開始と同時に
     recOverlay.stop();                          // 録音停止と同時に
   ------------------------------------------------------------------ */
(function (global) {
  'use strict';

  var HOME = '/';                 // かぶせて開く最初の画面（ログイン済みならトップへ飛ぶ）
  var Z    = 2147480000;          // base.html の最大 z-index(99999) より確実に上

  var _active = false;            // 録音中か
  var _open   = false;            // かぶせて開いているか
  var _t0     = 0;                // 録音開始時刻
  var _timer  = null;
  var _label  = '';
  var _fab = null, _wrap = null, _frame = null, _clock = null, _fabTime = null;
  var _pushed = false;            // 戻る操作を受け止めるために履歴を1つ積んだか

  function _hhmmss(ms) {
    var s = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return (h ? h + ':' : '') + p(m) + ':' + p(ss);
  }

  function _tick() {
    var t = _hhmmss(Date.now() - _t0);
    if (_clock)   _clock.textContent = t;
    if (_fabTime) _fabTime.textContent = t;
  }

  // ---------------------------------------------------------- ボタン
  function _ensureFab() {
    if (_fab) return _fab;
    var b = document.createElement('button');
    b.id = 'recOvFab';
    b.type = 'button';
    // recKeepAlive のバナー(bottom:78px)と明暗トグル(bottom:130px)の上に置く
    b.style.cssText =
      'display:none;position:fixed;right:12px;bottom:182px;z-index:' + (Z - 10) + ';' +
      'padding:11px 15px;border:2px solid #fff;border-radius:22px;' +
      'background:#1b5e20;color:#fff;font-weight:800;font-size:0.84rem;' +
      'font-family:inherit;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.28);' +
      'line-height:1.35;text-align:left;';
    b.innerHTML =
      '<span style="display:block;">📱 他の機能をひらく</span>' +
      '<span style="display:block;font-weight:600;font-size:0.72rem;opacity:.9;">' +
      '● 録音中 <span id="recOvFabTime">00:00</span>（止まりません）</span>';
    document.body.appendChild(b);
    b.addEventListener('click', open);
    _fab = b;
    _fabTime = b.querySelector('#recOvFabTime');
    return b;
  }

  // ---------------------------------------------------------- かぶせる画面
  function _ensureWrap() {
    if (_wrap) return _wrap;

    var w = document.createElement('div');
    w.id = 'recOvWrap';
    w.style.cssText =
      'display:none;position:fixed;inset:0;z-index:' + Z + ';background:#eef1ee;' +
      'flex-direction:column;font-family:inherit;';

    var bar = document.createElement('div');
    bar.style.cssText =
      'flex:0 0 auto;display:flex;align-items:center;gap:8px;' +
      'padding:calc(8px + env(safe-area-inset-top)) 10px 8px;' +
      'background:#1b5e20;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.25);';

    var back = document.createElement('button');
    back.type = 'button';
    back.style.cssText =
      'flex:0 0 auto;padding:8px 11px;border:1px solid rgba(255,255,255,.55);' +
      'border-radius:9px;background:transparent;color:#fff;font-weight:800;' +
      'font-size:0.82rem;font-family:inherit;cursor:pointer;';
    back.textContent = '← 戻る';
    back.addEventListener('click', function () {
      // iframeの中だけを1つ戻す（土台の履歴は動かさない）
      try { _frame.contentWindow.history.back(); } catch (e) {}
    });

    var mid = document.createElement('div');
    mid.style.cssText = 'flex:1;min-width:0;line-height:1.35;';
    mid.innerHTML =
      '<div style="font-weight:800;font-size:0.86rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
      '<span id="recOvDot" style="display:inline-block;width:9px;height:9px;border-radius:50%;' +
      'background:#ff5252;margin-right:6px;vertical-align:middle;"></span>' +
      '録音中 <span id="recOvClock">00:00</span>' +
      '<span id="recOvLabel" style="font-weight:600;opacity:.85;"></span></div>' +
      '<div style="font-size:0.68rem;opacity:.85;">録音は止まっていません。終わったら「閉じる」で録音画面へ戻ってください。</div>';

    var close = document.createElement('button');
    close.type = 'button';
    close.style.cssText =
      'flex:0 0 auto;padding:9px 13px;border:none;border-radius:9px;' +
      'background:#fff;color:#1b5e20;font-weight:800;font-size:0.82rem;' +
      'font-family:inherit;cursor:pointer;';
    close.textContent = '閉じる';
    close.addEventListener('click', function () { close_(true); });

    bar.appendChild(back); bar.appendChild(mid); bar.appendChild(close);

    var fr = document.createElement('iframe');
    fr.id = 'recOvFrame';
    fr.setAttribute('title', 'TASUKARU');
    // sandbox は付けない（ファイル冒頭の「★iframe に sandbox は付けていない」を読むこと）
    fr.style.cssText = 'flex:1 1 auto;width:100%;border:0;background:#eef1ee;';

    var note = document.createElement('div');
    note.style.cssText =
      'flex:0 0 auto;padding:6px 12px calc(6px + env(safe-area-inset-bottom));' +
      'background:#fff7ee;color:#9a5a1a;font-size:0.68rem;font-weight:700;text-align:center;' +
      'border-top:1px solid #e0b58a;';
    note.textContent = '※ 録音中は、この中の「音声入力」は使わないでください（マイクの取り合いになります）';

    w.appendChild(bar); w.appendChild(fr); w.appendChild(note);
    document.body.appendChild(w);

    _wrap = w; _frame = fr; _clock = w.querySelector('#recOvClock');
    return w;
  }

  // ---------------------------------------------------------- 開閉
  function open() {
    if (!_active) return;
    _ensureWrap();
    if (!_frame.getAttribute('src')) _frame.setAttribute('src', HOME);
    _wrap.style.display = 'flex';
    _open = true;
    if (_fab) _fab.style.display = 'none';
    _tick();
    // Androidの「戻る」で土台ごと閉じられないよう、履歴を1つ積んでおく
    try { history.pushState({ recOverlay: 1 }, ''); _pushed = true; } catch (e) {}
  }

  function close_(popHistory) {
    if (!_open) return;
    _open = false;
    if (_wrap) _wrap.style.display = 'none';
    if (_active && _fab) _fab.style.display = 'block';
    if (popHistory && _pushed) { _pushed = false; try { history.back(); } catch (e) {} }
  }

  // Androidの戻るボタン／スワイプ：土台を離れる代わりに、かぶせた画面を閉じる
  window.addEventListener('popstate', function () {
    _pushed = false;
    if (_open) close_(false);
  });

  // ---------------------------------------------------------- 離脱防止
  /* 担当者会議は5分ごとにしか音声を送っていない。
     つまり、送る前の最大5分ぶんはブラウザの中にしか無い。
     録音中にうっかりページを離れると、その5分が黙って消える。
     ここで一度止めて聞き返す。 */
  function _beforeUnload(e) {
    if (!_active) return;
    e.preventDefault();
    e.returnValue = '録音中です。このページを離れると、まだ送っていない音声が失われます。';
    return e.returnValue;
  }

  // ---------------------------------------------------------- 開始/停止
  function start(opts) {
    opts = opts || {};
    _label = opts.label || '';
    if (opts.home) HOME = opts.home;
    _active = true;
    _t0 = opts.startedAt || Date.now();
    _ensureFab().style.display = 'block';
    _ensureWrap();
    var lab = _wrap.querySelector('#recOvLabel');
    if (lab) lab.textContent = _label ? '（' + _label + '）' : '';
    _tick();
    if (_timer) clearInterval(_timer);
    _timer = setInterval(_tick, 1000);
    window.addEventListener('beforeunload', _beforeUnload);
  }

  function stop() {
    _active = false;
    if (_timer) { clearInterval(_timer); _timer = null; }
    close_(false);
    if (_fab) _fab.style.display = 'none';
    if (_frame) _frame.removeAttribute('src');   // 次の録音では最初から開き直す
    window.removeEventListener('beforeunload', _beforeUnload);
  }

  global.recOverlay = { start: start, stop: stop, open: open, close: function () { close_(true); },
                        isActive: function () { return _active; }, isOpen: function () { return _open; } };
})(window);
