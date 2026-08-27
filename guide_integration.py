"""
TASUKARU 画面の案内役  guide-v1

【何のためのものか】
  TASUKARU は画面が79枚あるのに、手引書(manual.html)が触れているのは22項目。
  機能を足すたびに手引書が置いていかれる。
  そこで「画面ごとの案内文」を【この1か所】に集め、そこから

    ① 入力欄の横に出る「？」（吹き出し）
    ② 右上の「？」を押すと開くカード（この画面は何をする所か＋いま足りないこと）
    ③ 手引書の追記のもとネタ

  の3つを出す。テンプレート79枚には手を入れない。
  直すときは、このファイルの文章だけを直す。

【絶対に守ること】
  ★このモジュールは【データを読むだけ】。
    insert / update / delete / upsert / rpc を書いてはいけない。
    案内役が利用者の記録を書き換えたら、誰も気づけない事故になる。
    確認スクリプトでも、この5語が出てこないことを機械的に見ている。

  ★checks（いま足りないこと）は【必ず件数を返す軽い問い合わせ】にすること。
    どの画面を開いても走るので、重いクエリを置くと全体が遅くなる。

【増やし方】
  SCREENS に画面を1つ足すだけ。
  キーは【URLのパスまるごと】（"/input" "/admin/jisseki"）。
  ★先頭の1語だけにしてはいけない。/admin の下が全部おなじ名前になる。
  "fields" のキーは、その画面の HTML にある id をそのまま書く。
  画面に無い id を書いても無視される（確認スクリプトが警告してくれる）。

提供API:
  GET /api/guide/screen?path=/input   … 画面の案内一式（読むだけ）
"""

from flask import request, jsonify, session
from functools import wraps
from datetime import datetime, timedelta, time as dt_time


# ============================================================
# 案内文の置き場
# ============================================================
#   キーは【URLのパスまるごと】。先頭の1語だけにしてはいけない。
#   ★理由: /admin ・/admin/jisseki ・/admin/timecard … が全部おなじ名前になり、
#     8画面が区別できなくなる。ここで一度これを間違えた。
#
#   探し方は「完全一致 → いちばん長い前方一致」の順（下の _match_screen）。
#     /chat/<部屋のid> は "/chat" に当たる（部屋ごとに書かなくてよい）
#     /admin/jisseki は "/admin" ではなく "/admin/jisseki" に当たる
#
#   title  … 画面の名前
#   what   … この画面は何をする所か（1〜2文）
#   flow   … だいたいの手順（3〜5個）
#   fields … 入力欄の id → {"t": 見出し, "d": 説明}
#   checks … 「次は何をしたらいい？」の判定名（下の _CHECKS に実体を書く）

