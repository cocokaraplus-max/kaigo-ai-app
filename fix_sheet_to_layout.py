# coding: utf-8
"""
sheetToLayout関数を強化版に置き換える
行高さ・背景色・太字・文字色・テキスト寄せを取得してExcelを忠実に再現
"""

path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    lines = f.readlines()

# 908行目(0-indexed:907)から始まるsheetToLayout関数の終わりを探す
start = 907
depth = 0
end = start
for i in range(start, len(lines)):
    depth += lines[i].count('{') - lines[i].count('}')
    if i > start and depth <= 0:
        end = i
        break

print(f'sheetToLayout: lines {start+1} to {end+1}')

# 新しい関数
new_func = """function sheetToLayout(ws) {
  if (!ws['!ref']) return [];
  var range = XLSX.utils.decode_range(ws['!ref']);
  var merges = ws['!merges'] || [];
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
  var maxRow = Math.min(range.e.r, 49);
  var maxCol = Math.min(range.e.c, 25);
  for (var r = range.s.r; r <= maxRow; r++) {
    var rowInfo = ws['!rows'] && ws['!rows'][r];
    var rowH = rowInfo && rowInfo.hpx ? Math.max(rowInfo.hpx, 16) : null;
    var cells = [];
    var c = range.s.c;
    while (c <= maxCol) {
      var mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }
      var addr = XLSX.utils.encode_cell({ r: r, c: c });
      var cell = ws[addr];
      var text = cell ? XLSX.utils.format_cell(cell) : '';
      var colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;
      var style = 'font-size:11px;';
      if (rowH) style += 'height:' + rowH + 'px;vertical-align:middle;';
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
        }
      }
      var colInfo = ws['!cols'] && ws['!cols'][c];
      var colW = colInfo && colInfo.wpx ? Math.max(colInfo.wpx, 30) : null;
      if (colW) style += 'min-width:' + colW + 'px;max-width:' + colW + 'px;';
      cells.push({ c: c + 1, cs: colSpan, text: text, style: style, drop: false });
      c += colSpan;
    }
    if (cells.length > 0) {
      layout.push({ r: r + 1, label: String(r + 1), cells: cells });
    }
  }
  return layout;
}
"""

# 置き換え
new_lines = lines[:start] + [new_func] + lines[end+1:]
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'OK: sheetToLayout replaced (was {end-start+1} lines, now {len(new_func.splitlines())} lines)')
print('Total lines:', len(new_lines))
