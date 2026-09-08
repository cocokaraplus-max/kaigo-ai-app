# h_datedriver.py  —  soge-date-driver-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_datedriver.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_datedriver.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たないので、
#   app.py を直したあとに流し直せば、必ず今の中身を見る。
#
# 何を確かめるか
#   A. 変えた便だけに当たる。変えていない便は触らない
#   B. 未設定に戻す／未設定から入れる、どちらも当たる
#   C. 当ててはいけない日（過ぎた日・確定済み・読めない・まだ無い）では
#      【読みにも行かない】
#   D. 臨時便は触らない（その日かぎりのものなので配車表では決められない）
#   E. 特別枠（0=車が未定 / -1=送迎なし）は触らない
#   F. 配車表に無い便は触らない
#   G. 読めなかったら [] を返す（例外を外に出さない）
#   H. 1件の書き込みが落ちても、残りは当たる
#   I. 一言（_soge_driver_say）の文面。1件／3件／4件以上／未設定
#   J. 保存の口からは呼び、取り消しの口からは呼ばない
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


def _top_block(text, name):
    """字下げの無い行が来たら関数の終わり、で切り出す。"""
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


if not os.path.exists(APP):
    print("★app.py が見つかりません。~/dev/kaigo-ai-app/ で流してください。")
    sys.exit(1)
SRC = open(APP, encoding="utf-8").read()

push_src = _top_block(SRC, "_soge_push_driver")
say_src = _top_block(SRC, "_soge_driver_say")
if push_src is None or say_src is None:
    print("★soge-date-driver-v1 がまだ当たっていません。"
          "patch_soge_date_driver_v1.py を先に流してください。")
    sys.exit(1)

# ★切り出しの道具は、写したら1回は切れた中身を見る、と決めてある。
assert push_src.startswith("def _soge_push_driver("), "★切り出しの頭がおかしい"
assert push_src.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"
# ★入れ子の def は字下げされているので "\ndef " には当たらない（0が正しい）。
#   ここで1回転んだ。数は当ててから書く。
assert say_src.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"
assert "    def _one(" in say_src, "★一言の中の入れ子が無い"

_ns = {"datetime": datetime, "timezone": timezone, "timedelta": timedelta}
exec(compile(push_src + "\n" + say_src, APP, "exec"), _ns)   # noqa: S102
push = _ns["_soge_push_driver"]
say = _ns["_soge_driver_say"]

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


# ---------- 偽のSupabase ----------
class _Res(object):
    def __init__(self, data):
        self.data = data


class _Q(object):
    def __init__(self, db):
        self.db = db
        self.kind = None
        self.payload = None
        self.f = {}

    def select(self, cols):
        self.kind = "select"
        self.cols = cols
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def eq(self, k, v):
        self.f[k] = v
        return self

    def execute(self):
        if self.kind == "select":
            self.db.reads += 1
            if self.db.read_fail:
                raise RuntimeError("読めません")
            return _Res([dict(d) for d in self.db.days])
        self.db.writes += 1
        _id = self.f.get("id")
        if _id in self.db.write_fail:
            raise RuntimeError("書けません")
        self.db.updates.append((_id, self.payload.get("driver_name")))
        return _Res([])


class _DB(object):
    def __init__(self, days, read_fail=False, write_fail=()):
        self.days = days
        self.read_fail = read_fail
        self.write_fail = set(write_fail)
        self.updates = []
        self.reads = 0
        self.writes = 0

    def table(self, name):
        assert name == "soge_days", "★soge_days 以外を触っている: %s" % name
        return _Q(self)


def day(i, tk, vno, drv, name=None, extra=False):
    return {"id": i, "trip_key": tk, "trip_name": (name or tk),
            "vehicle_no": vno, "driver_name": drv, "is_extra": extra}


def row(tk, vno, drv):
    return {"trip_key": tk, "vehicle_no": vno, "driver_name": drv}


D = "2026-09-08"
F = "cocokaraplus-5526"

# ---------- A. 変えた便だけに当たる ----------
db = _DB([day(1, "t1", 1, "山田", "迎え便"),
          day(2, "t1", 2, "鈴木", "迎え便"),
          day(3, "t3", 1, "田中", "送り便")])
chg = push(db, F, D, [row("t1", 1, "佐藤"),      # 変えた
                      row("t1", 2, "鈴木"),      # 同じ
                      row("t3", 1, "田中")], "")  # 同じ
check("A 変えた1件だけ当たる", db.updates == [(1, "佐藤")], str(db.updates))
check("A 変えていない便は書きに行かない", db.writes == 1, str(db.writes))
check("A 返り値は (便名, 前, 後)", chg == [("迎え便", "山田", "佐藤")], str(chg))

# ---------- B. 未設定に戻す／未設定から入れる ----------
db = _DB([day(1, "t1", 1, "山田", "迎え便"), day(2, "t3", 1, None, "送り便")])
chg = push(db, F, D, [row("t1", 1, ""), row("t3", 1, "田中")], "")
check("B 未設定に戻すと None が入る", (1, None) in db.updates, str(db.updates))
check("B 未設定から名前を入れられる", (2, "田中") in db.updates, str(db.updates))
check("B 前が未設定なら空文字で返る",
      ("送り便", "", "田中") in chg, str(chg))

