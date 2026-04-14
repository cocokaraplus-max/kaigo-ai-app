# python3 add_board_private.py で実行してください

with open('app.py', 'r') as f:
    content = f.read()

# board_postsのinsertにis_private追加
old = '''        res = supabase.table("board_posts").insert({
            "facility_code": f_code, "staff_name": my_name,
            "content": content, "image_urls": image_urls,
            "file_urls": [], "audio_url": audio_url,
            "mention_names": mentions, "is_pinned": False,
        }).execute()'''

new = '''        is_private = request.form.get("is_private", "0") == "1"
        res = supabase.table("board_posts").insert({
            "facility_code": f_code, "staff_name": my_name,
            "content": content, "image_urls": image_urls,
            "file_urls": [], "audio_url": audio_url,
            "mention_names": mentions, "is_pinned": False,
            "is_private": is_private,
        }).execute()'''

if old in content:
    content = content.replace(old, new, 1)
    print("is_private追加OK")
else:
    print("該当箇所なし")

with open('app.py', 'w') as f:
    f.write(content)
print("行数:", len(content.splitlines()))
