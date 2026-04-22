# coding: utf-8
"""
mapping.htmlにExcelアップロード機能を追加するパッチスクリプト
kaigo-ai-appフォルダで python3 excel_upload_patch.py を実行する
"""
import sys

path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

print('File loaded:', len(html), 'chars')

# ============================================================
# 1. SheetJSをheadに追加
# ============================================================
SHEETJS = '<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>\n'
if 'xlsx' not in html:
    html = html.replace('</head>', SHEETJS + '</head>')
    print('STEP1 OK: SheetJS added')
else:
    print('STEP1 SKIP: SheetJS already present')

# ============================================================
# 2. ツールバーにExcelアップロードボタンを追加
# ============================================================
OLD_TOOLBAR_END = '</div>\n\n  <!-- メインレイアウト'
NEW_TOOLBAR_END = (
    '    <div style="display:flex;align-items:center;gap:8px;margin-left:auto;">\n'
    '      <label id="excel-upload-btn" style="display:inline-flex;align-items:center;gap:6px;\n'
    '             padding:7px 14px;background:#059669;color:#fff;border-radius:8px;\n'
    '             font-size:0.82rem;font-weight:600;cursor:pointer;white-space:nowrap;\n'
    '             border:none;transition:background .2s;" title=".xlsx/.xls/.csvファイルを読み込む">\n'
    '        <span class="material-symbols-outlined" style="font-size:16px">upload_file</span>\n'
    '        Excel\u30fb\u30b7\u30fc\u30c8\u3092\u8aad\u307f\u8fbc\u3080\n'
    '        <input type="file" id="excel-file-input" accept=".xlsx,.xls,.csv"\n'
    '               style="display:none" onchange="handleExcelUpload(event)">\n'
    '      </label>\n'
    '      <span id="excel-status" style="font-size:0.78rem;color:#6b7280;"></span>\n'
    '    </div>\n'
    '</div>\n\n  <!-- \u30e1\u30a4\u30f3\u30ec\u30a4\u30a2\u30a6\u30c8'
)

if OLD_TOOLBAR_END in html:
    html = html.replace(OLD_TOOLBAR_END, NEW_TOOLBAR_END)
    print('STEP2 OK: Upload button added to toolbar')
else:
    # フォールバック: sheet-selectorの直後に追加
    OLD2 = '    </select>\n  </div>'
    NEW2 = (
        '    </select>\n'
        '    <label id="excel-upload-btn" style="display:inline-flex;align-items:center;gap:6px;\n'
        '           padding:7px 14px;background:#059669;color:#fff;border-radius:8px;\n'
        '           font-size:0.82rem;font-weight:600;cursor:pointer;white-space:nowrap;"\n'
        '           title=".xlsx/.xls/.csvファイルを読み込む">\n'
        '      <span class="material-symbols-outlined" style="font-size:16px">upload_file</span>\n'
        '      Excel\u30fb\u30b7\u30fc\u30c8\u3092\u8aad\u307f\u8fbc\u3080\n'
        '      <input type="file" id="excel-file-input" accept=".xlsx,.xls,.csv"\n'
        '             style="display:none" onchange="handleExcelUpload(event)">\n'
        '    </label>\n'
        '    <span id="excel-status" style="font-size:0.78rem;color:#6b7280;"></span>\n'
        '  </div>'
    )
    if OLD2 in html:
        html = html.replace(OLD2, NEW2)
        print('STEP2 OK (fallback): Upload button added after selector')
    else:
        print('STEP2 NG: toolbar insertion point not found')

