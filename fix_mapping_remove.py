# coding: utf-8
"""
mapping.htmlの2つの問題を修正:
1. removeMapping後にカスタムレイアウトのセルがdroppableに戻る
2. sheetToLayoutで行高さ・背景色・罫線も取得してExcelを忠実に再現
"""

path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

# ============================================================
# 1. removeMapping関数を修正
#    buildGrid()で全再描画する代わりに、対象セルだけをdroppableに戻す
# ============================================================
OLD_REMOVE = """function removeMapping(key) {
  const field = mapping[key] ? mapping[key].field : null;
  delete mapping[key];
  buildGrid();
  if (field) markFieldAssigned(field, false);
  updateUI();
}"""

NEW_REMOVE = """function removeMapping(key) {
  const field = mapping[key] ? mapping[key].field : null;
  delete mapping[key];
  // カスタムレイアウトの場合はセルをdroppable状態に戻す
  const isCustom = document.getElementById('sheet-selector').value.startsWith('custom_');
  if (isCustom) {
    // keyに対応するtdを探してdroppableに戻す
    const td = document.querySelector(`#grid-body td[data-key="${key}"]`);
    if (td) {
      td.classList.remove('mapped');
      td.classList.add('droppable');
      td.innerHTML = '<span class="drop-hint">+ クリックまたはドロップ</span>';
      setupInteraction(td);
    } else {
      buildGrid();
    }
  } else {
    buildGrid();
  }
  if (field) markFieldAssigned(field, false);
  updateUI();
}"""

if OLD_REMOVE in html:
    html = html.replace(OLD_REMOVE, NEW_REMOVE)
    print('OK STEP1: removeMapping fixed')
else:
    print('NG STEP1: removeMapping pattern not found')

# ============================================================
# 2. sheetToLayoutで行高さ・背景色・罫線も取得
# ============================================================
OLD_SHEET = """function sheetToLayout(ws) {
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
      // カラム幅をExcelから取得（!cols情報があれば）
      const colInfo = ws['!cols'] && ws['!cols'][c];
      const colWidthPx = colInfo && colInfo.wpx ? Math.max(colInfo.wpx, 30) : null;
      const widthStyle = colWidthPx ? 'min-width:' + colWidthPx + 'px;max-width:' + colWidthPx + 'px;' : '';
      cells.push({ c: c + 1, cs: colSpan, text: text, style: (style || '') + widthStyle, drop: false });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r + 1, label: String(r + 1), cells: cells });
    }
  }
  return layout;
}"""

NEW_SHEET = """function sheetToLayout(ws) {
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
    // 行高さを取得
    var rowInfo = ws['!rows'] && ws['!rows'][r];
    var rowHeightPx = rowInfo && rowInfo.hpx ? Math.max(rowInfo.hpx, 16) : null;
    var cells = [];
    var c = range.s.c;
    while (c <= maxCol) {
      var mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }
      var addr = XLSX.utils.encode_cell({ r: r, c: c });
      var cell = ws[addr];
      var text = cell ? XLSX.utils.format_cell(cell) : '';
      var colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;
      // スタイル構築
      var style = 'font-size:11px;';
      // 行高さ
      if (rowHeightPx) style += 'height:' + rowHeightPx + 'px;';
      // 背景色
      var bgRgb = cell && cell.s && cell.s.fill && cell.s.fill.fgColor && cell.s.fill.fgColor.rgb;
      if (bgRgb && bgRgb !== 'FFFFFF' && bgRgb !== 'ffffff' && bgRgb.length === 6) {
        style += 'background:#' + bgRgb + ';';
      }
      // 太字
      var bold = cell && cell.s && cell.s.font && cell.s.font.bold;
      if (bold) style += 'font-weight:700;';
      // 文字色
      var fgRgb = cell && cell.s && cell.s.font && cell.s.font.color && cell.s.font.color.rgb;
      if (fgRgb && fgRgb !== '000000' && fgRgb !== 'FF000000' && fgRgb.length >= 6) {
        style += 'color:#' + fgRgb.slice(-6) + ';';
      }
      // テキスト寄せ
      var align = cell && cell.s && cell.s.alignment && cell.s.alignment.horizontal;
      if (align === 'center') style += 'text-align:center;';
      else if (align === 'right') style += 'text-align:right;';
      // カラム幅
      var colInfo = ws['!cols'] && ws['!cols'][c];
      var colWidthPx = colInfo && colInfo.wpx ? Math.max(colInfo.wpx, 30) : null;
      if (colWidthPx) style += 'min-width:' + colWidthPx + 'px;max-width:' + colWidthPx + 'px;';
      cells.push({ c: c + 1, cs: colSpan, text: text, style: style, drop: false });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r + 1, label: String(r + 1), cells: cells });
    }
  }
  return layout;
}"""

if OLD_SHEET in html:
    html = html.replace(OLD_SHEET, NEW_SHEET)
    print('OK STEP2: sheetToLayout enhanced with row height/colors/bold/align')
else:
    print('NG STEP2: sheetToLayout pattern not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved! Lines:', html.count('\n'))
