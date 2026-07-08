/* rec-keepalive-v1: 録音中に画面の自動スリープを防ぐ共通部品。
   第1段: Wake Lock の取得/解放/画面復帰時の自動再取得のみ。
   非対応端末(Wake Lock APIなし)では黙ってスキップし、録音は従来通り動く。
   使い方:
     recKeepAlive.acquire();   // 録音開始時
     recKeepAlive.release();   // 録音停止時
*/
(function (global) {
  var _lock = null;      // WakeLockSentinel
  var _active = false;   // acquire中かどうか(録音中フラグ)

  function _supported() {
    return ('wakeLock' in navigator) && navigator.wakeLock && typeof navigator.wakeLock.request === 'function';
  }

  async function _request() {
    if (!_supported()) return;
    try {
      _lock = await navigator.wakeLock.request('screen');
      if (_lock) {
        _lock.addEventListener('release', function () {
          // OSやタブ非表示で解放された。録音継続中なら復帰時に再取得する。
          _lock = null;
        });
      }
    } catch (e) {
      // 権限/状況により失敗することがある。録音自体は継続。
      _lock = null;
    }
  }

  function acquire() {
    _active = true;
    _request();
  }

  function release() {
    _active = false;
    if (_lock) {
      try { _lock.release(); } catch (e) {}
      _lock = null;
    }
  }

  // タブが再び前面に来たとき、録音継続中なら Wake Lock を取り直す
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && _active && !_lock) {
      _request();
    }
  });

  global.recKeepAlive = { acquire: acquire, release: release, supported: _supported };
})(window);