# ---------- C. 当ててはいけない日 ----------
for r in ("past", "locked", "unknown", "not_yet"):
    db = _DB([day(1, "t1", 1, "山田")])
    chg = push(db, F, D, [row("t1", 1, "佐藤")], r)
    check("C %s では当てない" % r, chg == [] and db.writes == 0)
    check("C %s では読みにも行かない" % r, db.reads == 0, str(db.reads))

# 空文字（＝作り直せた）や merged/write_failed のときは当てる
for r in ("", "merged", "write_failed", "clear_failed", "no_week"):
    db = _DB([day(1, "t1", 1, "山田")])
    push(db, F, D, [row("t1", 1, "佐藤")], r)
    check("C 理由 %r では当てる" % r, db.updates == [(1, "佐藤")], str(db.updates))

# ---------- D. 臨時便は触らない ----------
db = _DB([day(9, "t1", 1, "山田", "臨時便", extra=True)])
chg = push(db, F, D, [row("t1", 1, "佐藤")], "")
check("D 臨時便は触らない", chg == [] and db.writes == 0, str(db.updates))

# ---------- E. 特別枠は触らない ----------
db = _DB([day(1, "t1", 0, "山田"), day(2, "t1", -1, "山田")])
chg = push(db, F, D, [row("t1", 0, "佐藤"), row("t1", -1, "佐藤")], "")
check("E 車が未定(0)・送迎なし(-1) は触らない",
      chg == [] and db.writes == 0, str(db.updates))

# 便キーが空の行も無視する
db = _DB([day(1, "", 1, "山田")])
push(db, F, D, [row("", 1, "佐藤")], "")
check("E 便キーが空の行は触らない", db.writes == 0)

# ---------- F. 配車表に無い便は触らない ----------
db = _DB([day(1, "t1", 1, "山田"), day(2, "t9", 1, "鈴木")])
push(db, F, D, [row("t1", 1, "佐藤")], "")
check("F 配車表に無い便(t9)は触らない", db.updates == [(1, "佐藤")], str(db.updates))

# ---------- G. 読めなかったら [] ----------
db = _DB([day(1, "t1", 1, "山田")], read_fail=True)
chg = push(db, F, D, [row("t1", 1, "佐藤")], "")
check("G 読めなければ [] を返す（落ちない）", chg == [] and db.writes == 0)

# ---------- H. 1件落ちても残りは当たる ----------
db = _DB([day(1, "t1", 1, "山田"), day(2, "t3", 1, "田中")], write_fail=[1])
chg = push(db, F, D, [row("t1", 1, "佐藤"), row("t3", 1, "高橋")], "")
check("H 落ちた1件は返り値に入れない",
      chg == [("t3", "田中", "高橋")], str(chg))
check("H 残りは当たる", db.updates == [(2, "高橋")], str(db.updates))

# ---------- I. 一言 ----------
check("I 何も無ければ空", say([]) == "")
s1 = say([("迎え便", "山田", "佐藤")])
check("I 1件の文面", "迎え便：山田 → 佐藤" in s1 and s1.endswith("。"), s1)
check("I 反映したと書く", "反映しました" in s1, s1)
s2 = say([("迎え便", "", "佐藤"), ("送り便", "田中", "")])
check("I 空は「未設定」と書く",
      "迎え便：未設定 → 佐藤" in s2 and "送り便：田中 → 未設定" in s2, s2)
s4 = say([("a", "1", "2"), ("b", "1", "2"), ("c", "1", "2"), ("d", "1", "2")])
check("I 4件なら3件＋ほか1件", "ほか1件" in s4 and "d：" not in s4, s4)
s3 = say([("a", "1", "2"), ("b", "1", "2"), ("c", "1", "2")])
check("I 3件はそのまま出す", "ほか" not in s3 and "c：1 → 2" in s3, s3)

# ---------- J. 呼び出し側 ----------
_sv = _top_block(SRC, "api_soge_date_save") or ""
_dl = _top_block(SRC, "api_soge_date_delete") or ""
check("J 保存の口から1回だけ呼ぶ", _sv.count("_soge_push_driver(") == 1,
      str(_sv.count("_soge_push_driver(")))
check("J 取り消しの口からは呼ばない", "_soge_push_driver(" not in _dl)
check("J 保存の返しに drivers を入れている", '"drivers"' in _sv)
check("J 作り直しの呼び方は変えていない",
      _sv.count("_soge_date_rebuild(") == 1)

# ★9/2 に入れた歯止め（その日に運転手があれば配車表で上書きしない）は
#   今回そのまま残っていること。ここを消して直すのは間違い。
_mg = _top_block(SRC, "_soge_merge_day") or ""
check("J 9/2 の歯止めは残っている",
      'head["driver_name"] = day.get("driver_name")' in _mg)

print("h_datedriver: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
