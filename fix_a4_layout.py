# coding: utf-8
"""
sheetToLayoutにA4/A3スケーリングを追加
列幅合計をA4印刷可能幅(722px)に合わせてスケーリング
"""
path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

OLD = """function sheetToLayout(ws) {
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
      // スタイル構築
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
}"""

NEW = """function sheetToLayout(ws) {
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

  // A4/A3スケーリング計算
  // pageSetupがあればA3(8)かA4(9)か判定、なければA4と仮定
  var ps = ws['!pageSetup'] || {};
  var isA3 = ps.paperSize === 8 || ps.paperSize === 3;
  var isLandscape = ps.orientation === 'landscape';
  // 用紙の印刷可能幅(px) - 余白を引いた値
  // A4縦=722px, A4横=1030px, A3縦=1030px, A3横=1460px
  var paperW = isA3 ? (isLandscape ? 1460 : 1030) : (isLandscape ? 1030 : 722);

  // 全列幅の合計を計算してスケール係数を算出
  var colWidths = [];
  for (var ci = range.s.c; ci <= range.e.c; ci++) {
    var info = ws['!cols'] && ws['!cols'][ci];
    colWidths[ci] = info && info.wpx ? info.wpx : 64;
  }
  var totalW = 0;
  for (var ci = range.s.c; ci <= range.e.c; ci++) totalW += colWidths[ci];
  var scale = totalW > 0 ? paperW / totalW : 1.0;
  // スケールが極端な場合はクランプ
  scale = Math.min(Math.max(scale, 0.5), 3.0);

  var layout = [];
  var maxRow = Math.min(range.e.r, 59);
  var maxCol = range.e.c;

  for (var r = range.s.r; r <= maxRow; r++) {
    var rowInfo = ws['!rows'] && ws['!rows'][r];
    var rowH = rowInfo && rowInfo.hpx ? Math.round(Math.max(rowInfo.hpx * scale, 14)) : null;
    var cells = [];
    var c = range.s.c;
    while (c <= maxCol) {
      var mk = r + '_' + c;
      if (mergeMap[mk] === 'skip') { c++; continue; }
      var addr = XLSX.utils.encode_cell({ r: r, c: c });
      var cell = ws[addr];
      var text = cell ? XLSX.utils.format_cell(cell) : '';
      var colSpan = mergeMap[mk] ? mergeMap[mk].cs : 1;

      // 列幅をスケーリング
      var rawW = colWidths[c] || 64;
      var scaledW = Math.round(Math.max(rawW * scale, 20));

      // スタイル構築
      var style = 'font-size:11px;';
      style += 'min-width:' + scaledW + 'px;max-width:' + scaledW + 'px;width:' + scaledW + 'px;';
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
          if (s.font.sz) {
            var fsize = Math.round(s.font.sz * scale * 0.75); // ptをpxに変換
            fsize = Math.min(Math.max(fsize, 8), 16);
            style += 'font-size:' + fsize + 'px;';
          }
        }
        if (s.alignment) {
          if (s.alignment.horizontal === 'center') style += 'text-align:center;';
          else if (s.alignment.horizontal === 'right') style += 'text-align:right;';
          if (s.alignment.wrapText) style += 'white-space:normal;word-break:break-all;';
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
}"""

if OLD in html:
    html = html.replace(OLD, NEW)
    print('OK: A4/A3 scaling added to sheetToLayout')
else:
    print('NG: pattern not found')
    idx = html.find('function sheetToLayout')
    print('Found at:', idx)

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved! Lines:', html.count('\n'))
