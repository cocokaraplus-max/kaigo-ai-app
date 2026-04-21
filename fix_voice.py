# coding: utf-8
import sys

path = 'templates/input.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

print('File loaded, length:', len(html))

# ---- STEP 1: HTMLボタン部分の置き換え ----
old_btns = (
    '<div style="display:flex; gap:8px; align-items:center;">\n'
    '            <button type="button" class="btn btn-primary btn-sm" id="rec-btn" onclick="toggleRecording()">\n'
    '                <span class="material-symbols-outlined">mic</span>\n'
    '                \u9332\u97f3\u958b\u59cb\n'
    '            </button>\n'
    '            <span id="rec-status" style="font-size:0.82rem; color:#5f6368;"></span>\n'
    '        </div>'
)

new_btns = (
    '<div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">\n'
    '            <button type="button" class="btn btn-primary btn-sm" id="rec-btn" onclick="toggleRecording()">\n'
    '                <span class="material-symbols-outlined">mic</span>\n'
    '                \u9332\u97f3\u958b\u59cb\n'
    '            </button>\n'
    '            <button type="button" id="pause-btn" onclick="togglePause()"\n'
    '                style="display:none; align-items:center; gap:5px; padding:8px 16px;\n'
    '                       background:#f59e0b; color:#fff; border:none; border-radius:10px;\n'
    '                       font-size:0.85rem; cursor:pointer; font-weight:600;">\n'
    '                \u23f8 \u4e00\u6642\u505c\u6b62\n'
    '            </button>\n'
    '            <span id="rec-status" style="font-size:0.82rem; color:#5f6368;"></span>\n'
    '        </div>'
)

if old_btns in html:
    html = html.replace(old_btns, new_btns)
    print('STEP1 OK: button HTML replaced')
else:
    print('STEP1 NG: old_btns not found - trying flexible match...')
    idx = html.find('rec-btn')
    if idx >= 0:
        print('rec-btn found at index', idx)
        print('Context:', repr(html[idx-100:idx+400]))
    sys.exit(1)

# ---- STEP 2: JSコードの置き換え ----
old_js_marker = 'let mediaRecorder = null, audioChunks = [], isRecording = false;'
old_js_end    = "    } finally {\n        document.getElementById('ai-loading').style.display = 'none';\n    }\n}"