SCREENS = {

    # --------------------------------------------------------
    # 記録入力
    # --------------------------------------------------------
    "/input": {
        "title": "記録入力",
        "what": "利用者ごとのケース記録を書く画面です。"
                "キーボードで打つほかに、話した声から作ることもできます。",
        "flow": [
            "利用者を選ぶ",
            "内容を書く（マイクで話してもOK）",
            "カテゴリを選ぶ",
            "保存",
        ],
        "fields": {
            "patient-search": {
                "t": "誰の記録か",
                "d": "ひらがな・漢字・カルテ番号のどれでも探せます。"
                     "「やまだ」「山田」「001」のどれでも出ます。"
                     "選ぶと、下に名前が出て確定します。",
            },
            "record-date": {
                "t": "いつの記録か",
                "d": "今日の日付が最初から入っています。"
                     "前の日のぶんを後から書くときだけ、ここを変えてください。",
            },
            "photo-input": {
                "t": "写真・動画",
                "d": "1件の記録に5つまで付けられます。"
                     "保存すると、ケース記録に一緒に残ります。",
            },
            "inp-v-result": {
                "t": "音声からの文字起こし",
                "d": "マイクで話した内容を、AIが文字にしたものです。"
                     "ここで直してから「記録に追加する」を押すと、下の「内容」に入ります。"
                     "話し言葉のままで大丈夫です。",
            },
            "cat-trigger": {
                "t": "カテゴリ",
                "d": "後から探すときの目印です。"
                     "「休み連絡」「追加利用連絡」を選ぶと日付の欄が出てきて、"
                     "保存するとカレンダーにも自動で入ります（二重入力は要りません）。",
            },
            "leave-reporter-type": {
                "t": "誰から聞いたか",
                "d": "本人・家族・ケアマネ・その他から選びます。"
                     "誰から聞いた話かが記録に残るので、後で確認しやすくなります。",
            },
            "leave-date-start": {
                "t": "休み期間",
                "d": "続けて休む場合は、ここに始まりの日と終わりの日を入れます。"
                     "1日だけなら、同じ日を両方に入れてください。"
                     "飛び飛びの日は、下の欄で1日ずつ足します。",
            },
            "leave-multi-input": {
                "t": "飛び飛びのお休み日",
                "d": "続いていない休みは、ここで1日ずつ足します。"
                     "足した日それぞれにカレンダーの「お休み」ができ、"
                     "ケース記録は1件にまとまります。",
            },
            "leave-reason": {
                "t": "お休みの理由",
                "d": "聞いた言葉のままで大丈夫です。"
                     "「発熱のため」「通院のため」など短くて構いません。",
            },
            "extra-date-start": {
                "t": "追加利用日",
                "d": "いつもの曜日以外に来られる日を入れます。"
                     "続けて来られる場合は始まりの日と終わりの日を。"
                     "飛び飛びの日は、下の欄で1日ずつ足します。",
            },
            "extra-multi-input": {
                "t": "飛び飛びの追加利用日",
                "d": "続いていない追加利用は、ここで1日ずつ足します。"
                     "足した日それぞれにカレンダーの「追加利用」ができます。",
            },
            "extra-reason": {
                "t": "追加利用の理由",
                "d": "任意です。「家族の都合で」「リハビリ強化のため」など。",
            },
            "content-area": {
                "t": "内容",
                "d": "見たこと・聞いたことを、そのまま書いてください。"
                     "「昼食を半分、むせ込みなし」のように短くて構いません。"
                     "うまくまとめようとしなくて大丈夫です。",
            },
            "must-read-btn": {
                "t": "閲覧必須にする",
                "d": "全員に必ず読んでほしい記録に付けます。"
                     "付けるとTOP画面で目立つように出ます。"
                     "毎回付けると目立たなくなるので、本当に大事なときだけに。",
            },
        },
        "checks": ["today_no_record", "today_missing_records"],
    },

    # --------------------------------------------------------
    # TOP（入り口）  ※入力欄が無いのでカードだけ
    # --------------------------------------------------------
    "/top": {
        "title": "TOP",
        "what": "今日の様子がひと目でわかる入り口です。"
                "今日のケース記録、自分に来ているタスク、今日が誕生日の方が並びます。",
        "flow": [
            "上のお知らせ（閲覧必須・タスク）を見る",
            "下のメニューから、やりたいことの画面へ行く",
            "迷ったら、どの画面でも右上の「?」を押す",
        ],
        "fields": {},
        "checks": ["unread_must_read", "my_tasks_overdue", "today_no_record"],
    },

    # --------------------------------------------------------
    # 日々の記録  ※一覧画面
    # --------------------------------------------------------
    "/daily_view": {
        "title": "日々の記録",
        "what": "1日ぶんのケース記録を、利用者ごとにまとめて読む画面です。"
                "AIがその日の要約を作って、読み上げることもできます。",
        "flow": [
            "見たい日を選ぶ（左右の矢印で前の日・次の日）",
            "利用者ごとに開いて読む",
            "直したい記録は、その場で「編集」から直せる",
        ],
        "fields": {},
        "checks": ["unread_must_read", "today_missing_records"],
    },

    # --------------------------------------------------------
    # 掲示板  ※一覧画面
    # --------------------------------------------------------
    "/board": {
        "title": "掲示板",
        "what": "職員どうしの連絡を貼る場所です。"
                "利用者ごとの記録ではなく、事業所ぜんたいへのお知らせに使います。",
        "flow": [
            "「未読」で自分がまだ読んでいないものを確認する",
            "読んだら開く（開くと既読になります）",
            "書くときは右上の鉛筆から",
        ],
        "fields": {},
        "checks": [],
    },

    # --------------------------------------------------------
    # タスクリスト  ※一覧画面
    # --------------------------------------------------------
    "/tasks": {
        "title": "タスクリスト",
        "what": "やることを人に振ったり、自分の分を確認したりする画面です。"
                "「自分のタスク」「依頼したタスク」で切り替えられます。",
        "flow": [
            "「自分のタスク」で、自分に来ているものを見る",
            "終わったら状態を変える",
            "人に頼むときは右上の＋から（誰に・いつまでに・優先度）",
        ],
        "fields": {},
        "checks": ["my_tasks_overdue"],
    },

    # --------------------------------------------------------
    # バイタル
    # --------------------------------------------------------
    "/vitals": {
        "title": "バイタル",
        "what": "血圧・体温・脈などを記録する画面です。"
                "★ここに記録があると、その方は【その日に来所した】とみなされます。"
                "出席回数や月次評価の数字は、ここから出ています。",
        "flow": [
            "日付と、午前／午後を選ぶ",
            "利用者を選んで、数値を入れる（カメラ読み取り・音声入力も使えます）",
            "決められた範囲を外れた方は、再検査の対象として上に出ます",
        ],
        "fields": {
            "vital-date": {
                "t": "測定した日",
                "d": "今日の日付が最初から入っています。"
                     "前の日のぶんを後から入れるときだけ変えてください。"
                     "★この日付が、その方の来所した日として残ります。",
            },
            "daily-date": {
                "t": "見たい日",
                "d": "その日に測ったぶんを一覧で確かめられます。"
                     "入れ忘れがないかの確認に使ってください。",
            },
            "history-search": {
                "t": "利用者で絞る",
                "d": "名前を入れると、その方の過去の測定値だけが並びます。"
                     "血圧の移り変わりを見たいときに。",
            },
            "s-recheck-notify": {
                "t": "再検査のお知らせ時刻",
                "d": "決めた時刻に「まだ再検査していない方がいます」と知らせます。"
                     "時刻は何個でも足せます。",
            },
        },
        "checks": ["today_no_vitals", "today_missing_vitals"],
    },

    # --------------------------------------------------------
    # カレンダー
    # --------------------------------------------------------
    "/calendar": {
        "title": "カレンダー",
        "what": "職員の予定・希望休・会議などを入れる画面です。"
                "記録入力で「休み連絡」「追加利用連絡」を保存すると、"
                "ここにも自動で入ります（二重入力は要りません）。",
        "flow": [
            "月／週を切り替えて、入れたい日を押す",
            "タイトルと日時を入れる",
            "どのカレンダーに入れるかを選んで保存",
        ],
        "fields": {
            "ev-title": {
                "t": "タイトル",
                "d": "一覧に出る名前です。「希望休」「担当者会議」など短くて構いません。",
            },
            "ev-start-date": {
                "t": "始まりの日",
                "d": "押した日が最初から入っています。",
            },
            "ev-end-date": {
                "t": "終わりの日",
                "d": "1日だけの予定なら、始まりの日と同じで大丈夫です。",
            },
            "ev-allday": {
                "t": "終日",
                "d": "入にすると時刻の欄が消えます。"
                     "希望休など、時間の決まっていない予定に使ってください。",
            },
            "ev-start-time": {
                "t": "始まりの時刻",
                "d": "「終日」を入にしているときは使いません。",
            },
            "ev-end-time": {
                "t": "終わりの時刻",
                "d": "「終日」を入にしているときは使いません。",
            },
            "ev-calendar": {
                "t": "どのカレンダーに入れるか",
                "d": "種類ごとに分けておくと、色で見分けられて後から絞り込めます。"
                     "新しい種類は、この下の「作成」から足せます。",
            },
            "ev-repeat": {
                "t": "繰り返し",
                "d": "毎週の会議など、決まって続く予定に使います。"
                     "1回だけならそのままで大丈夫です。",
            },
            "ev-repeat-until": {
                "t": "繰り返しの終わり",
                "d": "いつまで続けるかを決めます。"
                     "★決めないと、ずっと先まで作られ続けます。",
            },
            "ev-notify": {
                "t": "通知",
                "d": "予定の前に、端末にお知らせが出ます。"
                     "★スマホの通知が許可されていないと届きません。",
            },
            "ev-memo": {
                "t": "メモ",
                "d": "任意です。場所や持ち物など、当日わかると助かることを。",
            },
            "new-cal-name": {
                "t": "新しいカレンダーの名前",
                "d": "「希望休」「会議」のように、種類の名前を付けます。"
                     "後から色を変えられます。",
            },
        },
        "checks": [],
    },

}


