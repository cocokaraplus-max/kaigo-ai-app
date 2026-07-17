// translation-v1: 外国人スタッフ向け翻訳入力
// テキストエリアの右下に小さい翻訳ボタンを設置。タップで展開。
// キーボード表示中に被らないよう、自動ポップアップはしない。
(function () {
  'use strict';

  var activeField = null;
  var expandedField = null;  // 翻訳パネルが開いているフィールド
  var mediaRec = null;
  var recChunks = [];
  var isRecording = false;

  // ===== テキストエリアごとのボタン付与 =====
  function attach(ta) {
    if (ta.dataset.ttAttached) return;
    ta.dataset.ttAttached = '1';

    // ラッパーを作る（relative 位置のコンテナ）
    var parent = ta.parentElement;
    if (!parent) return;
    if (parent.classList.contains('tt-wrap')) return;

    // ラッパーで包む
    var wrap = document.createElement('div');
    wrap.className = 'tt-wrap';
    wrap.style.cssText = 'position:relative;display:block;';
    parent.insertBefore(wrap, ta);
    wrap.appendChild(ta);

    // 翻訳ボタン（右下の小アイコン）
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tt-field-btn';
    btn.title = '翻訳入力';
    btn.innerHTML = '<span style="font-size:1rem;">文A</span>';
    btn.style.cssText = [
      'position:absolute;bottom:6px;right:6px;',
      'width:32px;height:32px;border-radius:50%;',
      'border:none;background:rgba(26,115,232,0.12);color:#1a73e8;',
      'cursor:pointer;display:flex;align-items:center;justify-content:center;',
      'font-size:0.72rem;font-weight:800;z-index:10;',
      'transition:background .15s;',
      '-webkit-tap-highlight-color:transparent;',
    ].join('');
    wrap.appendChild(btn);

    // 翻訳パネル（ボタン直下）
    var panel = buildPanel(ta, btn, wrap);
    wrap.appendChild(panel);

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      togglePanel(ta, panel, btn);
    });

    ta.addEventListener('focus', function () { activeField = ta; });
    ta.addEventListener('blur', function () {
      // パネルが開いている間はactiveFieldを保持
      if (expandedField !== ta) activeField = null;
    });
  }

  function buildPanel(ta, btn, wrap) {
    var p = document.createElement('div');
    p.className = 'tt-panel';
    p.style.cssText = [
      'display:none;position:absolute;right:0;bottom:calc(100% + 4px);z-index:200;',
      'background:#fff;border-radius:14px;',
      'box-shadow:0 4px 20px rgba(16,24,40,0.16);border:1.5px solid #e0e0e0;',
      'padding:8px 10px;display:none;align-items:center;gap:8px;white-space:nowrap;',
    ].join('');
    p.innerHTML =
      '<span style="font-size:0.72rem;color:#5f6368;font-weight:700;">翻訳入力</span>' +
      '<button type="button" class="tt-panel-mic" title="母国語で話して日本語に変換" style="' +
        'width:36px;height:36px;border-radius:50%;border:none;cursor:pointer;' +
        'background:#e8f0fe;color:#1a73e8;display:flex;align-items:center;justify-content:center;">' +
        '<span class="material-symbols-outlined" style="font-size:19px;">mic</span>' +
      '</button>' +
      '<button type="button" class="tt-panel-translate" title="テキストを日本語に翻訳" style="' +
        'width:36px;height:36px;border-radius:50%;border:none;cursor:pointer;' +
        'background:#e8f0fe;color:#1a73e8;display:flex;align-items:center;justify-content:center;">' +
        '<span class="material-symbols-outlined" style="font-size:19px;">translate</span>' +
      '</button>' +
      '<span class="tt-panel-status" style="font-size:0.7rem;color:#1a73e8;font-weight:700;display:none;"></span>';

    p.querySelector('.tt-panel-mic').addEventListener('mousedown', function (e) {
      e.preventDefault();
      toggleRec(ta, p);
    });
    p.querySelector('.tt-panel-translate').addEventListener('mousedown', function (e) {
      e.preventDefault();
      translateText(ta, p);
    });
    return p;
  }

  function togglePanel(ta, panel, btn) {
    var isOpen = panel.style.display === 'flex';
    // 他の全パネルを閉じる
    document.querySelectorAll('.tt-panel').forEach(function (p) { p.style.display = 'none'; });
    document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.background = 'rgba(26,115,232,0.12)'; });
    if (isRecording) stopRec(false);
    expandedField = null;

    if (!isOpen) {
      panel.style.display = 'flex';
      btn.style.background = 'rgba(26,115,232,0.25)';
      expandedField = ta;
      activeField = ta;
    }
  }

  // ===== テキスト翻訳 =====
  async function translateText(ta, panel) {
    var text = ta.value.trim();
    if (!text) { setStatus(panel, 'テキストを入力してください', true); return; }
    var btn = panel.querySelector('.tt-panel-translate');
    if (btn) btn.disabled = true;
    setStatus(panel, '翻訳中...');
    try {
      var r = await fetch('/api/translate/text', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})
      });
      var d = await r.json();
      if (d.status === 'success') {
        ta.value = d.translated;
        ta.dispatchEvent(new Event('input', {bubbles: true}));
        setStatus(panel, '翻訳完了');
        setTimeout(function () { setStatus(panel, ''); }, 2000);
      } else { setStatus(panel, '翻訳失敗', true); }
    } catch (e) { setStatus(panel, '通信エラー', true); }
    if (btn) btn.disabled = false;
  }

  // ===== 音声録音 → 翻訳 =====
  function toggleRec(ta, panel) {
    if (isRecording) stopRec(true, ta, panel);
    else startRec(ta, panel);
  }

  async function startRec(ta, panel) {
    try {
      var stream = await navigator.mediaDevices.getUserMedia({audio: true});
      recChunks = [];
      mediaRec = new MediaRecorder(stream);
      mediaRec.ondataavailable = function (e) { if (e.data && e.data.size > 0) recChunks.push(e.data); };
      mediaRec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        sendAudio(ta, panel);
      };
      mediaRec.start();
      isRecording = true;
      var mic = panel.querySelector('.tt-panel-mic');
      if (mic) { mic.style.background = '#ea4335'; mic.style.color = '#fff'; }
      setStatus(panel, '録音中...');
    } catch (e) {
      setStatus(panel, 'マイクにアクセスできません', true);
    }
  }

  function stopRec(send, ta, panel) {
    if (mediaRec && mediaRec.state === 'recording') {
      if (!send) mediaRec.onstop = function () {};
      mediaRec.stop();
    }
    isRecording = false;
    // 全パネルのmicボタンをリセット
    document.querySelectorAll('.tt-panel-mic').forEach(function (b) {
      b.style.background = '#e8f0fe'; b.style.color = '#1a73e8';
    });
    if (send && panel) setStatus(panel, '変換中...');
  }

  async function sendAudio(ta, panel) {
    if (!recChunks.length) { setStatus(panel, ''); return; }
    var blob = new Blob(recChunks, {type: 'audio/webm'});
    var reader = new FileReader();
    reader.onloadend = async function () {
      var b64 = reader.result.split(',')[1];
      try {
        var r = await fetch('/api/translate/voice', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({audio_data: b64, audio_mime: 'audio/webm'})
        });
        var d = await r.json();
        if (d.status === 'success') {
          var cur = ta.value;
          ta.value = cur ? cur + '\n' + d.translated : d.translated;
          ta.dispatchEvent(new Event('input', {bubbles: true}));
          setStatus(panel, '変換完了');
          setTimeout(function () { setStatus(panel, ''); }, 2000);
        } else { setStatus(panel, '変換失敗', true); }
      } catch (e) { setStatus(panel, '通信エラー', true); }
    };
    reader.readAsDataURL(blob);
  }

  function setStatus(panel, msg, isErr) {
    var s = panel ? panel.querySelector('.tt-panel-status') : null;
    if (!s) return;
    if (msg) { s.textContent = msg; s.style.color = isErr ? '#ea4335' : '#1a73e8'; s.style.display = 'inline'; }
    else { s.textContent = ''; s.style.display = 'none'; }
  }

  // ===== 外タップで閉じる =====
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.tt-wrap')) {
      document.querySelectorAll('.tt-panel').forEach(function (p) { p.style.display = 'none'; });
      document.querySelectorAll('.tt-field-btn').forEach(function (b) { b.style.background = 'rgba(26,115,232,0.12)'; });
      expandedField = null;
    }
  });

  // ===== 初期化・動的要素対応 =====
  function attachAll() {
    document.querySelectorAll('textarea').forEach(attach);
  }

  document.addEventListener('DOMContentLoaded', function () {
    attachAll();
    new MutationObserver(function () { attachAll(); }).observe(document.body, {childList: true, subtree: true});
  });
})();
