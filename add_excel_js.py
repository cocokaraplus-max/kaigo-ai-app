# coding: utf-8
"""
mapping.htmlにExcel/CSVアップロードのJSを追加する
kaigo-ai-appフォルダで python3 add_excel_js.py を実行
"""

path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

print('Before:', html.count('handleExcelUpload'), 'handleExcelUpload occurrences')

# </script>の直前（最後の</script>の手前）に挿入
NEW_JS = """
// ============================================================
// Excel / CSV アップロード機能
// ============================================================
window.handleExcelUpload = async function(event) {
  const file = event.target.files[0];
  if (!file) return;
  const status = document.getElementById('excel-status');
  status.textContent = '読み込み中...';
  status.style.color = '#6b7280';
  try {
    const buffer = await file.arrayBuffer();
    let layout;
    if (file.name.toLowerCase().endsWith('.csv')) {
      const text = new TextDecoder('utf-8').decode(buffer);
      layout = csvToLayout(text);
    } else {
      const wb = XLSX.read(buffer, { type: 'array', sheetRows: 50 });
      const ws = wb.Sheets[wb.SheetNames[0]];
      layout = sheetToLayout(ws);
    }
    const key = 'custom_' + Date.now();
    const label = file.name.replace(/\\.xlsx?|\\.csv$/i, '').slice(0, 20);
    LAYOUTS[key] = layout;
    const sel = document.getElementById('sheet-selector');
    Array.from(sel.options).forEach(function(o) {
      if (o.value.startsWith('custom_')) sel.remove(o.index);
    });
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = '\u2605 ' + label + ' (\u8aad\u307f\u8fbc\u307f)';
    sel.appendChild(opt);
    sel.value = key;
    buildGrid();
    status.textContent = '\u2705 ' + label + ' \u3092\u8aad\u307f\u8fbc\u307f\u307e\u3057\u305f\uff01\u30de\u30c3\u30d4\u30f3\u30b0\u3057\u305f\u3044\u30bb\u30eb\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u304f\u3060\u3055\u3044\u3002';
    status.style.color = '#059669';
    event.target.value = '';
  } catch(e) {
    console.error(e);
    status.textContent = '\u274c \u8aad\u307f\u8fbc\u307f\u5931\u6557: ' + e.message;
    status.style.color = '#dc2626';
  }
};

function sheetToLayout(ws) {
  if (!ws['!ref']) return [];
  const range = XLSX.utils.decode_range(ws['!ref']);
  const merges = ws['!merges'] || [];
  const mergeMap = {};
  merges.forEach(function(m) {
    for (var r = m.s.r; r <= m.e.r; r++) {
      for (var c = m.s.c; c <= m.e.c; c++) {
        if (r === m.s.r && c === m.s.c) {
          mergeMap[r + '_' + c] = { cs: m.e.c - m.s.c + 1 };
        } else {
          mergeMap[r + '_' + c] = 'skip';
        }
      }
    }
  });
  var layout = [];
  var maxRow = Math.min(range.e.r, 49);
  var maxCol = Math.min(range.e.c, 25);
  for (var r = range.s.r; r <= maxRow; r++) {
    var cells = [];
    var c = range.s.c;
    while (c <= maxCol) {
      var mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }
      var addr = XLSX.utils.encode_cell({ r: r, c: c });
      var cell = ws[addr];
      var text = cell ? XLSX.utils.format_cell(cell) : '';
      var colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;
      var style = text ? 'font-size:11px;' : '';
      cells.push({ c: c + 1, cs: colSpan, text: text, style: style, drop: false });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r + 1, label: String(r + 1), cells: cells });
    }
  }
  return layout;
}

function csvToLayout(text) {
  var rows = text.split('\\n').filter(function(r) { return r.trim(); }).slice(0, 40);
  return rows.map(function(row, ri) {
    var vals = row.split(',');
    var cells = vals.slice(0, 15).map(function(v, ci) {
      return { c: ci + 1, cs: 1, text: v.trim().replace(/^"|"$/g, ''), drop: false };
    });
    return { r: ri + 1, label: String(ri + 1), cells: cells };
  });
}
"""

# </script>の直前に挿入
last_script_close = html.rfind('</script>')
if last_script_close >= 0:
    html = html[:last_script_close] + NEW_JS + '\n</script>' + html[last_script_close + len('</script>'):]
    print('JS inserted before </script> at index', last_script_close)
else:
    print('ERROR: </script> not found')

print('After:', html.count('handleExcelUpload'), 'handleExcelUpload occurrences')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved! Lines:', html.count('\n'))