# ============================================================
# どの画面か決める
# ============================================================

def _norm_path(p):
    """URLのパスをそろえる。末尾の / を落とし、小文字にする。"""
    p = (p or "").split("?")[0].split("#")[0].strip().lower()
    if not p.startswith("/"):
        p = "/" + p
    while len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def _match_screen(path):
    """完全一致 → いちばん長い前方一致 の順で探す。

    ★前方一致は【/ で区切れている所】だけ。
      これをしないと /inputXXX が /input に当たってしまう。
    返す形: (見つかったキー, 中身) または (None, None)
    """
    p = _norm_path(path)
    if p in SCREENS:
        return p, SCREENS[p]
    best = None
    for k in SCREENS:
        if p.startswith(k + "/") and (best is None or len(k) > len(best)):
            best = k
    return (best, SCREENS[best]) if best else (None, None)


# ============================================================
# 「次は何をしたらいい？」の判定
# ============================================================
#   ★ここも【読むだけ】。
#   返す形: None（言うことなし） または
#           {"say": 本文, "go": 行き先URL(任意), "label": ボタンの文字(任意)}

def _today_range(tokyo_tz):
    """JSTの今日の始まりと終わり。Cloud Run は UTC なので必ずJSTに直すこと。"""
    now = datetime.now(tokyo_tz)
    start = tokyo_tz.localize(datetime.combine(now.date(), dt_time.min))
    return start, start + timedelta(days=1)


