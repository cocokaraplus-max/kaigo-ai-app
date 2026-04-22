# coding: utf-8
"""
mapping.htmlのbuildGrid関数を修正:
1. カスタムレイアウト時にセルをクリックで黄色/ドロップ対象に切り替え
2. セル内のテキストをダブルクリックで直接編集できる
3. カラム幅をExcelから取得して反映
kaigo-ai-appフォルダで python3 fix_custom_layout.py を実行
"""

path = 'static/mapping.html'
with open(path, encoding='utf-8') as f:
    html = f.read()

# ============================================================
# buildGrid内の「else { td.textContent = cell.text || ''; }」を拡張
# カスタムレイアウト時はクリックでdroppableトグル + ダブルクリックで編集
# ============================================================
OLD = """      } else {
        td.textContent = cell.text || '';
      }
      tr.appendChild(td);"""

NEW = """      } else {
        td.textContent = cell.text || '';
        // カスタムレイアウト: クリックでdroppable切替 / ダブルクリックで編集
        const isCustom = document.getElementById('sheet-selector').value.startsWith('custom_');
        if (isCustom) {
          td.style.cursor = 'pointer';
          // シングルクリック: droppable切替
          td.addEventListener('click', function(e) {
            if (e.detail === 2) return; // ダブルクリックは別処理
            if (selectedField) {
              // フィールド選択中ならそのままマッピング
              cell.drop = true;
              cell.key = cell.key || ('custom_' + row.label + '_' + cell.c);
              td.dataset.key = cell.key;
              td.classList.add('droppable');
              td.innerHTML = '<span class="drop-hint">+ クリックまたはドロップ</span>';
              setupInteraction(td);
              applyMapping(cell.key, td, selectedField);
              clearSelection();
            } else {
              // フィールド未選択: 黄色切替
              if (td.classList.contains('droppable')) {
                td.classList.remove('droppable');
                cell.drop = false;
                td.textContent = cell.text || '';
                td.style.background = '';
                td.style.outline = '';
              } else {
                cell.drop = true;
                cell.key = cell.key || ('custom_' + row.label + '_' + cell.c);
                td.dataset.key = cell.key;
                td.classList.add('droppable');
                td.innerHTML = '<span class="drop-hint">+ クリックまたはドロップ</span>';
                setupInteraction(td);
              }
            }
          });
          // ダブルクリック: テキスト直接編集
          td.addEventListener('dblclick', function(e) {
            e.stopPropagation();
            const current = cell.text || '';
            const input = document.createElement('input');
            input.type = 'text';
            input.value = current;
            input.style.cssText = 'width:100%;border:none;outline:2px solid #2563eb;font-size:inherit;padding:2px;box-sizing:border-box;background:#eff6ff;';
            td.innerHTML = '';
            td.appendChild(input);
            input.focus();
            input.select();
            function finishEdit() {
              cell.text = input.value;
              td.textContent = cell.text;
              td.style.cursor = 'pointer';
            }
            input.addEventListener('blur', finishEdit);
            input.addEventListener('keydown', function(e) {
              if (e.key === 'Enter') { input.blur(); }
              if (e.key === 'Escape') { input.value = current; input.blur(); }
            });
          });
        }
      }
      tr.appendChild(td);"""

if OLD in html:
    html = html.replace(OLD, NEW)
    print('OK: buildGrid custom cell handling added')
else:
    print('NG: OLD pattern not found')
    # フォールバック検索
    idx = html.find("td.textContent = cell.text || '';")
    print('td.textContent found at:', idx)

# ============================================================
# sheetToLayoutでExcelのカラム幅を取得
# ============================================================
OLD_SHEET = "    cells.push({ c: c + 1, cs: colSpan, text: text, style: style, drop: false });"
NEW_SHEET = """    // カラム幅をExcelから取得（!cols情報があれば）
    const colInfo = ws['!cols'] && ws['!cols'][c];
    const colWidthPx = colInfo && colInfo.wpx ? Math.max(colInfo.wpx, 30) : null;
    const widthStyle = colWidthPx ? 'min-width:' + colWidthPx + 'px;max-width:' + colWidthPx + 'px;' : '';
    cells.push({ c: c + 1, cs: colSpan, text: text, style: (style || '') + widthStyle, drop: false });"""

if OLD_SHEET in html:
    html = html.replace(OLD_SHEET, NEW_SHEET)
    print('OK: Column width from Excel added')
else:
    print('NG: sheetToLayout cells.push pattern not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved! Lines:', html.count('\n'))
