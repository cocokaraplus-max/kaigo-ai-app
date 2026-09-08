# h_pastadmin.py  —  soge-past-admin-v1 / soge-guard4-v1 の台
#
# 置き場所: ~/dev/kaigo-ai-app/h_pastadmin.py
# 使い方  : cd ~/dev/kaigo-ai-app && python3 h_pastadmin.py
#
# ★app.py を【その場で読んで】切り出す。写しを持たないので、
#   app.py を直したあとに流し直せば、必ず今の中身を見る。
#
# なぜこの台があるか
#   「過ぎた日の記録は管理者だけが直せる」の 403 は、DEVでも本番でも
#   実物を出せなかった。管理者でないアカウントが作れないため
#   （職員の登録がLINE紐付けになっている）。
#   だから【判定そのもの】と【ガードが全ルートに残っていること】を
#   機械で固定して、壊れたら次に気づけるようにする。
#
# 何を確かめるか
#   A. _soge_past_admin_ok の判定
#      過ぎた日＋管理者 → 通す ／ 過ぎた日＋一般 → 断る
#      今日・これからの日 → 誰でも通す
#      日付が読めない → 断る ／ 権限を読めない（例外） → 断る（fail closed）
#   B. 打刻・修正の口すべてに、このガードが残っていること
#      ★とくに /run/depart と /run/return。2026-09-02 に
#        この2本だけガードが無く、日をまたぐと昨日の便に今日の時刻が入った。
#   C. 断るときは 403 と past_admin を返していること（画面がこれを見て理由を出す）
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")

# ガードが要る口（関数名） — 過ぎた日に【書く】ものだけ
GUARDED = [
    "api_soge_run_arrive",        # 到着
    "api_soge_run_stop_edit",     # 立ち寄りの時刻を直す
    "api_soge_run_move",          # 並べ替え
    "api_soge_run_depart",        # ★出発（2026-09-02 に抜けていた）
    "api_soge_run_day_edit",      # 便を直す
    "api_soge_run_extra_create",  # 臨時便を作る
    "api_soge_run_extra_add_stop",
    "api_soge_run_extra_delete",
    "api_soge_run_return",        # ★帰着（2026-09-02 に抜けていた）
]


def _top_block(text, name):
    """字下げの無い行が来たら関数の終わり、で切り出す。

    ★「次の @app.route まで」で切ると、後ろに口を足しただけで切れ目が動く。
    """
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

blk = _top_block(SRC, "_soge_past_admin_ok")
if blk is None:
    print("★_soge_past_admin_ok が見つかりません。")
    sys.exit(1)

# ★切り出しの道具は、写したら1回は切れた中身を見る、と決めてある。
#   目で見られないので、形をここで確かめる。
assert blk.startswith("def _soge_past_admin_ok("), "★切り出しの頭がおかしい"
assert blk.count("\ndef ") == 0, "★次の関数まで飲み込んでいる"
assert "is_admin_user" in blk, "★権限を見ていない"

ok = 0
ng = []


