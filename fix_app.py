with open('app.py', 'r') as f:
    content = f.read()

old1 = '        import re as _re, json as _json\n        m = _re.search(r'
new1 = '        audio_url = ""\n        if is_audio:\n            try:\n                supabase_s = get_supabase()\n                audio_url = upload_audio_to_supabase(supabase_s, file_bytes, filename, session.get("f_code","unknown"))\n            except Exception as _ae:\n                print(f"音声保存エラー: {_ae}")\n        import re as _re, json as _json\n        m = _re.search(r'

old2 = '            "ai_challenge":        data.get("ai_challenge",""),\n            "created_by":       my_name,'
new2 = '            "ai_challenge":        data.get("ai_challenge",""),\n            "audio_url":          data.get("audio_url",""),\n            "created_by":       my_name,'

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("修正1 OK")
else:
    print("修正1 見つからず")

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("修正2 OK")
else:
    print("修正2 見つからず")

with open('app.py', 'w') as f:
    f.write(content)
print("完了")