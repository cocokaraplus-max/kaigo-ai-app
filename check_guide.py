# -*- coding: utf-8 -*-
"""
案内役の点検スクリプト  guide-check-v1

【何のためのものか】
  案内文（guide_integration.py）は【手で書いた文章】。
  機能を足しても勝手には更新されない。手引書(manual.html)が置いていかれたのと
  同じことが、放っておけばまた起きる。

  文章の中身が古いかどうかは機械には分からない。
  でも【構造のズレ】は全部見つけられる。それをやるのがこれ。

【いつ走らせるか】
  ・画面を足したとき
  ・入力欄の id を変えたとき
  ・URL を変えたとき・画面を消したとき
  ・本番へマージする前（いちばん大事）

【使い方】
  python3 check_guide.py                  … 点検する
  python3 check_guide.py --new            … 案内がまだ無い画面だけ出す
  python3 check_guide.py --quiet          … 問題があるときだけ出す

  リポジトリの一番上（app.py のある所）で走らせること。

【終了コード】
  0 … 問題なし     1 … 直すべきものがある     2 … 走れなかった
"""
import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ルートを集めるファイル。増えたらここに足す。
ROUTE_FILES = [
    "app.py",
    "self_eval_integration.py",
    "patient_hub_integration.py",
    "patient_info_integration.py",
    "patient_info_import_integration.py",
    "monitoring_integration.py",
]

# 案内が要らない画面。ここに入れておけば「案内が無い」と言われない。
#   ★利用者に渡す画面は _NO_GUIDE（guide_integration.py 側）でも止めている。
#     こちらは「わざと書いていない」ことの記録。
SKIP_PREFIX = (
    "/api/", "/static/", "/dev", "/admin_auth", "/admin_2fa",
)
SKIP_EXACT = {
    # 印刷用（見るだけ・案内する所が無い）
    "/print_pdf", "/print_preview", "/renraku/print", "/soge/print",
    "/admin/jisseki/print", "/photo/sheet", "/admin/assessment_sheet",
    # ログイン・登録まわり
    "/login", "/logout", "/register", "/invite", "/setup", "/onboard",
    "/onboard/done", "/reactivate", "/pricing", "/reset_password",
    "/new_password", "/staff_start", "/dev_login",
    # 利用者にタブレットを渡す画面（出してはいけない）
    "/self-eval/run", "/self-eval/locked",
    # base.html を継承していないので、そもそも届かない
    "/timecard",
    # その他
    "/faq", "/guide_ledger", "/history", "/case_records", "/mapping",
}


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------
# 案内文を読む（実行せずに ast で値だけ取り出す）
# ------------------------------------------------------------
def load_guide():
    src = read(os.path.join(HERE, "guide_integration.py"))
    tree = ast.parse(src)
    screens = checks_used = no_guide = None
    checks_reg = set()
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        name = getattr(n.targets[0], "id", "")
        if name == "SCREENS":
            screens = ast.literal_eval(n.value)
        elif name == "_NO_GUIDE":
            no_guide = set(ast.literal_eval(n.value))
        elif name == "_CHECKS":
            checks_reg = {k.value for k in n.value.keys}
    if screens is None:
        raise SystemExit("!! SCREENS が読めません")
    checks_used = set()
    for v in screens.values():
        checks_used |= set(v.get("checks", []))
    return screens, checks_used, checks_reg, (no_guide or set())


# ------------------------------------------------------------
# 実在するルートを集める
# ------------------------------------------------------------
def load_routes():
    routes = set()
    missing = []
    for f in ROUTE_FILES:
        p = os.path.join(HERE, f)
        if not os.path.exists(p):
            missing.append(f)
            continue
        routes |= set(re.findall(r"@app\.route\(\s*['\"]([^'\"]+)['\"]", read(p)))
    return routes, missing


# ------------------------------------------------------------
# テンプレートの id を集める
# ------------------------------------------------------------
def template_ids():
    """テンプレート名 → その中にある id の集合"""
    d = os.path.join(HERE, "templates")
    out = {}
    if not os.path.isdir(d):
        return out
    for f in os.listdir(d):
        if not f.endswith(".html") or ".bak" in f:
            continue
        out[f] = set(re.findall(r'\bid="([^"]+)"', read(os.path.join(d, f))))
    return out


