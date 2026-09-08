# h_nogeo.py  —  soge-nogeo-leg-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_nogeo.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_nogeo.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たないので、
#   app.py を直したあとに流し直せば、必ず今の中身を見る。
#
# 何を確かめるか
#   A. 座標が無い人の区間（0分）が、分かっている区間の平均で埋まる
#   B. 全員そろっているときは1つも触らない（同じ住所のご夫婦の0分を守る）
#   C. 1人も座標が無い便は触らない（埋めようがない）
#   D. None・長さ違いを壊さない
#   E. 鍵に座標の有無が効く（座標が付いたら取り直す／付いていないうちは同じ）
#   F. _soge_drive_detail が、鍵にも返しにもちゃんと使っている（本文の検査）
#   G. 警告と geo_missing が、組み直し・保存済みの【両方】に出る
#   H. 画面に「座標を取り直す」がある
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
WKSRC = open(WEEK, encoding="utf-8").read()

parts = {}
for n in ("_soge_route_hash", "_soge_fill_nogeo_legs", "_soge_name_list"):
    b = _top_block(SRC, n)
    if b is None:
        print("★soge-nogeo-leg-v1 がまだ当たっていません。"
              "patch_soge_nogeo_leg_v1.py を先に流してください。")
        sys.exit(1)
    assert b.count("\ndef ") == 0, "★%s が次の関数まで飲み込んでいる" % n
    parts[n] = b

_ns = {}
exec(compile("\n".join(parts.values()), APP, "exec"), _ns)   # noqa: S102
fill = _ns["_soge_fill_nogeo_legs"]
rhash = _ns["_soge_route_hash"]
namelist = _ns["_soge_name_list"]

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


G = {"lat": 35.1, "lng": 137.1}
S3 = [{"patient_id": "a"}, {"patient_id": "b"}, {"patient_id": "c"}]
ALL = {"a": G, "b": G, "c": G}

# ---------- A. 平均で埋まる ----------
r = fill([0, 9.0, 5.0], S3, {"b": G, "c": G})
check("A 先頭の0分が埋まる", r == [7.0, 9.0, 5.0], str(r))
r = fill([4.0, 0, 6.0], S3, {"a": G, "c": G})
check("A まん中の0分が埋まる", r == [4.0, 5.0, 6.0], str(r))
r = fill([0, 8.0, 0], S3, {"b": G})
check("A 2人ぶんでも埋まる", r == [8.0, 8.0, 8.0], str(r))
# ★送り便の1人目が出発時刻と同じになる、が消えること
r = fill([0, 9.0, 4.15, 6.15, 2.32],
         [{"patient_id": x} for x in "abcde"],
         {"b": G, "c": G, "d": G, "e": G})
check("A 本番で出た形（先頭0）が直る", r[0] > 0, str(r))

# ---------- B. 全員そろっていれば触らない ----------
check("B そろっていれば素通り", fill([3.0, 9.0, 5.0], S3, ALL) == [3.0, 9.0, 5.0])
check("B 同じ住所のご夫婦の0分は残す",
      fill([4.0, 0.0, 5.0], S3, ALL) == [4.0, 0.0, 5.0],
      "座標があるのに書き換えている")

# ---------- C. 1人も座標が無い便 ----------
check("C 全員座標なしなら触らない", fill([0, 0, 0], S3, {}) == [0, 0, 0])

# ---------- D. 壊れた入力 ----------
check("D None を壊さない", fill(None, S3, {"b": G}) is None)
check("D 長さ違いを触らない", fill([1.0, 2.0], S3, {"b": G}) == [1.0, 2.0])
check("D 立ち寄りが無ければ触らない", fill([1.0], [], {"b": G}) == [1.0])
check("D 数でないものが混ざっていたら触らない",
      fill([0, "x", 5.0], S3, {"b": G, "c": G}) == [0, "x", 5.0])

# ---------- E. 鍵 ----------
check("E 同じ入力なら同じ鍵", rhash("x", S3, ALL) == rhash("x", S3, ALL))
check("E 座標が付いたら鍵が変わる",
      rhash("x", S3, {"b": G, "c": G}) != rhash("x", S3, ALL),
      "古い0分のキャッシュを拾い続けてしまう")
check("E 座標を渡さない呼び方は今までどおり",
      rhash("x", S3) == rhash("x", S3))
check("E 座標つきと座標なしの鍵は別",
      rhash("x", S3) != rhash("x", S3, ALL))
check("E 施設が変われば鍵も変わる", rhash("x", S3, ALL) != rhash("y", S3, ALL))
check("E 並びが変われば鍵も変わる",
      rhash("x", S3, ALL) != rhash("x", list(reversed(S3)), ALL))

# ---------- 名前の並び ----------
check("名前 3人はそのまま", namelist(["あ", "い", "う"]) == "あ・い・う")
check("名前 6人はたたむ",
      namelist(list("あいうえおか")) == "あ・い・う・え・お ほか1名",
      namelist(list("あいうえおか")))
check("名前 空は空", namelist([]) == "" and namelist([None, " "]) == "")

# ---------- F. 使われ方（本文の検査） ----------
dd = _top_block(SRC, "_soge_drive_detail") or ""
check("F 鍵に座標を渡している", "_soge_route_hash(origin, stops, geo)" in dd)
check("F キャッシュから返すときに埋めている",
      dd.count("_soge_fill_nogeo_legs(") == 2, str(dd.count("_soge_fill_nogeo_legs(")))
check("F 保存するのは埋める前",
      dd.find('"legs": legs,') < dd.find("return minutes, dist_km"),
      "当て推量をキャッシュに書いている")
check("F 経路に入れる条件は変えていない", "if not g:\n            continue" in dd)

# ---------- G. 警告と geo_missing ----------
bw = _top_block(SRC, "soge_build_week") or ""
check("G 組み直しに名前が出る", "_soge_name_list(no_geo)" in bw)
check("G 組み直しが geo_missing を返す", '"geo_missing": len(no_geo)' in bw)
rv = _top_block(SRC, "_soge_rows_view") or ""
check("G 保存済みにも警告が出る", "_soge_name_list(_ng)" in rv,
      "ふだん見る配車表に出ないと気づけない")
check("G 保存済みも geo_missing を返す", '"geo_missing": len(_ng)' in rv)
check("G 文言はボタンを指している",
      SRC.count("下の「座標を取り直す」を押してください。") == 2)

# ★到着予定時刻の計算そのものは触っていないこと
pt = _top_block(SRC, "_soge_planned_times") or ""
check("G 予定時刻の計算は触っていない",
      "_soge_fill_nogeo_legs" not in pt and "soge-back-plan-v1" in pt)

# ---------- H. 画面 ----------
check("H ボタンがある", "座標を取り直す</button>" in WKSRC)
check("H 警告の作りは1か所",
      WKSRC.count("function sgWarnHTML(") == 1
      and WKSRC.count("$('sgWarnings').innerHTML = sgWarnHTML(d);") == 2,
      str(WKSRC.count("$('sgWarnings').innerHTML = sgWarnHTML(d);")))
check("H 座標が無いときだけ出す", "if (d.geo_missing)" in WKSRC)
check("H 取れなかった人を出す", "取れなかった方" in WKSRC)
check("H 未保存なら読み直さない", "state.dirty" in WKSRC and "保存してから開き直す" in WKSRC)

print("h_nogeo: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
