# h_payverify.py  —  pay-verify-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_payverify.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_payverify.py
#
# ★app.py と app.py.bak を【その場で読んで】関数を切り出す。
#   写しを持たないので、app.py を直したあとに流し直せば、必ず今の中身を見る。
#   app.py.bak が pay-verify-v1 より前のものでなくなったら、A の比較は飛ばす。
#
# 何を確かめるか
#   A. でたらめな打刻 3000 通りで、直す前(app.py.bak)と後(app.py)の
#      実働・打刻異常・印・休憩・出勤・退勤 が すべて同じ（＝お金に触っていない）
#   B. 在席 - 休憩 = 実働 が、打刻異常でない日で いつでも成り立つ
#   C. 300 か月ぶんのでたらめなデータで、合計行の
#      「在席の合計 - 休憩の合計 = 実働の合計」が外れない
#   D. 中抜けの日（宇佐美さん 2026-08-21 の形）が、数字まで合う
#   E. 秒まで出す時刻 _tc_fmt_time_jst_sec が JST で %H:%M:%S になる
#   F. 「秒を先に捨てる」形にしても中抜けは消えない（社労士さん待ちの論点）
import os
import random
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))
UTC = timezone.utc

PRELUDE = (
    "from datetime import datetime as _tc_dt, timezone as _tc_tz, "
    "timedelta as _tc_td\n"
    "_TC_JST = _tc_tz(_tc_td(hours=9))\n"
)


def _top_block(text, name):
    """字下げの無い行が来たら関数の終わり、で切り出す。

    ★「次の @app.route まで」で切ると、後ろに口を足しただけで切れ目が動く。
      コメント行(#)も、字下げが無ければ関数の外とみなす。
    """
    head = "def %s(" % name
    i = text.find("\n" + head)
    if i < 0:
        if text.startswith(head):
            i = -1
        else:
            return None
    start = i + 1
    lines = text[start:].splitlines(True)
    out = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and not ln[0].isspace():
            break
        out.append(ln)
    return "".join(out)


def load(path, names, need_all=True):
    """path から names の関数だけを切り出して、1つの名前空間に入れて返す。"""
    if not os.path.exists(path):
        return None
    src = open(path, encoding="utf-8").read()
    body = [PRELUDE]
    for n in names:
        blk = _top_block(src, n)
        if blk is None:
            if need_all:
                return None
            continue
        body.append(blk)
        body.append("\n")
    ns = {}
    exec(compile("".join(body), path, "exec"), ns)      # noqa: S102
    return ns


BASE = ["_tc_parse_iso", "_tc_compute_day"]
tc = load(os.path.join(HERE, "app.py"), BASE + ["_tc_fmt_time_jst_sec"])
if tc is None:
    print("★app.py から関数を切り出せませんでした。app.py と同じ所で流してください。")
    sys.exit(1)
tc_before = load(os.path.join(HERE, "app.py.bak"), BASE)

# ★切り出しの道具は、写したら1回だけ「切れた中身」を目で見る、と決めてある。
#   目で見られないぶん、ここで形を確かめる。
_blk = _top_block(open(os.path.join(HERE, "app.py"), encoding="utf-8").read(),
                  "_tc_compute_day")
assert _blk.startswith("def _tc_compute_day(punches):"), "★切り出しの頭がおかしい"
assert _blk.rstrip().endswith("}"), \
    "★切り出しの尻がおかしい（return の途中で切れている）: %r" % _blk.rstrip()[-60:]
assert _blk.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"
assert '"stay_min"' in _blk, "★在席を返していない"

ok = 0
ng = []
skip = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


def iso(dt):
    return dt.astimezone(UTC).isoformat()


def p(kind, dt):
    return {"punch_type": kind, "punched_at": iso(dt)}


