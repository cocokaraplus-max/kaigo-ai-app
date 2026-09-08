# h_runplan.py  —  soge-run-plan-edit-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_runplan.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_runplan.py
#
# ★app.py と templates/soge_run.html を【その場で読んで】切り出す。
#
# 何を確かめるか
#   A. 予定の受け取り方（HH:MM だけ通す／空で消せる／おかしい形は断る）
#   B. 予定を送っていないときは、予定に触らない
#   C. 打刻(arrived_at)の道を1行も変えていない
#   D. 過ぎた日のガードと「手で直した跡」が、この口に残っている
#   E. 画面：押す場所が2つある／送るのは plan／打刻の送り方は変えていない
#   F. 画面：入力の受け皿が1つだけあり、貯める仕掛けには乗せていない
#   G. 画面の <script> が文法として通る（node があるときだけ）
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
RUN = os.path.join(HERE, "templates", "soge_run.html")


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


for f in (APP, RUN):
    if not os.path.exists(f):
        print("★%s が見つかりません。~/dev/kaigo-ai-app/ で流してください。" % f)
        sys.exit(1)
SRC = open(APP, encoding="utf-8").read()
RUNSRC = open(RUN, encoding="utf-8").read()

blk = _top_block(SRC, "api_soge_run_stop_edit")
if blk is None or "soge-run-plan-edit-v1" not in SRC:
    print("★soge-run-plan-edit-v1 がまだ当たっていません。"
          "patch_soge_run_plan_edit_v1.py を先に流してください。")
    sys.exit(1)
assert blk.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"

# ---- 予定を受け取る所だけを切り出して、そのまま動かす ----
#   ★書き写さない。app.py の【その行】を動かす。
i = blk.find('        if "plan" in data:')
j = blk.find('        if "time" in data:')
assert 0 <= i < j, "★予定の受けが、打刻の受けの前に見つからない"
piece = blk[i:j].rstrip() + "\n"
body = "\n".join(("    " + ln[8:]) if ln.strip() else ""
                 for ln in piece.splitlines())
_src = "def _plan(data):\n    upd = {}\n" + body + "\n    return upd\n"

_ns = {"jsonify": lambda d: ("NG", d)}
exec(compile(_src, "h_runplan", "exec"), _ns)      # noqa: S102
plan = _ns["_plan"]

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


def is_ng(r):
    """400 で断ったか。"""
    return isinstance(r, tuple) and r[1] == 400


# ---------- A. 受け取り方 ----------
for good in ("00:00", "08:30", "12:05", "23:59", "09:00"):
    r = plan({"plan": good})
    check("A %s は通る" % good, r.get("planned_at") == good, str(r))

check("A 前後の空白は落とす", plan({"plan": "  08:30  "}).get("planned_at") == "08:30")
check("A 空なら予定を消す", plan({"plan": ""}).get("planned_at", "x") is None)
check("A None でも予定を消す", plan({"plan": None}).get("planned_at", "x") is None)
check("A 空白だけでも消す", plan({"plan": "   "}).get("planned_at", "x") is None)

for bad in ("0830", "8:30", "08:3", "08-30", "aa:bb", "08:xx", "1:2:3",
            "24:00", "25:00", "08:60", "08:99", "-1:00", "０８:３０"):
    check("A %r は断る" % bad, is_ng(plan({"plan": bad})), str(plan({"plan": bad})))

# ---------- B. 送っていないときは触らない ----------
check("B plan が無ければ予定に触らない", "planned_at" not in plan({}))
check("B 打刻だけ送っても予定に触らない",
      "planned_at" not in plan({"time": "08:30"}))
check("B 休みだけ送っても予定に触らない",
      "planned_at" not in plan({"absent": True}))

# ---------- C. 打刻の道は変えていない ----------
check("C 打刻の受けが残っている", 'if "time" in data:' in blk)
check("C 打刻は arrived_at に書く", 'upd["arrived_at"] = _soge_at_iso(' in blk)
check("C 予定は打刻を書かない", 'arrived_at' not in piece, piece[:80])
check("C 予定は休みも触らない", 'is_absent' not in piece)
check("C 予定の受けは打刻より前", i < j)

# ---------- D. 歯止め ----------
check("D 過ぎた日のガードが残っている", "_soge_past_admin_ok" in blk)
check("D 403 で断る", '"past_admin": True' in blk)
check("D 手で直した跡を残す", 'upd = {"edited_at"' in blk)

# ---------- E/F. 画面 ----------
check("E 一覧から押せる", 'data-plan="\' + escA(s.id)' in RUNSRC)
check("E 運転中から押せる", '">予定を直す</button>' in RUNSRC)
check("E 予定として送る", "{ stop_id: id, plan: t }" in RUNSRC)
check("E 打刻の送り方は変えていない",
      RUNSRC.count("{ stop_id: id, time: t }") == 1,
      str(RUNSRC.count("{ stop_id: id, time: t }")))
check("F 受け皿は1つ（定義と配線で2回出る）",
      RUNSRC.count("openPlanEditor") == 2, str(RUNSRC.count("openPlanEditor")))
check("F 打刻の受け皿はそのまま",
      RUNSRC.count("function openTimeEditor(") == 1)
_pe = RUNSRC[RUNSRC.find("function openPlanEditor("):]
_pe = _pe[:_pe.find("function openTimeEditor(")]
check("F 予定は貯めない（srqAdd を呼ばない）", "srqAdd" not in _pe)
check("F 断られたら止まる", "srRefused" in _pe)
check("F 触っただけでは送らない", "if (t === (initial || ''))" in _pe)
check("F ［決定］［やめる］がある", "'決定'" in _pe and "'やめる'" in _pe)

# ---------- G. <script> の文法（node があるときだけ） ----------
try:
    subprocess.run(["node", "--version"], capture_output=True, check=True)
    has_node = True
except Exception:
    has_node = False
if has_node:
    js = "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                              RUNSRC, re.S))
    js = re.sub(r"\{\{.*?\}\}", '"J"', js, flags=re.S)
    js = re.sub(r"\{%.*?%\}", "", js, flags=re.S)
    p = os.path.join(HERE, ".h_runplan_check.js")
    with open(p, "w", encoding="utf-8") as fp:
        fp.write(js)
    r = subprocess.run(["node", "--check", p], capture_output=True)
    os.remove(p)
    check("G <script> の文法が通る", r.returncode == 0,
          (r.stderr or b"").decode("utf-8", "replace")[:300])
else:
    print("  … node が無いので G は飛ばしました")

print("h_runplan: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
