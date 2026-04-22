# coding: utf-8
"""
sheetToLayout関数をA4基準スケーリング対応版に書き換える
"""
path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    lines = f.readlines()

# 953行目(0-indexed:952)から始まるsheetToLayout関数の終わりを探す
start = 952
depth = 0
end = start
for i in range(start, len(lines)):
    depth += lines[i].count('{') - lines[i].count('}')
    if i > start and depth <= 0:
        end = i
        break

print(f'sheetToLayout: lines {start+1} to {end+1}')

NEW_FUNC = """function sheetToLayout(ws) {
  if (!ws['!ref']) return [];
  var range = XLSX.utils.decode_range(ws['!ref']);
  var merges = ws['!merges'] || [];

  // ===== A4/A3基準のスケーリング =====
  // 用紙幅: A4縦=794px A4横=1123px A3縦=1123px A3横=1587px
  var PAGE_W = 794; // デフォルトA4縦
  var ps = ws['!pageSetup'];
  if (ps) {
    if (ps.paperSize == 8 || ps.paperSize == 3) PAGE_W = 1123; // A3
    if (ps.orientation === 'landscape') PAGE_W = PAGE_W === 794 ? 1123 : 1587;
  }
  // 実際の列幅合計を計算（印刷範囲内）
  var cols = ws['!cols'] || [];
  var totalWpx = 0;
  var colWidths = [];
  for (var ci = range.s.c; ci <= range.e.c; ci++) {
    var col = cols[ci];
    var w = col && col.wpx ? col.wpx : (col && col.width ? Math.round(col.width * 7) : 48);
    colWidths.push(w);
    totalWpx += w;
  }
  // スケール係数（印刷範囲が用紙幅に収まるよう）
  var scale = totalWpx > 0 ? Math.min((PAGE_W - 20) / totalWpx, 2.0) : 1.0;

  // マージ情報をマップ化
  var mergeMap = {};
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
  var maxRow = Math.min(range.e.r, 59);

  for (var r = range.s.r; r <= maxRow; r++) {
    var rowInfo = ws['!rows'] && ws['!rows'][r];
    var rowH = rowInfo && rowInfo.hpx ? Math.max(Math.round(rowInfo.hpx * scale), 16) : null;
    var cells = [];
    var c = range.s.c;
    while (c <= range.e.c) {
      var mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }
      var addr = XLSX.utils.encode_cell({ r: r, c: c });
      var cell = ws[addr];
      var text = cell ? XLSX.utils.format_cell(cell) : '';
      var colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;

      // スケーリングした列幅
      var colIdx = c - range.s.c;
      var rawW = colWidths[colIdx] || 48;
      var scaledW = Math.max(Math.round(rawW * scale), 20);

      // スタイル構築
      var style = 'font-size:11px;';
      if (rowH) style += 'height:' + rowH + 'px;vertical-align:middle;';
      style += 'min-width:' + scaledW + 'px;max-width:' + (scaledW * colSpan) + 'px;';

      if (cell && cell.s) {
        var s = cell.s;
        if (s.fill && s.fill.fgColor && s.fill.fgColor.rgb && s.fill.fgColor.rgb.length >= 6) {
          var bg = s.fill.fgColor.rgb.slice(-6);
          if (bg !== 'FFFFFF' && bg !== 'ffffff') style += 'background:#' + bg + ';';
        }
        if (s.font) {
          if (s.font.bold) style += 'font-weight:700;';
          if (s.font.color && s.font.color.rgb && s.font.color.rgb.length >= 6) {
            var fg = s.font.color.rgb.slice(-6);
            if (fg !== '000000') style += 'color:#' + fg + ';';
          }
        }
        if (s.alignment) {
          if (s.alignment.horizontal === 'center') style += 'text-align:center;';
          else if (s.alignment.horizontal === 'right') style += 'text-align:right;';
          if (s.alignment.wrapText) style += 'white-space:pre-wrap;word-break:break-all;';
        }
      }

      cells.push({ c: c - range.s.c + 1, cs: colSpan, text: text, style: style, drop: false });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r - range.s.r + 1, label: String(r + 1), cells: cells });
    }
  }
  return layout;
}
"""

new_lines = lines[:start] + [NEW_FUNC] + lines[end+1:]
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'OK: sheetToLayout replaced with A4-scaling version')
print(f'Was {end-start+1} lines, now {len(NEW_FUNC.splitlines())} lines')
print('Total lines:', len(new_lines))
