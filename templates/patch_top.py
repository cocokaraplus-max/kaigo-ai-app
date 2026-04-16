#!/usr/bin/env python3
# top.html 全面修正パッチ（ベル・歯車・nullエラー対応）
# 使い方: python3 patch_top.py
# 実行場所: /Users/ZIMAX 1/Desktop/kaigo-ai-app/templates/

import shutil, os, re

TARGET = 'top.html'
BACKUP = 'top.html.bak2'

if not os.path.exists(TARGET):
    print(f'❌ {TARGET} が見つかりません')
    exit(1)

shutil.copy2(TARGET, BACKUP)
print(f'✅ バックアップ: {BACKUP}')

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()

fixes = 0

# ========== ① 歯車ボタンCSS削除（base.htmlと重複・競合） ==========
css_start = content.find('/* ★ 歯車ボタン */')
css_end   = content.find('/* アイコン設定ボタン */')
if css_start > -1 and css_end > -1:
    removed = content[css_start:css_end]
    content = content[:css_start] + content[css_end:]
    print(f'✅ ① 歯車・設定モーダルCSS削除: {len(removed)}文字')
    fixes += 1
else:
    print('⚠️  ① CSS: 既に削除済み？')

# ========== ② 歯車ボタンHTML削除（base.htmlのtop-fab-areaと重複） ==========
html_start = content.find('<!-- ★ 歯車ボタン（右上固定） -->')
html_end   = content.find('<div class="logo-area">')
if html_start > -1 and html_end > -1:
    removed = content[html_start:html_end]
    content = content[:html_start] + content[html_end:]
    print(f'✅ ② 歯車ボタンHTML削除: {len(removed)}文字')
    fixes += 1
else:
    print('⚠️  ② 歯車HTML: 既に削除済み？')

# ========== ③ 歯車ボタンJSイベント: nullガード追加 ==========
old_fab_js = "// ===== 歯車ボタン =====\nvar fabBtn = document.getElementById('settings-fab-btn');\nvar modal  = document.getElementById('user-settings-modal');\nvar closeBtn = document.getElementById('settings-close-btn');\n\nfabBtn.addEventListener('click', openSettings);\nfabBtn.addEventListener('touchend', function(e) { e.preventDefault(); openSettings(); });\ncloseBtn.addEventListener('click', closeSettings);\nmodal.addEventListener('click', function(e) { if (e.target === modal) closeSettings(); });"

new_fab_js = "// ===== 歯車ボタン: base.htmlのイベント委譲と統合済み =====\nvar fabBtn   = document.getElementById('settings-fab-btn');\nvar modal    = document.getElementById('user-settings-modal');\nvar closeBtn = document.getElementById('settings-close-btn');\n\nif (fabBtn)   { fabBtn.addEventListener('click', openSettings); fabBtn.addEventListener('touchend', function(e) { e.preventDefault(); openSettings(); }); }\nif (closeBtn) { closeBtn.addEventListener('click', closeSettings); }\nif (modal)    { modal.addEventListener('click', function(e) { if (e.target === modal) closeSettings(); }); }"

if old_fab_js in content:
    content = content.replace(old_fab_js, new_fab_js)
    print('✅ ③ fabBtnのnullガード追加')
    fixes += 1
else:
    print('⚠️  ③ fabBtnJS: 見つからず（既に修正済み？）')

# ========== ④ openIconBtnのnullガード追加 ==========
old_icon = "openIconBtn.addEventListener('click', function() { closeSettings(); iconModal.style.display = 'flex'; });\nopenIconBtn.addEventListener('touchend', function(e) { e.preventDefault(); closeSettings(); iconModal.style.display = 'flex'; });\ncloseIconBtn.addEventListener('click', function() { iconModal.style.display = 'none'; });\ndocument.getElementById('my-icon-btn').addEventListener('click', function() { iconModal.style.display = 'flex'; });\niconModal.addEventListener('click', function(e) { if (e.target === iconModal) iconModal.style.display = 'none'; });"