def _check_today_no_record(supabase, tokyo_tz, f_code, my_name):
    """今日の記録がまだ1件も無い。"""
    s, e = _today_range(tokyo_tz)
    res = (supabase.table("records").select("id")
           .eq("facility_code", f_code)
           .gte("created_at", s.isoformat())
           .lt("created_at", e.isoformat())
           .limit(1).execute())
    if res.data:
        return None
    return {"say": "今日の記録は、まだ1件も保存されていません。"}


def _check_today_missing_records(supabase, tokyo_tz, f_code, my_name):
    """今日来られた人のうち、記録がまだ無い人。

    ★来所したかどうかは【その日にバイタルの記録があるか】で見る。
      これはアプリ全体で同じ数え方（monitoring-check-v1）。
    """
    s, e = _today_range(tokyo_tz)
    today = s.strftime("%Y-%m-%d")

    vres = (supabase.table("vitals").select("user_name")
            .eq("facility_code", f_code)
            .eq("measured_date", today)
            .execute())
    came = {(v.get("user_name") or "").strip() for v in (vres.data or [])}
    came.discard("")
    if not came:
        return None

    rres = (supabase.table("records").select("user_name")
            .eq("facility_code", f_code)
            .gte("created_at", s.isoformat())
            .lt("created_at", e.isoformat())
            .execute())
    written = {(r.get("user_name") or "").strip() for r in (rres.data or [])}

    missing = sorted(came - written)
    if not missing:
        return {"say": "今日来られた%d人ぶん、記録はそろっています。" % len(came),
                "ok": True}

    names = "、".join(missing[:3])
    if len(missing) > 3:
        names += " ほか%d人" % (len(missing) - 3)
    return {
        "say": "今日来られた%d人のうち、%d人はまだ記録がありません（%s）。"
               % (len(came), len(missing), names),
    }


def _check_unread_must_read(supabase, tokyo_tz, f_code, my_name):
    """自分にとって未読の【閲覧必須】が何件あるか。

    ★数え方は既存の /api/records/unread_count と同じにそろえてある。
      ここだけ違う数え方にすると、画面によって件数が食い違う。
    """
    res = (supabase.table("records").select("id")
           .eq("facility_code", f_code).eq("must_read", True).execute())
    ids = [r["id"] for r in (res.data or [])]
    if not ids:
        return None
    rr = (supabase.table("record_reads").select("record_id")
          .eq("facility_code", f_code).eq("staff_name", my_name)
          .in_("record_id", ids).execute())
    read = {r["record_id"] for r in (rr.data or [])}
    n = sum(1 for i in ids if i not in read)
    if not n:
        return None
    return {"say": "必ず読む記録が %d 件、まだ未読です。" % n}


def _check_my_tasks_overdue(supabase, tokyo_tz, f_code, my_name):
    """自分あてのタスクで、期限が過ぎたもの・今日が期限のもの。"""
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
    res = (supabase.table("tasks").select("title,due_date,status")
           .eq("facility_code", f_code).eq("assigned_to", my_name)
           .neq("status", "done").execute())
    over, due = [], []
    for t in (res.data or []):
        d = (t.get("due_date") or "")[:10]
        if not d:
            continue
        if d < today:
            over.append(t.get("title") or "")
        elif d == today:
            due.append(t.get("title") or "")
    if not over and not due:
        return None
    parts = []
    if over:
        parts.append("期限が過ぎたタスクが %d 件" % len(over))
    if due:
        parts.append("今日が期限のタスクが %d 件" % len(due))
    return {"say": "、".join(parts) + "あります。"}


