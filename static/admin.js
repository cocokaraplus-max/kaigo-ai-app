// ========== 誕生日入力パース ==========
const WAREKI = {
    'R': [2019, '令和'], '令': [2019, '令和'],
    'H': [1989, '平成'], '平': [1989, '平成'],
    'S': [1926, '昭和'], '昭': [1926, '昭和'],
    'T': [1912, '大正'], '大': [1912, '大正'],
    'M': [1868, '明治'], '明': [1868, '明治'],
};

function parseBirthInput(val, dateId, resultId) {
    if (!val.trim()) {
        showBirthResult(resultId, '', '');
        document.getElementById(dateId).value = '';
        return;
    }
    const iso = parseBirthToISO(val.trim());
    if (iso) {
        document.getElementById(dateId).value = iso;
        const [y, m, d] = iso.split('-');
        const wareki = toWareki(parseInt(y));
        showBirthResult(resultId, `${wareki}　${y}年${parseInt(m)}月${parseInt(d)}日`, 'ok');
    } else {
        document.getElementById(dateId).value = '';
        showBirthResult(resultId, '形式を確認してください（例：S20.3.15 / 昭和20年3月15日 / 1945/3/15）', 'err');
    }
}

function parseBirthToISO(val) {
    let m = val.match(/^(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})$/);
    if (m) return fmt(m[1], m[2], m[3]);
    m = val.match(/^(\d{4})(\d{2})(\d{2})$/);
    if (m) return fmt(m[1], m[2], m[3]);
    m = val.match(/^(\d{4})年(\d{1,2})月(\d{1,2})日?$/);
    if (m) return fmt(m[1], m[2], m[3]);
    m = val.match(/^([RHSTMrHstm令平昭大明])(\d{1,2})[\/\-\.\s年](\d{1,2})[\/\-\.\s月](\d{1,2})日?$/);
    if (m) {
        const key = m[1].toUpperCase();
        const base = WAREKI[key] || WAREKI[m[1]];
        if (base) return fmt(base[0] + parseInt(m[2]) - 1, m[3], m[4]);
    }
    m = val.match(/^(令和|平成|昭和|大正|明治)(\d{1,2})年(\d{1,2})月(\d{1,2})日?$/);
    if (m) {
        const eraMap = {'令和': 2019, '平成': 1989, '昭和': 1926, '大正': 1912, '明治': 1868};
        return fmt(eraMap[m[1]] + parseInt(m[2]) - 1, m[3], m[4]);
    }
    return null;
}

