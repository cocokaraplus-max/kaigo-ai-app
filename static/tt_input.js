// translation-v1: 外国人スタッフ向け翻訳入力バー
// 全テキストエリアにフォーカスすると、画面下に「🎤音声」「🌐翻訳」ボタンが出る。
// 🎤: 母国語で話す → 日本語に変換してテキストエリアに追記
// 🌐: テキストエリアの内容を日本語に翻訳して置き換え
(function () {
  'use strict';
  var bar = null;
  var activeField = null;
  var mediaRec = null;
  var recChunks = [];
  var isRecording = false;

  // ===== バー生成 =====
  function buildBar() {
    var b = document.createElement('div');
    b.id = 'tt-bar';
    b.setAttribute('aria-label', '翻訳入力');
    b.style.cssText = [
      'position:fixed;bottom:72px;left:50%;transform:translateX(-50%);z-index:8500;',
      'display:none;align-items:center;gap:8px;',
      'background:#fff;border-radius:40px;',
      'box-shadow:0 4px 20px rgba(16,24,40,0.18);',
      'padding:6px 14px 6px 12px;',
      'border:1.5px solid #e0e0e0;'
    ].join('');
    b.innerHTML =
      '<span style="font-size:0.72rem;color:#5f6368;font-weight:700;white-space:nowrap;">翻訳入力</span>' +
      '<button id="tt-mic" title="母国語で話して日本語に変換" style="' +
        'width:38px;height:38px;border-radius:50%;border:none;cursor:pointer;' +
        'background:#e8f0fe;color:#1a73e8;display:flex;align-items:center;justify-content:center;' +
        'transition:background .15s,color .15s;flex-shrink:0;">' +
        '<span class="material-symbols-outlined" style="font-size:20px;">mic</span>' +
      '</button>' +
      '<button id="tt-translate" title="入力したテキストを日本語に翻訳" style="' +
        'width:38px;height:38px;border-radius:50%;border:none;cursor:pointer;' +
        'background:#e8f0fe;color:#1a73e8;display:flex;align-items:center;justify-content:center;' +
        'transition:background .15s,color .15s;flex-shrink:0;">' +
        '<span class="material-symbols-outlined" style="font-size:20px;">translate</span>' +
      '</button>' +
      '<span id="tt-status" style="font-size:0.7rem;color:#ea4335;font-weight:700;display:none;white-space:nowrap;"></span>';
    document.body.appendChild(b);
    document.getElementById('tt-mic').addEventListener('mousedown', function (e) { e.preventDefault(); toggleRec(); });
    document.getElementById('tt-translate').addEventListener('mousedown', function (e) { e.preventDefault(); translateText(); });
    return b;
  }

  function showBar(field) {
    activeField = field;
    if (!bar) bar = buildBar();
    bar.style.display = 'flex';
    setStatus('');
  }

  function hideBar() {
    if (!bar) return;
    bar.style.display = 'none';
    if (isRecording) stopRec(false); // 録音中なら中断
    activeField = null;
    setStatus('');
  }

  function setStatus(msg, isErr) {
    var s = document.getElementById('tt-status');
    if (!s) return;
    if (msg) { s.textContent = msg; s.style.color = isErr ? '#ea4335' : '#1a73e8'; s.style.display = 'inline'; }
    else { s.textContent = ''; s.style.display = 'none'; }
  }

  // ===== テキスト翻訳 =====
  async function translateText() {
    if (!activeField) return;
    var text = activeField.value.trim();
    if (!text) { setStatus('テキストを入力してください', true); return; }
    var btn = document.getElementById('tt-translate');
    if (btn) btn.disabled = true;
    setStatus('翻訳中...');
    try {
      var r = await fetch('/api/translate/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
      });
      var d = await r.json();
      if (d.status === 'success') {
        activeField.value = d.translated;
        activeField.dispatchEvent(new Event('input', { bubbles: true }));
        setStatus('翻訳完了');
        setTimeout(function () { setStatus(''); }, 2000);
      } else {
        setStatus('翻訳失敗', true);
      }
    } catch (e) {
      setStatus('通信エラー', true);
    }
    if (btn) btn.disabled = false;
  }

  // ===== 音声録音 → 翻訳 =====
  function toggleRec() {
    if (isRecording) stopRec(true);
    else startRec();
  }

  async function startRec() {
    try {
      var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recChunks = [];
      mediaRec = new MediaRecorder(stream);
      mediaRec.ondataavailable = function (e) { if (e.data && e.data.size > 0) recChunks.push(e.data); };
      mediaRec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        sendAudio();
      };
      mediaRec.start();
      isRecording = true;
      var mic = document.getElementById('tt-mic');
      if (mic) { mic.style.background = '#ea4335'; mic.style.color = '#fff'; }
      setStatus('録音中... (再度タップで停止)');
    } catch (e) {
      setStatus('マイクにアクセスできません', true);
    }
  }

  function stopRec(sendResult) {
    if (mediaRec && mediaRec.state === 'recording') {
      if (!sendResult) mediaRec.onstop = function () {};
      mediaRec.stop();
    }
    isRecording = false;
    var mic = document.getElementById('tt-mic');
    if (mic) { mic.style.background = '#e8f0fe'; mic.style.color = '#1a73e8'; }
    if (sendResult) setStatus('変換中...');
  }

  async function sendAudio() {
    if (!activeField || !recChunks.length) { setStatus(''); return; }
    var blob = new Blob(recChunks, { type: 'audio/webm' });
    var reader = new FileReader();
    reader.onloadend = async function () {
      var b64 = reader.result.split(',')[1];
      try {
        var r = await fetch('/api/translate/voice', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ audio_data: b64, audio_mime: 'audio/webm' })
        });
        var d = await r.json();
        if (d.status === 'success' && activeField) {
          var cur = activeField.value;
          activeField.value = cur ? cur + '\n' + d.translated : d.translated;
          activeField.dispatchEvent(new Event('input', { bubbles: true }));
          setStatus('変換完了');
          setTimeout(function () { setStatus(''); }, 2000);
        } else {
          setStatus('変換失敗', true);
        }
      } catch (e) {
        setStatus('通信エラー', true);
      }
    };
    reader.readAsDataURL(blob);
  }

  // ===== テキストエリアへのイベント付与 =====
  function attach(el) {
    if (el.dataset.ttAttached) return;
    el.dataset.ttAttached = '1';
    el.addEventListener('focus', function () { showBar(el); });
    el.addEventListener('blur', function () {
      // バーのボタンを押したときは閉じない（mousedownでpreventDefaultしているので blur が先に来る）
      setTimeout(function () {
        if (bar && bar.style.display !== 'none') {
          if (document.activeElement && (bar.contains(document.activeElement) || document.activeElement === el)) return;
          hideBar();
        }
      }, 150);
    });
  }

  function attachAll() {
    document.querySelectorAll('textarea').forEach(attach);
  }

  document.addEventListener('DOMContentLoaded', function () {
    attachAll();
    // 動的に追加された textarea にも対応
    var obs = new MutationObserver(function () { attachAll(); });
    obs.observe(document.body, { childList: true, subtree: true });
  });
})();
