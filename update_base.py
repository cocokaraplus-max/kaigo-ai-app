# base.htmlのボトムナビを「トーク」→「掲示板」に変更
# python3 update_base.py

with open('templates/base.html', 'r') as f:
    content = f.read()

# ナビリンクを変更
old1 = '<a href="/chat" class="bottom-nav-item {% block nav_chat %}{% endblock %}" onclick="spaNav(event,\'/chat\')">'
new1 = '<a href="/board" class="bottom-nav-item {% block nav_chat %}{% endblock %}" onclick="spaNav(event,\'/board\')">'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print("ナビリンク変更OK")
else:
    print("ナビリンク見つからず")

# アイコンを変更
old2 = '<span class="material-symbols-outlined">forum</span>'
new2 = '<span class="material-symbols-outlined">campaign</span>'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print("アイコン変更OK")
else:
    print("アイコン見つからず")

# ラベルを変更
old3 = '            トーク'
new3 = '            掲示板'
if old3 in content:
    content = content.replace(old3, new3, 1)
    print("ラベル変更OK")
else:
    print("ラベル見つからず")

# ポーリングを掲示板未読カウントに変更
old4 = "const badge = document.getElementById('chat-badge');"
new4 = "const badge = document.getElementById('chat-badge'); // 掲示板未読バッジ"
# ポーリングURLを変更
old5 = "'/api/unread_count'"
new5 = "'/api/board/unread_count'"
if old5 in content:
    content = content.replace(old5, new5, 1)
    print("ポーリングURL変更OK")
else:
    print("ポーリングURL見つからず")

# /chatのナビアクティブ判定を/boardに変更
old6 = "if (href === '/chat' && (basePath === '/chat' || basePath.startsWith('/chat/'))) {"
new6 = "if (href === '/board' && (basePath === '/board' || basePath.startsWith('/board/'))) {"
if old6 in content:
    content = content.replace(old6, new6, 1)
    print("アクティブ判定変更OK")
else:
    print("アクティブ判定見つからず")

with open('templates/base.html', 'w') as f:
    f.write(content)
print("base.html更新完了")