function fmt(y, m, d) {
    const year = parseInt(y), month = parseInt(m), day = parseInt(d);
    if (year < 1868 || year > 2030 || month < 1 || month > 12 || day < 1 || day > 31) return null;
    return `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
}

function toWareki(year) {
    if (year >= 2019) return `令和${year - 2018}年`;
    if (year >= 1989) return `平成${year - 1988}年`;
    if (year >= 1926) return `昭和${year - 1925}年`;
    if (year >= 1912) return `大正${year - 1911}年`;
    if (year >= 1868) return `明治${year - 1867}年`;
    return `${year}年`;
}

function syncDateToText(isoVal, textId, resultId) {
    if (!isoVal) { showBirthResult(resultId, '', ''); return; }
    const [y, m, d] = isoVal.split('-');
    document.getElementById(textId).value = `${toWareki(parseInt(y)).replace('年','')}年${parseInt(m)}月${parseInt(d)}日`;
    showBirthResult(resultId, `${toWareki(parseInt(y))}　${y}年${parseInt(m)}月${parseInt(d)}日`, 'ok');
}

function showBirthResult(id, msg, type) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = 'birth-result' + (type ? ' ' + type : '');
}

function getBirthValue(dateId) {
    return document.getElementById(dateId)?.value || '';
}

// ========== タブ・アコーディオン ==========
function switchTab(name, el) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    el.classList.add('active');
}

function toggleAcc(name) {
    const body = document.getElementById('acc-body-' + name);
    const arrow = document.getElementById('acc-arrow-' + name);
    if (!body) return;
    const isOpen = body.style.display !== 'none' && body.style.display !== '';
    body.style.display = isOpen ? 'none' : 'block';
    if (arrow) arrow.style.transform = isOpen ? '' : 'rotate(180deg)';
}

function openEditForm(id) {
    document.getElementById('ef-' + id).style.display = 'block';
}

function closeEditForm(id) {
    document.getElementById('ef-' + id).style.display = 'none';
}

// ========== 利用者管理 ==========
async function addPatient() {
    const chart = document.getElementById('new-chart').value.trim();
    const name  = document.getElementById('new-name').value.trim();
    const kana  = document.getElementById('new-kana').value.trim();
    const birth = getBirthValue('new-birth-date');
    if (!chart || !name) { alert('カルテNoと氏名は必須です'); return; }
    const res = await fetch('/api/add_patient', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ chart, name, kana, birth })
    });
    if ((await res.json()).status === 'success') location.reload();
}

async function savePatientEdit(id) {
    const chart = document.getElementById('ef-chart-' + id).value.trim();
    const name  = document.getElementById('ef-name-' + id).value.trim();
    const kana  = document.getElementById('ef-kana-' + id).value.trim();
    const birth = getBirthValue('ef-birth-date-' + id);
    const res = await fetch('/api/update_patient', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id, chart, name, kana, birth })
    });
    if ((await res.json()).status === 'success') location.reload();
    else alert('更新に失敗しました');
}

let deleteTargetId = null;
function confirmDelete(id, name) {
    deleteTargetId = id;
    document.getElementById('modal-patient-name').textContent = name;
    document.getElementById('delete-modal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('delete-modal').style.display = 'none';
    deleteTargetId = null;
}

async function executeDelete() {
    if (!deleteTargetId) return;
    const res = await fetch('/api/delete_patient', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id: deleteTargetId })
    });
    if ((await res.json()).status === 'success') { closeModal(); location.reload(); }
}

// ========== 設定 ==========
async function issueClaude() {
    const res = await fetch('/api/issue_claude_session', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (data.status === 'success') {
        const url = `${window.location.origin}/claude_view?token=${data.token}`;
        document.getElementById('claude-url-text').textContent = url;
        document.getElementById('claude-url-result').style.display = 'block';
    } else {
        alert('発行に失敗しました');
    }
}

function copyClaudeUrl() {
    const text = document.getElementById('claude-url-text').textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = event.target.closest('button');
        btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;">check</span> コピーしました';
        setTimeout(() => {
            btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;">content_copy</span> コピー';
        }, 2000);
    });
}

async function updatePassword() {
    const pw = document.getElementById('new-pw').value;
    if (!pw) { alert('パスワードを入力してください'); return; }
    const res = await fetch('/api/update_password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ password: pw })
    });
    if ((await res.json()).status === 'success') {
        alert('パスワードを更新しました');
        document.getElementById('new-pw').value = '';
    }
}

async function updateHistLimit() {
    const limit = document.getElementById('hist-limit').value;
    const res = await fetch('/api/update_hist_limit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ limit: parseInt(limit) })
    });
    if ((await res.json()).status === 'success') alert('保存しました');
}

// ========== スタッフ管理 ==========
async function blockStaff(name) {
    if (!confirm(`${name} をブロックしますか？`)) return;
    const res = await fetch('/api/block_staff', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name })
    });
    if ((await res.json()).status === 'success') location.reload();
}

function toggleStaffBirth(idx, name, currentBirth) {
    const el = document.getElementById('sbf-' + idx);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function saveStaffBirth(name, idx) {
    const birth = document.getElementById('sbf-date-' + idx).value;
    const res = await fetch('/api/update_staff_birth', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name, birth })
    });
    if ((await res.json()).status === 'success') location.reload();
    else alert('保存に失敗しました');
}

async function unblockDevice(id) {
    const res = await fetch('/api/unblock_device', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id })
    });
    if ((await res.json()).status === 'success') location.reload();
}

// ========== 職員招待 ==========
async function addStaff() {
    const name = document.getElementById('new-staff-name').value.trim();
    const pw = document.getElementById('new-staff-pw').value;
    const pw2 = document.getElementById('new-staff-pw2').value;
    const errEl = document.getElementById('new-staff-error');
    const errMsg = document.getElementById('new-staff-error-msg');

    const showErr = (msg) => {
        errMsg.textContent = msg;
        errEl.style.display = 'flex';
    };

    errEl.style.display = 'none';
    if (!name) return showErr('スタッフ名を入力してください');
    if (!pw) return showErr('パスワードを入力してください');
    if (pw.length < 4) return showErr('パスワードは4文字以上にしてください');
    if (pw !== pw2) return showErr('パスワードが一致しません');

    const res = await fetch('/api/add_staff', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name, password: pw })
    });
    const data = await res.json();
    if (data.status === 'success') {
        location.reload();
    } else {
        showErr(data.message || '登録に失敗しました');
    }
}

async function deleteStaff(id, name) {
    if (!confirm(`${name} を削除しますか？\nこの操作は取り消せません。`)) return;
    const res = await fetch('/api/delete_staff', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id })
    });
    if ((await res.json()).status === 'success') location.reload();
    else alert('削除に失敗しました');
}

// ========== 招待QRコード ==========
async function issueInviteQR() {
    const res = await fetch('/api/issue_invite', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();
    if (data.status !== 'success') { alert('発行に失敗しました'); return; }

    const url = window.location.origin + '/invite?token=' + data.token;
    document.getElementById('invite-url-text').textContent = url;
    document.getElementById('invite-qr-area').style.display = 'block';

    const qrEl = document.getElementById('invite-qr-code');
    qrEl.innerHTML = '';
    if (typeof QRCode === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
        script.onload = () => generateQR(qrEl, url);
        document.head.appendChild(script);
    } else {
        generateQR(qrEl, url);
    }
}

function generateQR(el, url) {
    new QRCode(el, {
        text: url,
        width: 200,
        height: 200,
        colorDark: '#202124',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
    });
}
// ========== 管理者ログアウト ==========
async function adminLogout() {
    await fetch('/api/admin_logout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    });
    location.reload();
}

// ========== パスワード表示切り替え ==========
function togglePw(inputId, iconId) {
    const input = document.getElementById(inputId);
    const icon  = document.getElementById(iconId);
    if (!input || !icon) return;
    if (input.type === 'password') {
        input.type = 'text';
        icon.textContent = 'visibility_off';
    } else {
        input.type = 'password';
        icon.textContent = 'visibility';
    }
}

// ========== 写真から利用者一括読み取り ==========
let scanImageData = null;

window.onScanDrop = function(e) {
    e.preventDefault();
    document.getElementById('scan-drop-zone').style.background = '#fff';
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) loadScanImage(file);
};

window.onScanFileSelect = function(input) {
    const file = input.files[0];
    if (file) loadScanImage(file);
};

function loadScanImage(file) {
    const reader = new FileReader();
    reader.onload = e => {
        scanImageData = e.target.result;
        document.getElementById('scan-preview-img').src = scanImageData;
        document.getElementById('scan-preview').style.display = 'block';
        document.getElementById('scan-btn').style.display = 'block';
        document.getElementById('scan-results').style.display = 'none';
    };
    reader.readAsDataURL(file);
}

window.scanPatients = async function() {
    if (!scanImageData) return;
    document.getElementById('scan-btn').style.display = 'none';
    document.getElementById('scan-loading').style.display = 'block';
    document.getElementById('scan-results').style.display = 'none';

    try {
        // base64データを取得（data:image/...;base64, の後ろ）
        const base64 = scanImageData.split(',')[1];
        const mimeType = scanImageData.split(';')[0].split(':')[1];

        const res = await fetch('/api/scan_patients_from_image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: base64, mime_type: mimeType })
        });
        const data = await res.json();

        if (data.status === 'success' && data.patients.length > 0) {
            renderScanResults(data.patients);
        } else {
            alert('利用者情報を読み取れませんでした。\n別の写真でお試しください。\n\n' + (data.message || ''));
            document.getElementById('scan-btn').style.display = 'block';
        }
    } catch(e) {
        alert('エラーが発生しました: ' + e.message);
        document.getElementById('scan-btn').style.display = 'block';
    } finally {
        document.getElementById('scan-loading').style.display = 'none';
    }
};

function renderScanResults(patients) {
    const list = document.getElementById('scan-results-list');
    const DAYS = ['月','火','水','木','金','土','日'];
    list.innerHTML = '';

    // 件数表示
    const countEl = document.createElement('div');
    countEl.style.cssText = 'font-size:0.82rem;color:#34a853;font-weight:700;margin-bottom:8px;';
    countEl.textContent = `✅ ${patients.length}名を読み取りました。内容を確認・修正してから登録してください。`;
    list.appendChild(countEl);

    patients.forEach((p, i) => {
        const div = document.createElement('div');
        div.style.cssText = 'background:#fff;border:1.5px solid #e0e0e0;border-radius:10px;padding:12px;margin-bottom:8px;';

        // 利用曜日チェックボックス
        const dayChecks = DAYS.map((d, di) => {
            const dayVal = String(di + 1 === 7 ? 0 : di + 1); // 月=1...土=6,日=0
            const checked = (p.weekdays || '').includes(dayVal) ? 'checked' : '';
            return `<label style="display:flex;align-items:center;gap:2px;font-size:0.75rem;font-weight:700;cursor:pointer;">
                <input type="checkbox" name="scan-day-${i}" value="${dayVal}" ${checked} style="accent-color:#1a73e8;">
                <span style="color:${d==='日'?'#c62828':d==='土'?'#2e7d32':'#202124'}">${d}</span>
            </label>`;
        }).join('');

        div.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <input type="checkbox" id="scan-check-${i}" checked style="accent-color:#1a73e8;width:16px;height:16px;">
                <span style="font-size:0.82rem;font-weight:700;color:#34a853;">読み取り結果 ${i+1}</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
                <div>
                    <label style="font-size:0.72rem;color:#5f6368;font-weight:700;">氏名</label>
                    <input type="text" class="form-control" id="scan-name-${i}" value="${p.name||''}" placeholder="氏名">
                </div>
                <div>
                    <label style="font-size:0.72rem;color:#5f6368;font-weight:700;">かな</label>
                    <input type="text" class="form-control" id="scan-kana-${i}" value="${p.kana||''}" placeholder="かな">
                </div>
                <div>
                    <label style="font-size:0.72rem;color:#5f6368;font-weight:700;">生年月日</label>
                    <input type="date" class="form-control" id="scan-birth-${i}" value="${p.birth_date||''}">
                </div>
                <div>
                    <label style="font-size:0.72rem;color:#5f6368;font-weight:700;">カルテNo</label>
                    <input type="text" class="form-control" id="scan-chart-${i}" value="${p.chart||''}" placeholder="自動採番">
                </div>
            </div>
            <div style="margin-bottom:8px;">
                <label style="font-size:0.72rem;color:#5f6368;font-weight:700;display:block;margin-bottom:4px;">利用曜日</label>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">${dayChecks}</div>
            </div>
            <div>
                <label style="font-size:0.72rem;color:#5f6368;font-weight:700;display:block;margin-bottom:4px;">利用時間</label>
                <div style="display:flex;gap:8px;">
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer;">
                        <input type="radio" name="scan-ampm-${i}" value="AM" ${p.ampm==='AM'?'checked':''} style="accent-color:#1a73e8;">
                        🌅 午前（AM）
                    </label>
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer;">
                        <input type="radio" name="scan-ampm-${i}" value="PM" ${p.ampm==='PM'?'checked':''} style="accent-color:#1a73e8;">
                        🌇 午後（PM）
                    </label>
                    <label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer;">
                        <input type="radio" name="scan-ampm-${i}" value="BOTH" ${(!p.ampm||p.ampm==='BOTH')?'checked':''} style="accent-color:#1a73e8;">
                        全日
                    </label>
                </div>
            </div>
        `;
        list.appendChild(div);
    });
    document.getElementById('scan-results').style.display = 'block';
}