# ============================================================
# 3. Excelアップロード処理JSをSCRIPT末尾に追加
# ============================================================
EXCEL_JS = '''
// ============================================================
// Excel / CSV \u30a2\u30c3\u30d7\u30ed\u30fc\u30c9\u6a5f\u80fd
// ============================================================
window.handleExcelUpload = async function(event) {
  const file = event.target.files[0];
  if (!file) return;
  const status = document.getElementById('excel-status');
  status.textContent = '\u8aad\u307f\u8fbc\u307f\u4e2d...';
  status.style.color = '#6b7280';

  try {
    const buffer = await file.arrayBuffer();
    let layout;

    if (file.name.endsWith('.csv')) {
      // CSV\u51e6\u7406
      const text = new TextDecoder('utf-8').decode(buffer);
      layout = csvToLayout(text);
    } else {
      // xlsx/xls\u51e6\u7406
      const wb = XLSX.read(buffer, { type: 'array', cellStyles: true, sheetRows: 50 });
      const ws = wb.Sheets[wb.SheetNames[0]];
      layout = sheetToLayout(ws);
    }

    // LAYOUTS\u306b\u8ffd\u52a0\u3057\u3066\u9078\u629e
    const key = 'custom_' + Date.now();
    const label = file.name.replace(/\\.xlsx?|\\.csv$/i, '').slice(0, 20);
    LAYOUTS[key] = layout;

    // \u30bb\u30ec\u30af\u30bf\u30fc\u306b\u30aa\u30d7\u30b7\u30e7\u30f3\u8ffd\u52a0
    const sel = document.getElementById('sheet-selector');
    // \u65e2\u5b58\u306e\u30ab\u30b9\u30bf\u30e0\u30aa\u30d7\u30b7\u30e7\u30f3\u3092\u524a\u9664
    Array.from(sel.options).forEach(o => { if (o.value.startsWith('custom_')) sel.remove(o.index); });
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = '\u2605 ' + label + ' (\u8aad\u307f\u8fbc\u307f)';
    sel.appendChild(opt);
    sel.value = key;

    // \u30b0\u30ea\u30c3\u30c9\u518d\u63cf\u753b
    buildGrid();
    status.textContent = '\u2705 ' + label + ' \u3092\u8aad\u307f\u8fbc\u307f\u307e\u3057\u305f\uff01\u9ec4\u8272\u306b\u3057\u305f\u3044\u30bb\u30eb\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
    status.style.color = '#059669';

    // \u5165\u529b\u3092\u30ea\u30bb\u30c3\u30c8\uff08\u540c\u3058\u30d5\u30a1\u30a4\u30eb\u3092\u518d\u5ea6\u8aad\u307f\u8fbc\u3081\u308b\u3088\u3046\u306b\uff09
    event.target.value = '';
  } catch(e) {
    console.error(e);
    status.textContent = '\u274c \u8aad\u307f\u8fbc\u307f\u5931\u6557: ' + e.message;
    status.style.color = '#dc2626';
  }
};

// xlsx \u30b7\u30fc\u30c8 \u2192 LAYOUTS\u5f62\u5f0f\u306b\u5909\u63db
function sheetToLayout(ws) {
  const ref = ws['!ref'];
  if (!ref) return [];
  const range = XLSX.utils.decode_range(ref);
  const merges = ws['!merges'] || [];
  const layout = [];

  // \u30de\u30fc\u30b8\u60c5\u5831\u3092\u30de\u30c3\u30d7\u5316
  const mergeMap = {};
  merges.forEach(m => {
    for (let r = m.s.r; r <= m.e.r; r++) {
      for (let c = m.s.c; c <= m.e.c; c++) {
        if (r === m.s.r && c === m.s.c) {
          mergeMap[r + '_' + c] = { cs: m.e.c - m.s.c + 1, rs: m.e.r - m.s.r + 1 };
        } else {
          mergeMap[r + '_' + c] = 'skip';
        }
      }
    }
  });

  const maxRow = Math.min(range.e.r, 49);
  const maxCol = Math.min(range.e.c, 20);

  for (let r = range.s.r; r <= maxRow; r++) {
    const cells = [];
    let c = range.s.c;
    while (c <= maxCol) {
      const mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }

      const addr = XLSX.utils.encode_cell({ r, c });
      const cell = ws[addr];
      const text = cell ? XLSX.utils.format_cell(cell) : '';
      const colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;

      // \u30bb\u30eb\u306e\u30b9\u30bf\u30a4\u30eb\u5224\u5b9a
      const isBold = cell && cell.s && cell.s.font && cell.s.font.bold;
      const bgColor = cell && cell.s && cell.s.fill && cell.s.fill.fgColor && cell.s.fill.fgColor.rgb;

      let style = '';
      if (isBold) style += 'font-weight:600;';
      if (bgColor && bgColor !== 'FFFFFF' && bgColor !== 'ffffff') {
        style += 'background:#' + bgColor + ';';
      }
      if (text) style += 'font-size:11px;';

      cells.push({
        c: c + 1,       // 1-indexed
        cs: colSpan,
        text: text,
        style: style || undefined,
        drop: false      // \u521d\u671f\u306f\u5168\u30bb\u30eb\u975edrop\u3001\u30af\u30ea\u30c3\u30af\u3067toggle
      });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r + 1, label: String(r + 1), cells });
    }
  }
  return layout;
}

// CSV \u2192 LAYOUTS\u5f62\u5f0f\u306b\u5909\u63db
function csvToLayout(text) {
  const rows = text.split('\n').filter(r => r.trim()).slice(0, 40);
  return rows.map((row, ri) => {
    const vals = row.split(',');
    const cells = vals.slice(0, 15).map((v, ci) => ({
      c: ci + 1,
      cs: 1,
      text: v.trim().replace(/^"|"$/g, ''),
      drop: false
    }));
    return { r: ri + 1, label: String(ri + 1), cells };
  });
}
'''