new_js = """// ===== \u97f3\u58f0\u5165\u529b\uff08\u6539\u5584\u7248: \u4e00\u6642\u505c\u6b62\u30fb\u518d\u958b\u30fb\u30a8\u30e9\u30fc\u5f37\u5316\uff09=====
let mediaRecorder = null;
let audioChunks = [];
let allAudioBlobs = [];
let isRecording = false;
let isPaused = false;
let currentStream = null;
let audioMimeType = '';

function updateVoiceUI() {
    const btn      = document.getElementById('rec-btn');
    const pauseBtn = document.getElementById('pause-btn');
    const status   = document.getElementById('rec-status');
    if (!isRecording && !isPaused) {
        btn.innerHTML = '<span class="material-symbols-outlined">mic</span> \u9332\u97f3\u958b\u59cb';
        btn.style.background = '';
        btn.style.color = '';
        if (pauseBtn) pauseBtn.style.display = 'none';
        if (allAudioBlobs.length > 0) {
            status.textContent = '\u9332\u97f3\u5b8c\u4e86 \u2705 \u300cAI\u30c6\u30ad\u30b9\u30c8\u5909\u63db\u300d\u3092\u62bc\u3057\u3066\u304f\u3060\u3055\u3044';
            status.style.color = '#16a34a';
        } else {
            status.textContent = '';
        }
    } else if (isRecording && !isPaused) {
        btn.innerHTML = '<span class="material-symbols-outlined">stop_circle</span> \u9332\u97f3\u7d42\u4e86';
        btn.style.background = '#ea4335';
        btn.style.color = '#fff';
        if (pauseBtn) {
            pauseBtn.style.display = 'inline-flex';
            pauseBtn.style.background = '#f59e0b';
            pauseBtn.textContent = '\u23f8 \u4e00\u6642\u505c\u6b62';
        }
        status.textContent = '\u25cf \u9332\u97f3\u4e2d...';
        status.style.color = '#ea4335';
    } else if (isPaused) {
        btn.innerHTML = '<span class="material-symbols-outlined">stop_circle</span> \u9332\u97f3\u7d42\u4e86';
        btn.style.background = '#ea4335';
        btn.style.color = '#fff';
        if (pauseBtn) {
            pauseBtn.style.display = 'inline-flex';
            pauseBtn.style.background = '#2563eb';
            pauseBtn.textContent = '\u25b6 \u518d\u958b';
        }
        status.textContent = '\u4e00\u6642\u505c\u6b62\u4e2d \u2014 \u300c\u518d\u958b\u300d\u3067\u307e\u305f\u9332\u97f3\u3067\u304d\u307e\u3059';
        status.style.color = '#f59e0b';
    }
}

window.toggleRecording = async function() {
    const status = document.getElementById('rec-status');
    if (!isRecording && !isPaused) {
        try {
            currentStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4'];
            audioMimeType = mimeTypes.find(m => MediaRecorder.isTypeSupported(m)) || '';
            mediaRecorder = new MediaRecorder(currentStream, audioMimeType ? { mimeType: audioMimeType } : {});
            audioChunks = [];
            mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.onstop = () => {
                if (audioChunks.length > 0) {
                    allAudioBlobs.push(new Blob(audioChunks, { type: audioMimeType || 'audio/webm' }));
                    audioChunks = [];
                }
            };
            mediaRecorder.start(500);
            isRecording = true;
            isPaused = false;
            updateVoiceUI();
        } catch(e) {
            if (e.name === 'NotAllowedError') {
                status.textContent = '\u30de\u30a4\u30af\u306e\u8a31\u53ef\u304c\u5fc5\u8981\u3067\u3059\u3002\u30d6\u30e9\u30a6\u30b6\u306e\u8a2d\u5b9a\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
            } else if (e.name === 'NotFoundError') {
                status.textContent = '\u30de\u30a4\u30af\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3002\u63a5\u7d9a\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
            } else {
                status.textContent = '\u30de\u30a4\u30af\u30a8\u30e9\u30fc: ' + e.message;
            }
            status.style.color = '#ea4335';
        }
    } else {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
        if (currentStream) { currentStream.getTracks().forEach(t => t.stop()); currentStream = null; }
        isRecording = false;
        isPaused = false;
        setTimeout(async () => { await buildFinalAudio(); updateVoiceUI(); }, 300);
    }
}

window.togglePause = async function() {
    if (!isRecording && !isPaused) return;
    const status = document.getElementById('rec-status');
    if (!isPaused) {
        if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
        isRecording = false;
        isPaused = true;
        updateVoiceUI();
    } else {
        try {
            if (!currentStream || currentStream.getTracks().every(t => t.readyState === 'ended')) {
                currentStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            }
            audioChunks = [];
            mediaRecorder = new MediaRecorder(currentStream, audioMimeType ? { mimeType: audioMimeType } : {});
            mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.onstop = () => {
                if (audioChunks.length > 0) {
                    allAudioBlobs.push(new Blob(audioChunks, { type: audioMimeType || 'audio/webm' }));
                    audioChunks = [];
                }
            };
            mediaRecorder.start(500);
            isRecording = true;
            isPaused = false;
            updateVoiceUI();
        } catch(e) {
            status.textContent = '\u518d\u958b\u306b\u5931\u6557\u3057\u307e\u3057\u305f: ' + e.message;
            status.style.color = '#ea4335';
        }
    }
}

async function buildFinalAudio() {
    if (allAudioBlobs.length === 0) return;
    const finalBlob = new Blob(allAudioBlobs, { type: audioMimeType || 'audio/webm' });
    return new Promise(resolve => {
        const reader = new FileReader();
        reader.onload = e => {
            document.getElementById('audio-data').value = e.target.result.split(',')[1];
            document.getElementById('audio-mime').value = finalBlob.type;
            document.getElementById('ai-btn').style.display = 'flex';
            resolve();
        };
        reader.readAsDataURL(finalBlob);
    });
}

window.aiTranscribe = async function() {
    const audioData = document.getElementById('audio-data').value;
    const audioMime = document.getElementById('audio-mime').value;
    const status    = document.getElementById('rec-status');
    if (!audioData) return;
    document.getElementById('ai-btn').style.display = 'none';
    document.getElementById('ai-loading').style.display = 'flex';
    status.textContent = 'AI\u6587\u5b57\u8d77\u3053\u3057\u4e2d...';
    status.style.color = '#2563eb';
    const MAX_RETRY = 2;
    let lastError = null;
    for (let attempt = 1; attempt <= MAX_RETRY; attempt++) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 60000);
            const res = await fetch('/api/transcribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ audio_data: audioData, audio_mime: audioMime }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (!res.ok) {
                const errText = await res.text();
                throw new Error('\u30b5\u30fc\u30d0\u30fc\u30a8\u30e9\u30fc ' + res.status + ': ' + errText.slice(0, 100));
            }
            const data = await res.json();
            if (data.text) {
                const textarea = document.getElementById('content-area');
                const existing = textarea.value.trim();
                textarea.value = existing ? existing + '\\n' + data.text : data.text;
                status.textContent = '\u6587\u5b57\u8d77\u3053\u3057\u5b8c\u4e86\uff01\u5185\u5bb9\u3092\u78ba\u8a8d\u3057\u3066\u4fdd\u5b58\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
                status.style.color = '#16a34a';
                allAudioBlobs = [];
                document.getElementById('audio-data').value = '';
                document.getElementById('audio-mime').value = '';
                document.getElementById('ai-loading').style.display = 'none';
                return;
            } else if (data.error) {
                throw new Error(data.error);
            } else {
                throw new Error('\u30c6\u30ad\u30b9\u30c8\u304c\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f');
            }
        } catch(e) {
            lastError = e;
            if (e.name === 'AbortError') {
                lastError = new Error('\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8\uff0860\u79d2\uff09\u3057\u307e\u3057\u305f\u3002\u97f3\u58f0\u304c\u9577\u3044\u5834\u5408\u306f\u5206\u5272\u3057\u3066\u9332\u97f3\u3057\u3066\u304f\u3060\u3055\u3044\u3002');
                break;
            }
            if (attempt < MAX_RETRY) {
                status.textContent = '\u4e00\u6642\u30a8\u30e9\u30fc\u3001\u518d\u8a66\u884c\u4e2d(' + attempt + '/' + MAX_RETRY + ')...';
                status.style.color = '#f59e0b';
                await new Promise(r => setTimeout(r, 2000));
            }
        }
    }
    status.textContent = '\u5931\u6557: ' + (lastError ? lastError.message : '\u4e0d\u660e\u306a\u30a8\u30e9\u30fc');
    status.style.color = '#ea4335';
    document.getElementById('ai-btn').style.display = 'flex';
    document.getElementById('ai-loading').style.display = 'none';
}"""

start_idx = html.find(old_js_marker)
end_idx   = html.find(old_js_end)

if start_idx < 0:
    print('STEP2 NG: JS start marker not found')
    sys.exit(1)
elif end_idx < 0:
    print('STEP2 NG: JS end marker not found')
    sys.exit(1)
else:
    end_full = end_idx + len(old_js_end)
    html = html[:start_idx] + new_js + html[end_full:]
    print('STEP2 OK: JS replaced')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)

print('ALL DONE - lines:', html.count('\n'))
print('pause-btn in html:', 'pause-btn' in html)
print('togglePause in html:', 'togglePause' in html)
print('allAudioBlobs in html:', 'allAudioBlobs' in html)