new_icon = "if (openIconBtn && iconModal) {\n    openIconBtn.addEventListener('click', function() { if (typeof closeSettings==='function') closeSettings(); iconModal.style.display = 'flex'; });\n    openIconBtn.addEventListener('touchend', function(e) { e.preventDefault(); if (typeof closeSettings==='function') closeSettings(); iconModal.style.display = 'flex'; });\n}\nif (closeIconBtn) { closeIconBtn.addEventListener('click', function() { iconModal.style.display = 'none'; }); }\nvar _myIconBtn = document.getElementById('my-icon-btn');\nif (_myIconBtn && iconModal) { _myIconBtn.addEventListener('click', function() { iconModal.style.display = 'flex'; }); }\nif (iconModal) { iconModal.addEventListener('click', function(e) { if (e.target === iconModal) iconModal.style.display = 'none'; }); }"

if old_icon in content:
    content = content.replace(old_icon, new_icon)
    print('✅ ④ openIconBtnのnullガード追加')
    fixes += 1
else:
    print('⚠️  ④ openIconBtnJS: 見つからず（既に修正済み？）')

# ========== ⑤ 更新ログモーダルHTMLを追加 ==========
if 'id="update-log-modal"' not in content:
    update_log_modal = '''
<!-- ★ 更新ログモーダル -->
<div id="update-log-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:3000;align-items:flex-end;justify-content:center;">
    <div style="background:#fff;border-radius:20px 20px 0 0;width:100%;max-width:480px;padding:20px 20px 40px;max-height:80vh;overflow-y:auto;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
            <div style="font-size:1rem;font-weight:800;color:#202124;display:flex;align-items:center;gap:8px;">
                <span class="material-symbols-outlined" style="color:#1a73e8;font-size:22px;">notifications</span>
                アップデート情報
            </div>
            <button id="close-update-log-btn" style="background:none;border:none;cursor:pointer;padding:4px;">
                <span class="material-symbols-outlined">close</span>
            </button>
        </div>
        <div style="font-size:0.85rem;color:#5f6368;line-height:1.8;">
            <div style="margin-bottom:16px;padding:12px;background:#f8f9fa;border-radius:12px;">
                <div style="font-weight:800;color:#1a73e8;margin-bottom:6px;">🦝 Ver.4.0 （2026年4月）</div>
                <div>・設定モーダルをリニューアル</div>
                <div>・ベル・歯車ボタンを右上に配置</div>
                <div>・更新履歴をタップしてケース記録へジャンプ</div>
                <div>・更新履歴を入力順（新着順）に表示</div>
                <div>・評価レポートをICF視点・機能訓練指導員口調に改善</div>
                <div>・各種保存エラーを修正</div>
            </div>
            <div style="padding:12px;background:#f8f9fa;border-radius:12px;">
                <div style="font-weight:800;color:#5f6368;margin-bottom:6px;">📋 Ver.3.x</div>
                <div>・タスク管理・掲示板・バイタル管理機能を追加</div>
                <div>・AIによる日次統合記録を追加</div>
            </div>
        </div>
    </div>
</div>

'''
    # {% block content %}の直後（logo-areaの前）に挿入
    insert_marker = '<div class="logo-area">'
    if insert_marker in content:
        content = content.replace(insert_marker, update_log_modal + insert_marker, 1)
        print('✅ ⑤ 更新ログモーダルHTML追加')
        fixes += 1
    else:
        print('⚠️  ⑤ 挿入位置が見つかりません')
else:
    print('✅ ⑤ 更新ログモーダル: 既に存在')

# ========== ⑥ manual上に戻るボタンのscrollTo修正 ==========
# （manual.htmlはこのファイルではないのでここでは省略）

# ========== 保存 ==========
with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\n✅ 完了: {fixes}箇所修正')
print('ロールバック: cp top.html.bak2 top.html')