# </script>の直前に追加
if 'handleExcelUpload' not in html:
    # 最後の</script>の前に挿入
    last_script = html.rfind('</script>')
    if last_script >= 0:
        html = html[:last_script] + EXCEL_JS + '\n' + html[last_script:]
        print('STEP3 OK: Excel upload JS added')
    else:
        print('STEP3 NG: </script> not found')
else:
    print('STEP3 SKIP: handleExcelUpload already present')

# ============================================================
# 4. buildGrid()でカスタムレイアウトのセルをクリックでdrop切替
# ============================================================
# セルクリック時にdropをトグルする処理を追加
OLD_DROP_CLICK = "if (cell.drop) {"
NEW_DROP_CLICK = (
    "// \u30ab\u30b9\u30bf\u30e0\u8aad\u307f\u8fbc\u307f\u6642\u306f\u30af\u30ea\u30c3\u30af\u3067drop\u3092\u30c8\u30b0\u30eb\n"
    "      const isCustomLayout = document.getElementById('sheet-selector').value.startsWith('custom_');\n"
    "      if (isCustomLayout && !cell.drop && !cell.text.match(/^\\s*$/) || cell.drop) {\n"
    "        td.style.cursor = 'pointer';\n"
    "        td.addEventListener('click', function(e) {\n"
    "          if (isCustomLayout && !window._selectedField) {\n"
    "            // \u30c8\u30b0\u30eb\u30e2\u30fc\u30c9: \u30d5\u30a3\u30fc\u30eb\u30c9\u9078\u629e\u524d\u306f\u30bb\u30eb\u3092\u9ec4\u8272\u306b\u30c8\u30b0\u30eb\n"
    "            cell.drop = !cell.drop;\n"
    "            td.style.background = cell.drop ? '#fef9c3' : '';\n"
    "            td.style.outline = cell.drop ? '2px dashed #f59e0b' : '';\n"
    "            const addr2 = getCellAddr(cell.c, row.label);\n"
    "            td.title = cell.drop ? addr2 + ' \uff08\u30de\u30c3\u30d4\u30f3\u30b0\u5bfe\u8c61\uff09' : '';\n"
    "            return;\n"
    "          }\n"
    "        });\n"
    "      }\n"
    "      if (cell.drop) {"
)

if OLD_DROP_CLICK in html and NEW_DROP_CLICK not in html:
    html = html.replace(OLD_DROP_CLICK, NEW_DROP_CLICK, 1)
    print('STEP4 OK: Click-to-toggle drop added')
else:
    print('STEP4 SKIP or NG')

# ============================================================
# 保存
# ============================================================
with open(path, 'w', encoding='utf-8') as f:
    f.write(html)

print('\nAll done! File saved:', path)
print('Lines:', html.count('\n'))
print('\n--- 次のステップ ---')
print('1. git add static/mapping.html')
print('2. git commit -m "feat: Excelアップロードで書式を取り込む機能を追加"')
print('3. git push origin tasukaru-dev')
print('4. gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --project tasukaru-production --quiet')