def route_to_template():
    """URL → テンプレート名。render(...) の直前の @app.route を対応させる。"""
    import bisect
    m = {}
    for f in ROUTE_FILES:
        p = os.path.join(HERE, f)
        if not os.path.exists(p):
            continue
        s = read(p)
        pos = [(x.start(), x.group(1))
               for x in re.finditer(r"@app\.route\(\s*['\"]([^'\"]+)['\"]", s)]
        starts = [x[0] for x in pos]
        for x in re.finditer(r"\brender(?:_template)?\(\s*['\"]([\w.]+\.html)['\"]", s):
            i = bisect.bisect_right(starts, x.start()) - 1
            if i >= 0:
                m.setdefault(pos[i][1], x.group(1))
    return m


# ------------------------------------------------------------
# 点検
# ------------------------------------------------------------
def main():
    argv = sys.argv[1:]
    only_new = "--new" in argv
    quiet = "--quiet" in argv

    if not os.path.exists(os.path.join(HERE, "app.py")):
        print("!! app.py が見つかりません。リポジトリの一番上で走らせてください。")
        return 2

    screens, used, reg, no_guide = load_guide()
    routes, missing_files = load_routes()
    r2t = route_to_template()
    tids = template_ids()

    problems = []   # 直すべきもの
    notes = []      # 知らせるだけ

    if missing_files:
        notes.append("読めなかったファイル: " + "、".join(missing_files))

    lower_routes = {r.lower() for r in routes}

    # ① 案内のキーが実在するURLか
    #    ★1文字違うだけで、その画面には永久に案内が出ない。しかもエラーも出ない。
    for k in sorted(screens):
        if k not in lower_routes:
            problems.append("案内のキー %s は、実在しないURLです" % k)

    # ② 判定の名前が登録されているか
    for c in sorted(used - reg):
        problems.append("判定 '%s' が使われていますが、_CHECKS に登録されていません" % c)
    for c in sorted(reg - used):
        notes.append("判定 '%s' は登録されていますが、どの画面でも使われていません" % c)

    # ③ 案内文の欄 id が、その画面にまだ在るか
    #    ★入力欄の作りを変えると、ここが黙って効かなくなる。
    for k in sorted(screens):
        fields = screens[k].get("fields", {})
        if not fields:
            continue
        tpl = r2t.get(k)
        if not tpl:
            notes.append("%s のテンプレートが特定できず、欄の確認ができません" % k)
            continue
        have = tids.get(tpl)
        if have is None:
            notes.append("%s のテンプレート %s が見つかりません" % (k, tpl))
            continue
        for fid in fields:
            if fid not in have:
                problems.append("%s の欄 '%s' は %s にもう在りません" % (k, fid, tpl))

    # ④ 案内がまだ無い画面（画面を出すルートだけ）
    new = []
    for r in sorted(routes):
        if r.lower() in screens or r in no_guide:
            continue
        if r in SKIP_EXACT or r.startswith(SKIP_PREFIX):
            continue
        if "<" in r:                      # /chat/<room_id> のような可変部分
            continue
        if r not in r2t:                  # 画面を描かないルートは対象外
            continue
        new.append((r, r2t[r]))

    # ⑤ 形が欠けていないか
    need = ("title", "what", "flow", "fields", "checks")
    for k in sorted(screens):
        for key in need:
            if key not in screens[k]:
                problems.append("%s に '%s' がありません" % (k, key))

    # ---------------- 出力 ----------------
    if only_new:
        print("案内がまだ無い画面: %d" % len(new))
        for r, t in new:
            print("   %-26s %s" % (r, t))
        return 0

    if quiet and not problems:
        return 0

    print("=" * 58)
    print(" 案内役の点検  guide-check-v1")
    print("=" * 58)
    print(" 案内のある画面 %d ／ 集めたルート %d ／ 判定 %d"
          % (len(screens), len(routes), len(reg)))
    print()

    if problems:
        print(" ★直すべきもの %d 件" % len(problems))
        for p in problems:
            print("   ・" + p)
    else:
        print(" 直すべきもの: なし")
    print()

    if new:
        print(" 案内がまだ無い画面 %d 件（足すかどうかは人が決める）" % len(new))
        for r, t in new[:20]:
            print("   ・%-26s %s" % (r, t))
        if len(new) > 20:
            print("   ・…ほか %d 件（--new で全部出ます）" % (len(new) - 20))
        print()

    if notes:
        print(" 参考")
        for n in notes:
            print("   ・" + n)
        print()

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