def random_day(rnd):
    """でたらめな1日分の打刻列（秒つき・欠けも順番の壊れも入れる）。"""
    base = datetime(2026, 8, rnd.randint(1, 28), 0, 0, 0, tzinfo=JST)
    pun = []
    t = base + timedelta(minutes=rnd.randint(300, 600), seconds=rnd.randint(0, 59))
    for _ in range(rnd.choice([1, 1, 1, 2, 2, 3])):
        if rnd.random() >= 0.06:                       # 6%で出勤を落とす
            pun.append(p("in", t))
        t += timedelta(minutes=rnd.randint(30, 300), seconds=rnd.randint(0, 59))
        for _ in range(rnd.choice([0, 0, 1, 1, 2])):
            pun.append(p("break_start", t))
            t += timedelta(minutes=rnd.randint(5, 90), seconds=rnd.randint(0, 59))
            if rnd.random() < 0.9:                     # 10%で休憩終了を落とす
                pun.append(p("break_end", t))
            t += timedelta(minutes=rnd.randint(10, 120), seconds=rnd.randint(0, 59))
        if rnd.random() < 0.94:                        # 6%で退勤を落とす
            pun.append(p("out", t))
        t += timedelta(minutes=rnd.randint(10, 200), seconds=rnd.randint(0, 59))
    if rnd.random() < 0.05:
        rnd.shuffle(pun)
    return pun


# ---------- A. 実働の数字を1つも変えていない ----------
if tc_before is None or "gap_min" in (_top_block(
        open(os.path.join(HERE, "app.py.bak"), encoding="utf-8").read()
        if os.path.exists(os.path.join(HERE, "app.py.bak")) else "",
        "_tc_compute_day") or "gap_min"):
    skip.append("A（app.py.bak が pay-verify-v1 より前のものではない）")
else:
    rnd = random.Random(20260907)
    diff = []
    for i in range(3000):
        pun = random_day(rnd)
        a = tc_before["_tc_compute_day"](pun)
        b = tc["_tc_compute_day"](pun)
        if not (a["minutes"] == b["minutes"]
                and a["incomplete"] == b["incomplete"]
                and a["flags"] == b["flags"]
                and a["break_min"] == b["break_min"]
                and a["in"] == b["in"]
                and a["out"] == b["out"]):
            diff.append((i, a, b))
    check("A 3000通りで前と後が同じ", not diff,
          "差 %d 件 例=%s" % (len(diff), diff[:1]))
    _one = [p("in", datetime(2026, 8, 3, 9, 0, 5, tzinfo=JST)),
            p("out", datetime(2026, 8, 3, 18, 0, 55, tzinfo=JST))]
    _bf = tc_before["_tc_compute_day"](_one)
    check("A 前には gap_min / stay_min が無い",
          "gap_min" not in _bf and "stay_min" not in _bf)
    _af = tc["_tc_compute_day"](_one)
    check("A 後には gap_min / stay_min がある",
          "gap_min" in _af and "stay_min" in _af)

# ---------- B. 在席 - 休憩 = 実働（日ごと） ----------
rnd = random.Random(11)
bad = []
n_b = 0
for i in range(3000):
    d = tc["_tc_compute_day"](random_day(rnd))
    if d["incomplete"] or d["minutes"] is None:
        continue
    n_b += 1
    if d["stay_min"] - d["break_min"] != d["minutes"]:
        bad.append((i, d))
check("B 在席-休憩=実働（日ごと）", not bad,
      "外れ %d 件 / 見た日 %d" % (len(bad), n_b))
check("B 見た日が十分ある", n_b > 500, "%d 日" % n_b)

# ---------- C. 合計行でも成り立つ ----------
rnd = random.Random(777)
bad_m = []
for m in range(300):
    days = [tc["_tc_compute_day"](random_day(rnd))
            for _ in range(rnd.randint(15, 31))]
    okd = [d for d in days if (not d["incomplete"]) and d["minutes"] is not None]
    if (sum(d["stay_min"] for d in okd) - sum(d["break_min"] for d in okd)
            != sum(d["minutes"] for d in okd)):
        bad_m.append(m)
check("C 合計行でも 在席計-休憩計=実働計", not bad_m,
      "外れ %d か月" % len(bad_m))