window.registerScannedPatients = async function() {
    const items = document.querySelectorAll('[id^="scan-check-"]');
    const toRegister = [];
    items.forEach((cb, i) => {
        if (cb.checked) {
            // 利用曜日
            const days = [...document.querySelectorAll(`input[name="scan-day-${i}"]:checked`)].map(el => el.value).join('');
            // AM/PM
            const ampmEl = document.querySelector(`input[name="scan-ampm-${i}"]:checked`);
            const ampm = ampmEl ? ampmEl.value : 'BOTH';
            toRegister.push({
                name:       document.getElementById(`scan-name-${i}`).value.trim(),
                kana:       document.getElementById(`scan-kana-${i}`).value.trim(),
                birth_date: document.getElementById(`scan-birth-${i}`).value,
                chart:      document.getElementById(`scan-chart-${i}`).value.trim(),
                weekdays:   days,
                ampm:       ampm,
            });
        }
    });

    if (!toRegister.length) { alert('登録する利用者を選択してください'); return; }
    const valid = toRegister.filter(p => p.name);
    if (!valid.length) { alert('氏名が入力されていません'); return; }
    if (!confirm(`${valid.length}名を登録します。よろしいですか？`)) return;

    const res = await fetch('/api/bulk_register_patients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patients: valid })
    });
    const data = await res.json();
    if (data.status === 'success') {
        alert(`✅ ${data.count}名を登録しました！`);
        location.reload();
    } else {
        alert('登録に失敗しました: ' + (data.message || ''));
    }
};
