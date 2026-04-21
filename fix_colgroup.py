# coding: utf-8
"""
buildGrid()にcolgroup動的更新を追加して列幅をExcelから反映させる
"""
path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

# buildGrid()の先頭に列幅更新処理を追加
OLD = """function buildGrid() {
  const tbody = document.getElementById('grid-body');
  tbody.innerHTML = '';
  const layout = LAYOUTS[document.getElementById('sheet-selector').value] || LAYOUTS.monitoring;"""

NEW = """function buildGrid() {
  const tbody = document.getElementById('grid-body');
  tbody.innerHTML = '';
  const layout = LAYOUTS[document.getElementById('sheet-selector').value] || LAYOUTS.monitoring;

  // colgroupを動的に再構築（Excelの列幅を反映）
  const table = document.getElementById('sheet-grid');
  const isCustom = document.getElementById('sheet-selector').value.startsWith('custom_');
  if (isCustom && layout.length > 0) {
    // 全セルから最大列数と各列幅を計算
    const colWidths = {};
    layout.forEach(function(row) {
      row.cells.forEach(function(cell) {
        if (cell.cs === 1) {
          // 単一セルの場合のみ列幅を取得
          var w = null;
          if (cell.style) {
            var m = cell.style.match(/min-width:(\d+)px/);
            if (m) w = parseInt(m[1]);
          }
          if (w && !colWidths[cell.c]) colWidths[cell.c] = w;
        }
      });
    });
    // 最大列番号を算出
    var maxCol = 1;
    layout.forEach(function(row) {
      row.cells.forEach(function(cell) {
        maxCol = Math.max(maxCol, cell.c + (cell.cs || 1) - 1);
      });
    });
    // colgroupを再構築
    var cg = table.querySelector('colgroup');
    if (cg) {
      cg.innerHTML = '<col style="width:28px">'; // 行番号列
      for (var ci = 1; ci <= maxCol; ci++) {
        var w = colWidths[ci] || 48;
        cg.innerHTML += '<col style="width:' + w + 'px">';
      }
    }
    // テーブル幅をコンテンツに合わせる
    var totalW = 28;
    for (var ci = 1; ci <= maxCol; ci++) totalW += colWidths[ci] || 48;
    table.style.width = Math.max(totalW, 600) + 'px';
    table.style.tableLayout = 'fixed';
  } else {
    // 通常テンプレートは元のcolgroupに戻す
    table.style.width = '100%';
  }"""

if OLD in html:
    html = html.replace(OLD, NEW)
    print('OK: colgroup dynamic update added to buildGrid()')
else:
    print('NG: buildGrid pattern not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved! Lines:', html.count('\n'))
