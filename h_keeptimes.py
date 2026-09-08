# h_keeptimes.py  —  soge-keep-times-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_keeptimes.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_keeptimes.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たない。
#
# 何を確かめるか
#   A. 「組み直す」で所要時間・距離・予定時刻を測っている
#   B. 立ち寄り順を作り直していない（手で直した順を壊さない）
#   C. 手で入れた時刻を上書きしない
#   D. 「保存すると再計算」に倒していない／時刻を消していない
#   E. 待機と「間に合いません」を返している
#   F. 未割当・送迎なしの箱は測らない
#   G. 保存の決まりは変えていない（自動の時刻は保存しない）
#   H. 「ゼロから」側は今までどおり
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
WEEK = os.path.join(HERE, "templates", "soge_week.html")


def _top_block(text, name):
    head = "def %s(" % name
    i = text.find("\n" + head)
    if i < 0:
        return None
    lines = text[i + 1:].splitlines(True)
    out = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and not ln[0].isspace():
            break
        out.append(ln)
    return "".join(out)


for f in (APP, WEEK):
    if not os.path.exists(f):
        print("★%s が見つかりません。~/dev/kaigo-ai-app/ で流してください。" % f)
        sys.exit(1)
SRC = open(APP, encoding="utf-8").read()
WK = open(WEEK, encoding="utf-8").read()

KEEP = _top_block(SRC, "soge_build_week_keep")
BUILD = _top_block(SRC, "soge_build_week")
ROWS = _top_block(SRC, "_soge_plan_rows")
if KEEP is None or "soge-keep-times-v1" not in KEEP:
    print("★soge-keep-times-v1 がまだ当たっていません。"
          "patch_soge_keep_times_v1.py を先に流してください。")
    sys.exit(1)
for n, b in (("soge_build_week_keep", KEEP), ("soge_build_week", BUILD),
             ("_soge_plan_rows", ROWS)):
    assert b is not None and b.count("\ndef ") == 0, "★%s の切り出しがおかしい" % n

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


# ---------- A. 測っている ----------
check("A 走行時間を引く", KEEP.count("_soge_drive_detail(") == 1,
      str(KEEP.count("_soge_drive_detail(")))
check("A 乗降時間を足す", KEEP.count("_soge_stop_minutes(") == 1)
check("A 予定時刻を出す", KEEP.count("_soge_planned_times(") == 1)
check("A 所要時間を返す", 'v["minutes"] = _drive + _stop_m' in KEEP)
check("A 距離を返す", 'v["distance_km"] = _km' in KEEP)
check("A 目標超えを返す", 'v["over_target"]' in KEEP and "_soge_trip_target(" in KEEP)
check("A 取れなかったら0に倒す", "_drive, _km, _legs = 0, 0.0, None" in KEEP,
      "取れないときに落ちる")

# ---------- B. 並べ直していない ----------
check("B 立ち寄り順を作り直さない", "_soge_stops_of(" not in KEEP,
      "手で直した順が壊れる")
check("B 車の stops をそのまま測る", '_stops = v.get("stops") or []' in KEEP)

# ---------- C. 手入力を守る ----------
check("C 手で入れた時刻は上書きしない",
      'if s.get("plan_manual"):' in KEEP and "continue" in KEEP)
_i = KEEP.find('if s.get("plan_manual"):')
_j = KEEP.find('s["planned_at"] = _planned[')
check("C 守りが上書きより前", 0 < _i < _j, "%d / %d" % (_i, _j))

# ---------- D. 倒していない ----------
check("D stale にしない", 'v["stale"] = False' in KEEP and 'v["stale"] = True' not in KEEP)
check("D 時刻を消さない", 's["planned_at"] = None' not in KEEP)
check("D 所要時間を None にしない", 'v["minutes"] = None' not in KEEP)

# ---------- E. 待機と警告 ----------
check("E 待機を返す", '"wait_minutes"' in KEEP)
check("E 間に合わない印を返す", '"plan_short"' in KEEP)
check("E 間に合わない便を文字でも出す",
      "間に合いません" in KEEP and "warns.extend(shorts)" in KEEP)
check("E 便名と車名を出す", 'trip.get("trip_name")' in KEEP and 'v.get("vehicle_name")' in KEEP)

# ---------- F. 特別枠は測らない ----------
check("F 未割当・送迎なしは飛ばす",
      'if v.get("unassigned") or v.get("noride"):' in KEEP)

# ---------- G. 保存の決まりは変えていない ----------
check("G 自動の時刻は保存しない",
      '★自動で計算した時刻は保存しない' in ROWS or "自動で計算した時刻は保存しない" in ROWS,
      "保存の決まりが変わっている")
check("G 保存するのは手入力だけ", 's.get("plan_manual") and len(_at) == 5' in ROWS)
check("G 保存側に測る処理を足していない",
      "_soge_planned_times(" not in ROWS and "_soge_drive_detail(" not in ROWS)

# ---------- H. 「ゼロから」側 ----------
check("H ゼロからは今までどおり測る",
      BUILD.count("_soge_planned_times(") == 1 and BUILD.count('"wait_minutes"') == 1)
check("H ゼロからは並べ直す（こちらは正しい）", "_soge_stops_of(" in BUILD)

# ---------- 画面 ----------
check("画面 待機を出す", "v.wait_minutes > 0" in WK)
check("画面 間に合わない印を出す", "v.plan_short" in WK)
check("画面 stale のときは出さない", "if (!v.stale) {" in WK)
check("画面 所要時間の出し方は変えていない", "v.minutes + '分</span>'" in WK)

print("h_keeptimes: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
