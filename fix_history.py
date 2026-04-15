"""
TASUKARU 更新履歴修正スクリプト
実行方法: python3 fix_history.py
対象ファイル: app.py（同じディレクトリに置いて実行）
"""

import re

with open("app.py", "r", encoding="utf-8") as f:
    src = f.read()

# ============================================================
# 修正1: input_view の records.insert に record_date を追加
# created_at は常に「今の日時」にする（指定日付は record_date へ）
# ============================================================
old_input = '''                    from datetime import time as dt_time
                    record_time = datetime.now(tokyo_tz).time()
                    dt_record = tokyo_tz.localize(datetime.combine(
                        datetime.strptime(record_date, "%Y-%m-%d").date(),
                        record_time
                    ))
                    supabase.table("records").insert({
                        "facility_code": f_code,
                        "chart_number": m.group(1),
                        "user_name": m.group(2),
                        "staff_name": my_name,
                        "content": content,
                        "created_at": dt_record.isoformat(),
                        "image_urls": image_urls if image_urls else None
                    }).execute()'''

new_input = '''                    from datetime import time as dt_time
                    now_jst = datetime.now(tokyo_tz)
                    supabase.table("records").insert({
                        "facility_code": f_code,
                        "chart_number": m.group(1),
                        "user_name": m.group(2),
                        "staff_name": my_name,
                        "content": content,
                        "created_at": now_jst.isoformat(),
                        "record_date": record_date,
                        "image_urls": image_urls if image_urls else None
                    }).execute()'''

if old_input in src:
    src = src.replace(old_input, new_input)
    print("✅ 修正1完了: input_view の created_at を現在日時に固定 + record_date を保存")
else:
    print("⚠️  修正1: 対象箇所が見つかりませんでした（既に修正済みか確認してください）")

# ============================================================
# 修正2: top ルートの履歴表示
# created_at 降順ソートはそのまま、表示日付は record_date 優先に
# ============================================================
old_top = '''            for r in filtered:
                records.append({
                    "user_name": r["user_name"],
                    "time": parse_jst(r["created_at"]),
                    "date": str(r.get("record_date", str(parse_jst_date(r["created_at"])))),
                })'''

new_top = '''            for r in filtered:
                # record_date があればそちらを表示日付に使う（created_at は入力日時）
                display_date = r.get("record_date") or str(parse_jst_date(r["created_at"]))
                records.append({
                    "user_name": r["user_name"],
                    "time": parse_jst(r["created_at"]),
                    "date": str(display_date),
                })'''

if old_top in src:
    src = src.replace(old_top, new_top)
    print("✅ 修正2完了: top の履歴表示日付を record_date 優先に変更")
else:
    print("⚠️  修正2: 対象箇所が見つかりませんでした（既に修正済みか確認してください）")

with open("app.py", "w", encoding="utf-8") as f:
    f.write(src)

print("\n🎉 app.py の修正が完了しました！")
print("次のコマンドでデプロイしてください：")
print("  git add app.py && git commit -m '履歴: created_atを入力日時に固定、record_dateに指定日付を保存'")
print("  gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --platform managed --allow-unauthenticated")
