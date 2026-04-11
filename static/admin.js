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
    // 西暦パターン: 1945/3/15, 1945-3-15, 1945.3.15, 19450315
    let m = val.match(/^(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})$/);
    if (m) return fmt(m[1], m[2], m[3]);

    m = val.match(/^(\d{4})(\d{2})(\d{2})$/);
    if (m) return fmt(m[1], m[2], m[3]);

    m = val.match(/^(\d{4})年(\d{1,2})月(\d{1,2})日?$/);
    if (m) return fmt(m[1], m[2], m[3]);

    // 和暦パターン: S20.3.15, H1.1.8, R5.4.1
    m = val.match(/^([RHSTMrHstm令平昭大明])(\d{1,2})[\/\-\.\s年](\d{1,2})[\/\-\.\s月](\d{1,2})日?$/);
    if (m) {
        const key = m[1].toUpperCase();
        const base = WAREKI[key] || WAREKI[m[1]];
        if (base) {
            const year = base[0] + parseInt(m[2]) - 1;
            return fmt(year, m[3], m[4]);
        }
    }

    // 「昭和20年3月15日」形式
    for (const [k, v] of Object.entries(WAREKI)) {
        if (k.length > 1) continue; // 漢字キーはスキップ（別処理）
    }
    m = val.match(/^(令和|平成|昭和|大正|明治)(\d{1,2})年(\d{1,2})月(\d{1,2})日?$/);
    if (m) {
        const eraMap = {'令和': 2019, '平成': 1989, '昭和': 1926, '大正': 1912, '明治': 1868};
        const year = eraMap[m[1]] + parseInt(m[2]) - 1;
        return fmt(year, m[3], m[4]);
    }

    return null;
}

function fmt(y, m, d) {
    const year = parseInt(y), month = parseInt(m), day = parseInt(d);
    if (year < 1868 || year > 2030) return null;
    if (month < 1 || month > 12) return null;
    if (day < 1 || day > 31) return null;
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
    const wareki = toWareki(parseInt(y));
    document.getElementById(textId).value = `${wareki.replace('年','')}年${parseInt(m)}月${parseInt(d)}日`;
    showBirthResult(resultId, `${wareki}　${y}年${parseInt(m)}月${parseInt(d)}日`, 'ok');
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
// ========================================

function switchTab(name, el) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    el.classList.add('active');
}

function toggleAcc(name) {
    const body = document.getElementById('acc-body-' + name);
    const arrow = document.getElementById('acc-arrow-' + name);
    body.classList.toggle('open');
    arrow.classList.toggle('open');
}

async function adminLogin() {
    const pw = document.getElementById('admin-pw').value;
    const res = await fetch('/api/admin_login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ password: pw })
    });
    if ((await res.json()).status === 'success') location.reload();
    else alert('パスワードが違います');
}

async function adminLogout() {
    await fetch('/api/admin_logout', { method: 'POST' });
    location.reload();
}

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

function openEditForm(id) {
    document.getElementById('ef-' + id).style.display = 'block';
}
function closeEditForm(id) {
    document.getElementById('ef-' + id).style.display = 'none';
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
    document.getElementById('modal-title').textContent = `「${name}」を削除しますか？`;
    document.getElementById('delete-modal').style.display = 'flex';
}
function closeModal() {
    deleteTargetId = null;
    document.getElementById('delete-modal').style.display = 'none';
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
    if (!pw) return;
    const res = await fetch('/api/update_password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ password: pw })
    });
    if ((await res.json()).status === 'success') alert('パスワードを更新しました');
}

async function updateHistLimit() {
    const limit = document.getElementById('hist-limit').value;
    await fetch('/api/update_hist_limit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ limit })
    });
    alert('保存しました');
}

async function blockStaff(name) {
    if (!confirm(`「${name}」をブロックしますか？`)) return;
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
    const res = await fetch('/api/unblock_device', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id })
    });
    if ((await res.json()).status === 'success') location.reload();
}

// ========== スタッフ管理 ==========
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