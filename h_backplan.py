# h_backplan.py  —  soge-back-plan-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_backplan.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_backplan.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たないので、
#   app.py を直したあとに流し直せば、必ず今の中身を見る。
#
# 何を確かめるか
#   A. トグルが off / 到着が空 のときは、これまでと1分も変わらない
#   B. 送り便（迎えのない便）は、到着を入れても前向きのまま
#   C. 中間便：送りは前向き、迎えは到着から逆算、間に待機が出る
#   D. 迎え便：出発の前に待機が出る（＝設定より遅く出れば足りる）
#   E. 逆算した便は【必ず到着時刻ちょうどに事業所へ戻る】
#   F. 間に合わない日は前向きに倒して short を返す（時刻は前向きと同じ）
#   G. 車いすの乗降時間が効く／立ち寄りが1件でも動く
#   H. 区間の時間が無いとき（等分）でも動く
#   I. 便の設定が「到着」を持ち回る（形が違えば空に倒す）
#   J. 呼び出し側と設定の読み書きに、到着とトグルが入っている
import os
import sys

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

blk = _top_block(SRC, "_soge_planned_times")
nrm = _top_block(SRC, "_soge_norm_trips")
if blk is None or nrm is None or "soge-back-plan-v1" not in SRC:
    print("★soge-back-plan-v1 がまだ当たっていません。"
          "patch_soge_back_plan_v1.py を先に流してください。")
    sys.exit(1)

# ★切り出しの道具は、写したら1回は切れた中身を見る、と決めてある。
assert blk.startswith("def _soge_planned_times("), "★切り出しの頭がおかしい"
assert blk.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"
assert blk.rstrip().endswith("]"), "★return の途中で切れている"

_ns = {}
exec(compile(blk + "\n" + nrm, APP, "exec"), _ns)      # noqa: S102
plan = _ns["_soge_planned_times"]
norm = _ns["_soge_norm_trips"]

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


def S(back_plan=False, stop=2, wc=5):
    return {"stop_minutes": stop, "stop_minutes_wc": wc, "back_plan": back_plan}


def drop(name, wcs=False):
    return {"type": "dropoff", "user_name": name, "is_wheelchair": wcs}


def pick(name, wcs=False):
    return {"type": "pickup", "user_name": name, "is_wheelchair": wcs}


