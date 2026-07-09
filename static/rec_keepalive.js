/* rec-keepalive-v2: 録音中の画面スリープ防止 + 中断検知/自動再開 + 明暗トグル。
   第1段(v1): Wake Lock 取得/解放/画面復帰時の再取得。
   第2段(v2): 中断検知→自動再開コールバック(失敗時は警告バナー+手動再開)、
              明るさトグル(明るく保つ/省電力オーバーレイ)。
   使い方:
     recKeepAlive.start({
       onResume: async function(){ ... 録音を再開する処理。成功で true を返す ... },
       label: '会議'   // 任意
     });
     recKeepAlive.stop();   // 録音停止時
*/
(function (global) {
  var _lock = null;
  var _active = false;
  var _onResume = null;
  var _wasHidden = false;
  var _bannerEl = null;
  var _toggleEl = null;
  var _dimEl = null;
  var _dimmed = false;

  function _supported() {
    return ('wakeLock' in navigator) && navigator.wakeLock && typeof navigator.wakeLock.request === 'function';
  }

  async function _request() {
    if (!_supported()) return;
    try {
      _lock = await navigator.wakeLock.request('screen');
      if (_lock) _lock.addEventListener('release', function () { _lock = null; });
    } catch (e) { _lock = null; }
  }

  // ---- UI: 警告バナー ----
  function _ensureBanner() {
    if (_bannerEl) return _bannerEl;
    var b = document.createElement('div');
    b.id = 'recKaBanner';
    b.style.cssText = 'display:none;position:fixed;left:12px;right:12px;bottom:78px;z-index:9998;'
      + 'background:#fff3e0;border:1.5px solid #ffb74d;border-radius:12px;padding:12px 14px;'
      + 'box-shadow:0 4px 16px rgba(0,0,0,.18);font-size:0.86rem;color:#e65100;'
      + 'display:none;align-items:center;justify-content:space-between;gap:10px;';
    b.innerHTML = '<span id="recKaBannerMsg">録音が中断された可能性があります。</span>'
      + '<button id="recKaResumeBtn" style="padding:7px 12px;border:none;border-radius:8px;'
      + 'background:#e65100;color:#fff;font-weight:700;cursor:pointer;font-size:0.82rem;white-space:nowrap;">録音を再開</button>';
    document.body.appendChild(b);
    b.querySelector('#recKaResumeBtn').addEventListener('click', function () {
      _hideBanner();
      _tryResume(true);
    });
    _bannerEl = b;
    return b;
  }
  function _showBanner(msg) {
    var b = _ensureBanner();
    if (msg) b.querySelector('#recKaBannerMsg').textContent = msg;
    b.style.display = 'flex';
  }
  function _hideBanner() { if (_bannerEl) _bannerEl.style.display = 'none'; }

  // ---- UI: 明暗トグル ----
  function _ensureToggle() {
    if (_toggleEl) return _toggleEl;
    var t = document.createElement('button');
    t.id = 'recKaToggle';
    t.type = 'button';
    t.style.cssText = 'display:none;position:fixed;right:12px;bottom:130px;z-index:9998;'
      + 'padding:9px 13px;border:1.5px solid #1b5e20;border-radius:20px;background:#fff;'
      + 'color:#1b5e20;font-weight:700;font-size:0.8rem;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);';
    t.textContent = '🔆 画面: 明るく保つ';
    document.body.appendChild(t);
    t.addEventListener('click', function () { _dimmed ? _undim() : _dim(); });
    _toggleEl = t;
    return t;
  }
  function _showToggle() { _ensureToggle().style.display = 'block'; }
  function _hideToggle() { if (_toggleEl) _toggleEl.style.display = 'none'; }

  // ---- UI: 省電力オーバーレイ ----
  function _dim() {
    _dimmed = true;
    if (!_dimEl) {
      var d = document.createElement('div');
      d.id = 'recKaDim';
      d.style.cssText = 'position:fixed;inset:0;z-index:9997;background:#000;'
        + 'display:flex;align-items:center;justify-content:center;color:#333;'
        + 'font-size:0.8rem;';
      d.innerHTML = '<div style="text-align:center;line-height:1.8;">'
        + '<div style="font-size:1.4rem;">●REC</div>'
        + '<div>録音中（省電力表示）</div><div>画面をタップで戻る</div></div>';
      d.addEventListener('click', _undim);
      document.body.appendChild(d);
      _dimEl = d;
    }
    _dimEl.style.display = 'flex';
    if (_toggleEl) _toggleEl.textContent = '🌙 画面: 省電力（暗く）';
  }
  function _undim() {
    _dimmed = false;
    if (_dimEl) _dimEl.style.display = 'none';
    if (_toggleEl) _toggleEl.textContent = '🔆 画面: 明るく保つ';
  }

  // ---- 中断→再開 ----
  async function _tryResume(manual) {
    if (!_active || typeof _onResume !== 'function') return;
    try {
      var ok = await _onResume();  // ページ側で録音を再開。成功でtrue。
      if (ok) { _hideBanner(); await _request(); }
      else { _showBanner('録音が中断されました。「録音を再開」を押してください。'); }
    } catch (e) {
      _showBanner('録音が中断されました。「録音を再開」を押してください。');
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (!_active) return;
    if (document.visibilityState === 'hidden') {
      _wasHidden = true;  // バックグラウンド化(録音が切れた可能性)
    } else if (document.visibilityState === 'visible') {
      // 前面復帰: Wake Lock取り直し + 中断していたら自動再開を試みる
      if (!_lock) _request();
      if (_wasHidden) { _wasHidden = false; _tryResume(false); }
    }
  });

  function start(opts) {
    opts = opts || {};
    _active = true;
    _onResume = opts.onResume || null;
    _wasHidden = false;
    _request();
    _showToggle();
    _undim();
  }
  function stop() {
    _active = false;
    _onResume = null;
    if (_lock) { try { _lock.release(); } catch (e) {} _lock = null; }
    _hideBanner();
    _hideToggle();
    _undim();
  }

  // 後方互換(v1のacquire/releaseも生かす)
  function acquire() { start({}); }
  function release() { stop(); }

  global.recKeepAlive = { start: start, stop: stop, acquire: acquire, release: release, supported: _supported };
})(window);