# ---------- D. 中抜け（宇佐美さん 2026-08-21 の実データの形） ----------
U0821 = [
    p("in",          datetime(2026, 8, 21,  8, 21, 52, tzinfo=JST)),
    p("break_start", datetime(2026, 8, 21, 13, 41,  5, tzinfo=JST)),
    p("break_end",   datetime(2026, 8, 21, 14, 12, 24, tzinfo=JST)),
    p("out",         datetime(2026, 8, 21, 15, 11,  2, tzinfo=JST)),
    p("in",          datetime(2026, 8, 21, 17, 54, 52, tzinfo=JST)),
    p("out",         datetime(2026, 8, 21, 20, 24, 40, tzinfo=JST)),
]
d21 = tc["_tc_compute_day"](U0821)
check("D 打刻異常にならない", d21["incomplete"] is False, str(d21["flags"]))
check("D 実働 527分", d21["minutes"] == 527, str(d21["minutes"]))
check("D 休憩 31分", d21["break_min"] == 31, str(d21["break_min"]))
check("D 中抜け 163分", d21["gap_min"] == 163, str(d21["gap_min"]))
check("D 在席 558分", d21["stay_min"] == 558, str(d21["stay_min"]))
check("D 在席-休憩=実働",
      d21["stay_min"] - d21["break_min"] == d21["minutes"])
# ★社労士さんが見ているのは【時:分までのCSV】。秒は見えていない。
#   だから 20:24 - 08:21 = 723分 で引く。秒つきで引くと 722分 になるが、
#   それは社労士さんの手元では起きない引き算。
_look = ((20 * 60 + 24) - (8 * 60 + 21)) - 31
check("D 見た目の引き算 692分", _look == 692, str(_look))
check("D 見た目との差 165分", _look - d21["minutes"] == 165,
      "%d - %d = %d" % (_look, d21["minutes"], _look - d21["minutes"]))

# 中抜けが2回でも合う。
#   10:00:50→12:00:00 が 119分、14:30:30→17:00:00 が 149分。
#   ★中抜けも区間ごとに切り捨てる（実働と同じ数え方）。270 ではなく 268。
d2 = tc["_tc_compute_day"]([
    p("in",  datetime(2026, 8, 5,  8,  0, 10, tzinfo=JST)),
    p("out", datetime(2026, 8, 5, 10,  0, 50, tzinfo=JST)),
    p("in",  datetime(2026, 8, 5, 12,  0,  0, tzinfo=JST)),
    p("out", datetime(2026, 8, 5, 14, 30, 30, tzinfo=JST)),
    p("in",  datetime(2026, 8, 5, 17,  0,  0, tzinfo=JST)),
    p("out", datetime(2026, 8, 5, 19,  0,  0, tzinfo=JST)),
])
check("D 中抜け2回 gap=268分", d2["gap_min"] == 268, str(d2["gap_min"]))
check("D 中抜け2回 在席-休憩=実働",
      d2["stay_min"] - d2["break_min"] == d2["minutes"])

d0 = tc["_tc_compute_day"]([
    p("in",  datetime(2026, 8, 6, 9, 0, 5, tzinfo=JST)),
    p("out", datetime(2026, 8, 6, 18, 0, 55, tzinfo=JST)),
])
check("D 中抜けなしは gap=0", d0["gap_min"] == 0, str(d0["gap_min"]))
check("D 中抜けなし 在席=実働",
      d0["stay_min"] == d0["minutes"] == 540, str(d0))

# ---------- E. 秒まで出す ----------
F = tc["_tc_fmt_time_jst_sec"]
check("E 秒が出る", F("2026-08-20T23:21:52+00:00") == "08:21:52",
      F("2026-08-20T23:21:52+00:00"))
check("E 秒0でも8桁", F("2026-08-21T00:00:00+09:00") == "00:00:00")
check("E 空は --:--:--", F(None) == "--:--:--")
check("E 読めない値も --:--:--", F("xxx") == "--:--:--")
check("E Zつきも読める", F("2026-08-20T23:21:52Z") == "08:21:52")

# ---------- F. 「秒を先に捨てる」形にしても中抜けは消えない ----------
_trunc = [{"punch_type": q["punch_type"],
           "punched_at": iso(tc["_tc_parse_iso"](q["punched_at"])
                             .replace(second=0, microsecond=0))}
          for q in U0821]
d21t = tc["_tc_compute_day"](_trunc)
check("F 秒を先に捨てても 529分にしかならない（中抜けは残る）",
      d21t["minutes"] == 529, str(d21t["minutes"]))
check("F 秒を先に捨てても 在席-休憩=実働",
      d21t["stay_min"] - d21t["break_min"] == d21t["minutes"])

print("h_payverify: %d 件 OK" % ok)
for s in skip:
    print("  … 飛ばした: %s" % s)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