def m(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


# 中間便の見本。送り2人・迎え2人、各区間10分、乗降2分。
#   走行は 施設→s0→s1→s2→s3→施設 の5区間 = 50分。行きの4区間が legs。
MID = [drop("A"), drop("B"), pick("C"), pick("D")]
LEGS = [10, 10, 10, 10]
DRIVE = 50

# ---------- A. トグル off / 到着が空 は、これまでどおり ----------
base = plan("12:00", MID, DRIVE, S(False), LEGS)
check("A 前向きの並び", base == ["12:10", "12:22", "12:34", "12:46"], str(base))
check("A トグルoffなら到着を入れても同じ",
      plan("12:00", MID, DRIVE, S(False), LEGS, "13:30") == base)
check("A 到着が空なら同じ",
      plan("12:00", MID, DRIVE, S(True), LEGS, "") == base)
check("A 到着が None でも同じ",
      plan("12:00", MID, DRIVE, S(True), LEGS, None) == base)
check("A 形の違う到着は無視して前向き",
      plan("12:00", MID, DRIVE, S(True), LEGS, "1330") == base)
i = {}
plan("12:00", MID, DRIVE, S(True), LEGS, "13:30", i)
check("A 逆算したときは back が立つ", i.get("back") is True, str(i))

# ---------- B. 送り便（迎えが無い）は前向きのまま ----------
DRO = [drop("A"), drop("B")]
f = plan("16:00", DRO, 30, S(False), [10, 10])
b = plan("16:00", DRO, 30, S(True), [10, 10], "17:00", i)
check("B 送り便は到着を入れても前向き", b == f, "%s / %s" % (b, f))
check("B 送り便では警告も出さない", i.get("short") is False, str(i))

# ---------- C. 中間便：送りは前向き、迎えは逆算、間に待機 ----------
i = {}
mid = plan("12:00", MID, DRIVE, S(True), LEGS, "13:30", i)
check("C 送りの2人は前向きのまま", mid[:2] == ["12:10", "12:22"], str(mid))
check("C 迎えは到着から逆算", mid[2:] == ["13:06", "13:18"], str(mid))
check("C 待機は32分", i.get("wait") == 32, str(i))
check("C 間に合っているので警告は出さない", i.get("short") is False, str(i))
check("C 待機は「最後に降ろした人」と「最初に乗せる人」の間",
      m(mid[2]) - m(mid[1]) == 10 + 2 + 32, str(mid))

# ---------- D. 迎え便：待機は出発の前 ----------
PIC = [pick("C"), pick("D")]
i = {}
p2 = plan("08:30", PIC, 30, S(True), [10, 10], "09:30", i)
# 逆算: 帰り 30-20=10分。09:30-10=09:20 → D 着 09:18 → 10分前 09:08 → C 着 09:06
check("D 迎え便は到着から逆算", p2 == ["09:06", "09:18"], str(p2))
fw = plan("08:30", PIC, 30, S(False), [10, 10])
check("D 前向きなら早く着いてしまう", fw == ["08:40", "08:52"], str(fw))
check("D 待機は出発の前に出る（26分）", i.get("wait") == 26, str(i))

# ---------- E. 逆算した便は、必ず到着時刻ちょうどに戻る ----------
def back_home(times, stops, legs, drive, arrive, st):
    """最後の立ち寄り + 乗降 + 帰りの区間 = 到着 になるか。"""
    ret = drive - sum(legs)
    last = stops[-1]
    stay = st["stop_minutes_wc"] if last.get("is_wheelchair") else st["stop_minutes"]
    return m(times[-1]) + stay + ret == m(arrive)


check("E 中間便は13:30ちょうどに戻る",
      back_home(mid, MID, LEGS, DRIVE, "13:30", S(True)))
check("E 迎え便は09:30ちょうどに戻る",
      back_home(p2, PIC, [10, 10], 30, "09:30", S(True)))

# いろいろな形で、必ず到着ちょうどに戻ること
_cases = 0
for nd in range(0, 4):
    for np_ in range(1, 4):
        stops = [drop("d%d" % k) for k in range(nd)] + \
                [pick("p%d" % k, k == 0) for k in range(np_)]
        legs = [7 + k for k in range(len(stops))]
        drive = sum(legs) + 9
        st = S(True)
        i2 = {}
        t = plan("09:00", stops, drive, st, legs, "13:00", i2)
        if not i2.get("back"):
            continue           # 間に合わない形は E の対象外
        _cases += 1
        if not back_home(t, stops, legs, drive, "13:00", st):
            ng.append("E 到着ちょうどに戻らない: %s %s" % (t, (nd, np_)))
            break
else:
    ok += 1
check("E 見た形が十分ある", _cases >= 8, str(_cases))

# ---------- F. 間に合わない日は前向きに倒す ----------
i = {}
tight = plan("12:00", MID, DRIVE, S(True), LEGS, "12:40", i)
check("F 間に合わないと前向きの時刻に戻る", tight == base, str(tight))
check("F 警告を立てる", i.get("short") is True, str(i))
check("F 逆算していないので back は偽", i.get("back") is False, str(i))
check("F 待機は0にする", i.get("wait") == 0, str(i))
# ちょうど間に合う（待機0）は逆算として扱う
i = {}
just = plan("12:00", MID, DRIVE, S(True), LEGS, "12:58", i)
check("F ちょうど間に合う日は逆算あつかい",
      i.get("back") is True and i.get("wait") == 0, str(i))
check("F そのとき時刻は前向きと同じ", just == base, "%s / %s" % (just, base))

# ---------- G. 車いす・1件だけ ----------
W = [drop("A"), pick("C", True)]
i = {}
w = plan("12:00", W, 30, S(True), [10, 10], "13:00", i)
# 帰り 30-20=10分。13:00-10=12:50 → 車いす5分 → C 着 12:45
check("G 車いすの乗降5分が効く", w[1] == "12:45", str(w))
one = plan("08:00", [pick("C")], 20, S(True), [10], "09:00", i)
# 帰り 20-10=10。09:00-10=08:50 → 乗降2分 → 08:48
check("G 立ち寄り1件でも動く", one == ["08:48"], str(one))
check("G 立ち寄りが無ければ空", plan("08:00", [], 20, S(True), [], "09:00") == [])
check("G 出発が空なら空のまま",
      plan("", MID, DRIVE, S(True), LEGS, "13:30") == [None] * 4)

# ---------- H. 区間の時間が無いとき（等分）----------
i = {}
eq = plan("12:00", MID, 50, S(True), None, "13:30", i)
check("H 等分でも逆算する", i.get("back") is True, str(i))
check("H 等分でも到着ちょうどに戻る",
      m(eq[-1]) + 2 + (50 - 4 * 10) == m("13:30"), str(eq))

# ---------- I. 便の設定が「到着」を持ち回る ----------
t = norm([{"name": "中間便", "depart": "12:00", "arrive": "13:30",
           "pickup_units": [2], "dropoff_units": [1]}], 2)
check("I 到着を持ち回る", t[0].get("arrive") == "13:30", str(t[0]))
t2 = norm([{"name": "迎え便", "depart": "08:30", "arrive": "930",
            "pickup_units": [1], "dropoff_units": []}], 1)
check("I 形が違う到着は空に倒す", t2[0].get("arrive") == "", str(t2[0]))
t3 = norm([{"name": "送り便", "depart": "16:00",
            "pickup_units": [], "dropoff_units": [1]}], 1)
check("I 到着が無ければ空", t3[0].get("arrive") == "", str(t3[0]))

# ---------- J. 呼び出し側・設定の読み書き ----------
check("J 設定の読みにトグルがある", '"back_plan": bool(s.get("back_plan"))' in SRC)
check("J 既定は逆算しない", '"back_plan": False,' in SRC)
check("J 設定の保存にトグルがある",
      '"back_plan": bool(data.get("back_plan"))' in SRC)
# ★2026-09-08: ここは元々「trip.get("arrive") が9個あること」で見ていた。
#   別の直しで1つ増えるたびに落ちる、意味のない検査だった（実際に落ちた）。
#   数ではなく【予定時刻を出す呼び出しが、全部そろって到着を渡しているか】を見る。
def _args_of(text, i):
    """text[i] から始まる呼び出しの、かっこの中を返す。"""
    j = text.index("(", i)
    d, k = 0, j
    while k < len(text):
        if text[k] == "(":
            d += 1
        elif text[k] == ")":
            d -= 1
            if d == 0:
                return text[j + 1:k]
        k += 1
    return ""


_calls, _p = [], 0
while True:
    _p = SRC.find("_soge_planned_times(", _p)
    if _p < 0:
        break
    if not SRC[max(0, _p - 4):_p].strip().endswith("def"):   # 定義そのものは数えない
        _calls.append(_args_of(SRC, _p))
    _p += 1
check("J 予定時刻を出す呼び出しがある", len(_calls) >= 5, str(len(_calls)))
check("J どの呼び出しも到着を渡している",
      _calls and all("arrive" in a for a in _calls),
      str([a[:50] for a in _calls if "arrive" not in a]))
check("J 引き直しは便の定義から到着を引く", "_arrive_of.get(" in SRC)
_bw = _top_block(SRC, "soge_build_week") or ""
check("J 配車表は間に合わない便を警告する",
      "に間に合いません" in _bw and '_pinf.get("short")' in _bw)
check("J 配車表は待機を返す", '"wait_minutes": _pinf.get("wait", 0),' in _bw)

# ★9/2 と 9/8 に入れた歯止めが残っていること
_mg = _top_block(SRC, "_soge_merge_day") or ""
check("J 運転手の歯止めは残っている",
      'head["driver_name"] = day.get("driver_name")' in _mg)
_mt = _top_block(SRC, "soge_materialize_day") or ""
check("J 過ぎた日の歯止めは残っている",
      'return {"built": False, "reason": "past"}' in _mt)

print("h_backplan: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