def _check_today_no_vitals(supabase, tokyo_tz, f_code, my_name):
    """今日のバイタルがまだ1件も無い。"""
    today = datetime.now(tokyo_tz).strftime("%Y-%m-%d")
    res = (supabase.table("vitals").select("id")
           .eq("facility_code", f_code).eq("measured_date", today)
           .limit(1).execute())
    if res.data:
        return None
    return {"say": "今日のバイタルは、まだ1件も入っていません。"}


def _check_today_missing_vitals(supabase, tokyo_tz, f_code, my_name):
    """今日ケース記録がある人のうち、バイタルがまだの人。

    ★/input に入れた判定の裏返し。
      あちらは「来たのに記録が無い人」、こちらは「記録はあるのにバイタルが無い人」。
    """
    s, e = _today_range(tokyo_tz)
    today = s.strftime("%Y-%m-%d")

    rres = (supabase.table("records").select("user_name")
            .eq("facility_code", f_code)
            .gte("created_at", s.isoformat())
            .lt("created_at", e.isoformat())
            .execute())
    wrote = {(r.get("user_name") or "").strip() for r in (rres.data or [])}
    wrote.discard("")
    if not wrote:
        return None

    vres = (supabase.table("vitals").select("user_name")
            .eq("facility_code", f_code).eq("measured_date", today).execute())
    measured = {(v.get("user_name") or "").strip() for v in (vres.data or [])}

    missing = sorted(wrote - measured)
    if not missing:
        return {"say": "今日ケース記録がある %d 人ぶん、バイタルもそろっています。" % len(wrote),
                "ok": True}
    names = "、".join(missing[:3])
    if len(missing) > 3:
        names += " ほか%d人" % (len(missing) - 3)
    return {"say": "今日ケース記録がある %d 人のうち、%d 人はバイタルがまだです（%s）。"
                   % (len(wrote), len(missing), names)}


_CHECKS = {
    "today_no_record": _check_today_no_record,
    "today_missing_records": _check_today_missing_records,
    # guide-batchA
    "unread_must_read": _check_unread_must_read,
    "my_tasks_overdue": _check_my_tasks_overdue,
    "today_no_vitals": _check_today_no_vitals,
    "today_missing_vitals": _check_today_missing_vitals,
}


# ============================================================
# 登録
# ============================================================

def register_guide_routes(app):
    """Flaskアプリに案内役のAPIを登録。"""

    from app import get_supabase, tokyo_tz

    def login_required(f):
        @wraps(f)
        def decorated(*a, **kw):
            if not session.get("f_code") or not session.get("my_name"):
                return jsonify({"status": "error", "message": "ログインしてください"}), 401
            return f(*a, **kw)
        return decorated

    @app.route("/api/guide/screen", methods=["GET"])
    @login_required
    def api_guide_screen():
        """画面の案内一式を返す。★読むだけ。何も書き換えない。"""
        path = (request.args.get("path") or "").strip()
        name, conf = _match_screen(path)
        if not conf:
            # まだ案内文を書いていない画面。エラーにはしない（画面側が静かに諦める）
            return jsonify({"status": "success", "known": False,
                            "screen": "", "path": _norm_path(path)})

        fields = [{"id": k, "t": v.get("t", ""), "d": v.get("d", "")}
                  for k, v in conf.get("fields", {}).items()]

        todos = []
        f_code = session.get("f_code")
        my_name = session.get("my_name")
        if conf.get("checks"):
            try:
                supabase = get_supabase()
                for cname in conf["checks"]:
                    fn = _CHECKS.get(cname)
                    if not fn:
                        continue
                    try:
                        r = fn(supabase, tokyo_tz, f_code, my_name)
                        if r:
                            todos.append(r)
                    except Exception as ex:
                        # 1つ転んでも案内全体は出す
                        print("[guide] check %s: %s" % (cname, ex), flush=True)
            except Exception as ex:
                print("[guide] supabase: %s" % ex, flush=True)

        return jsonify({
            "status": "success",
            "known": True,
            "screen": name,
            "path": _norm_path(path),
            "title": conf.get("title", ""),
            "what": conf.get("what", ""),
            "flow": conf.get("flow", []),
            "fields": fields,
            "todos": todos,
        })

    print("[guide-v1] 案内役のAPIを登録しました（画面%d枚ぶん）" % len(SCREENS), flush=True)