def check(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
    else:
        ng.append("%s  %s" % (name, extra))


# ---------- 台のまわり（本物のDBは使わない） ----------
JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
TOMORROW = (datetime.now(JST) + timedelta(days=1)).strftime("%Y-%m-%d")


def build(admin_returns):
    """_soge_past_admin_ok を、差し替えた is_admin_user の上で動かす。

    admin_returns … True / False / "boom"（例外を投げる）
    """
    def _is_admin(supabase, f_code, my_name):
        if admin_returns == "boom":
            raise RuntimeError("権限テーブルが読めない")
        return admin_returns

    ns = {
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "_soge_jst": lambda: JST,
        "is_admin_user": _is_admin,
    }
    exec(compile(blk, APP, "exec"), ns)      # noqa: S102
    return ns["_soge_past_admin_ok"]


F_ADMIN = build(True)
F_PLAIN = build(False)
F_BOOM = build("boom")
S, C, N = None, "DEMO001", "テスト職員"

# ---------- A. 判定 ----------
check("A 過ぎた日＋管理者 → 通す", F_ADMIN(S, C, YESTERDAY, N) is True)
check("A 過ぎた日＋一般 → ★断る", F_PLAIN(S, C, YESTERDAY, N) is False)
check("A 今日＋一般 → 通す（現場の流れを変えない）",
      F_PLAIN(S, C, TODAY, N) is True)
check("A これからの日＋一般 → 通す", F_PLAIN(S, C, TOMORROW, N) is True)
check("A ずっと前の日＋一般 → 断る", F_PLAIN(S, C, "2020-01-01", N) is False)

# 今日・未来は権限を見に行かない（見に行っていたら例外で落ちるはず）
check("A 今日は権限を見に行かない", F_BOOM(S, C, TODAY, N) is True)
check("A これからの日も見に行かない", F_BOOM(S, C, TOMORROW, N) is True)

# ---------- A'. 読めないときは断る（fail closed） ----------
check("A' 権限を読めない（例外）→ ★断る", F_BOOM(S, C, YESTERDAY, N) is False)
for bad in (None, "", "2026-09", "きのう", "20260907", 20260907):
    check("A' 日付が読めない(%r) → 断る" % (bad,),
          F_PLAIN(S, C, bad, N) is False, repr(bad))

# ---------- A''. ★スラッシュの日付は、いまのところ すり抜ける ----------
#   len(d) == 10 しか見ていないので、"2026/08/01" は形が違っても長さが合う。
#   そのうえ文字で比べているため "2026/" > "2026-"（/ は - より大きい）になり、
#   過ぎた日なのに【今日より後】と判定されて通ってしまう。
#   date を画面から受け取る口（api_soge_run_merge / api_soge_run_extra_create）
#   に手で投げれば届く。画面は必ず YYYY-MM-DD を送るので、普通は起きない。
#   → 直したら（marker soge-past-admin-v2）、ここは assert に変わる。
_Y = TODAY[:4]
_SLASH = [_Y + "/01/01", _Y + "-13-45"]   # スラッシュ／在りえない日付
if "soge-past-admin-v2" in blk:
    for bad in _SLASH:
        check("A'' スラッシュの日付(%s) → 断る" % bad,
              F_PLAIN(S, C, bad, N) is False)
else:
    _leak = [b for b in _SLASH if F_PLAIN(S, C, b, N) is not False]
    if _leak:
        print("  ⚠ まだ直していない穴: 形の違う日付が過ぎた日の歯止めを"
              "すり抜けます %s" % _leak)
        print("    （len(d)==10 しか見ておらず、文字で比べると "
              "'2026/' > '2026-'、'2026-1' > '2026-0' になるため）")
        print("    → patch_soge_past_admin_v2.py を流すと直ります")
# 0埋めなしの日付。長さが10に足りないので、v1 でも v2 でも断る側に倒れる
# （v2 では読めたうえで形をそろえるので、過去日なら過去日として断る）。
check("A' 0埋めなしの過去日 → 断る", F_PLAIN(S, C, "2026-8-1", N) is False)

# 日付の頭10文字だけを見る（タイムスタンプで来ても動く）
check("A 日付にゴミが付いていても頭10文字で見る",
      F_PLAIN(S, C, YESTERDAY + "T09:00:00+09:00", N) is False)
check("A 同上・管理者なら通す",
      F_ADMIN(S, C, YESTERDAY + "T09:00:00+09:00", N) is True)

# ---------- B. ガードが全ルートに残っているか ----------
missing = []
no403 = []
for fn in GUARDED:
    body = _top_block(SRC, fn)
    if body is None:
        missing.append(fn + "（関数が無い）")
        continue
    if "_soge_past_admin_ok" not in body:
        missing.append(fn)
        continue
    if "403" not in body or "past_admin" not in body:
        no403.append(fn)
check("B 書く口すべてにガードがある（%d本）" % len(GUARDED),
      not missing, "抜けている: %s" % missing)
check("C 断るときは 403 と past_admin を返す", not no403, "足りない: %s" % no403)

# ★2026-09-02 に抜けていた2本は、名指しでも見る（また消えたらここで気づく）
for fn in ("api_soge_run_depart", "api_soge_run_return"):
    b = _top_block(SRC, fn) or ""
    check("B ★%s にガードがある" % fn, "_soge_past_admin_ok" in b)

# ---------- D. 画面側（親切の出し分け）が残っているか ----------
RUN = os.path.join(HERE, "templates", "soge_run.html")
if os.path.exists(RUN):
    h = open(RUN, encoding="utf-8").read()
    check("D 画面は can_edit を見る", "d.can_edit === true" in h)
    check("D 分からないときは直せない扱い", "if (!d.past) return true;" in h)
    check("D 帰着・出発のボタンを止める",
          "[data-dep],[data-ret]" in h.replace(" ", ""))
    check("D 理由を出す", "過ぎた日の記録は管理者だけが直せます" in h)
else:
    print("  … templates/soge_run.html が無いので D は飛ばしました")

print("h_pastadmin: %d 件 OK" % ok)
if ng:
    print("★NG")
    for x in ng:
        print("  -", x)
    sys.exit(1)
