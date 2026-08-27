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
        "title": "ケース記録閲覧",
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
        "title": "タスク",
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

    # --------------------------------------------------------
    # 評価（担当ごとの入口）
    # --------------------------------------------------------
    "/assessment2": {
        "title": "評価（担当ごとの入口）",
        "what": "1か月ぶんの評価をつくる画面です。"
                "評価担当者と機能訓練指導員で入口が分かれていて、"
                "自分に関係のある欄だけが出ます。"
                "★2人が同時に入っても、別の入口なら両方書けます。",
        "flow": [
            "利用者と月を選ぶ",
            "自分の入口（評価担当者／機能訓練指導員）を選ぶ",
            "自分の欄を書いて保存する",
            "報告文はAIで作れる。誰でも直せます",
        ],
        "fields": {
            "a2-ym": {
                "t": "どの月の評価か",
                "d": "★ここを間違えると、別の月の評価を書き換えてしまいます。"
                     "先月ぶんを後から書くときは、必ず確かめてください。",
            },
            "a2-intake": {
                "t": "ご本人に聞いた内容",
                "d": "聞いた言葉のまま書いて大丈夫です。"
                     "ここに書いた内容と、機能訓練指導員が書いた体の評価の"
                     "【両方】から、AIが報告文を作ります。",
            },
            "a2-ftdata": {
                "t": "体の評価の記録",
                "d": "測った数値や気づいたことを、そのまま書いてください。"
                     "評価担当者が聞き取った内容とは別の欄なので、"
                     "同時に書いても消し合いません。",
            },
            "a2-changes": {
                "t": "訓練による変化",
                "d": "AIで作ったあと、誰でも直せます。"
                     "おかしいと思ったところは、そのまま直してください。",
            },
            "a2-issues": {
                "t": "課題とその要因",
                "d": "AIで作ったあと、誰でも直せます。",
            },
            "a2-special": {
                "t": "特記事項",
                "d": "上のどこにも当てはまらないことを書きます。任意です。",
            },
        },
        "checks": ["eval_this_month"],
    },

    # --------------------------------------------------------
    # 評価（1枚のほう・従来）
    # --------------------------------------------------------
    "/assessment": {
        "title": "評価（1枚のほう）",
        "what": "1か月ぶんの評価を、1枚の画面にまとめて書く従来のやり方です。"
                "★入口を分けた新しい画面（評価）もあります。"
                "★この画面を開いている間は、新しい画面のどちらの入口も使えません。"
                "1枚で全部を書き換えるためです。",
        "flow": [
            "利用者と月を選ぶ",
            "上から順に埋めていく",
            "保存する",
        ],
        "fields": {},
        "checks": ["eval_this_month"],
    },

    # --------------------------------------------------------
    # モニタリング文章生成
    # --------------------------------------------------------
    "/monitoring": {
        "title": "モニタリング文章生成",
        "what": "その月にたまったケース記録をAIが読んで、"
                "ケアマネジャー向けの報告文を作る画面です。"
                "★記録に書いてあることだけを使います。無い話は作りません。",
        "flow": [
            "利用者と対象月を選ぶ",
            "カテゴリ別か、まとめて1本かを選ぶ",
            "文字数を選んで生成する",
            "読んで直してから、下書き保存または確定保存",
        ],
        "fields": {},
        "checks": ["monitoring_this_month"],
    },

    # --------------------------------------------------------
    # 生活機能チェック
    # --------------------------------------------------------
    "/life_check": {
        "title": "生活機能チェック",
        "what": "生活機能チェックシート（様式3-2）を入力する画面です。"
                "介護区分によって使う様式が変わります。",
        "flow": [
            "利用者を選ぶ",
            "要介護の方は様式3-2、要支援・事業対象者の方はBIを選ぶ",
            "基本情報とADLを埋めて保存",
        ],
        "fields": {},
        "checks": [],
    },

    # --------------------------------------------------------
    # 書類出力
    # --------------------------------------------------------
    "/print_output": {
        "title": "書類出力",
        "what": "評価の内容を、印刷できる報告書の形にして出す画面です。"
                "1人ずつでも、全員まとめてでも出せます。",
        "flow": [
            "介護区分と、載せる項目を選ぶ",
            "「プレビューで確認」で中身を確かめる",
            "印刷、またはPDFで保存",
        ],
        "fields": {},
        "checks": ["eval_this_month"],
    },

    # --------------------------------------------------------
    # 利用者セルフ評価（職員側）
    # --------------------------------------------------------
    "/self-eval": {
        "title": "利用者セルフ評価",
        "what": "ご本人に、目標の達成度や困りごとを答えてもらう仕組みです。"
                "答えてもらう方法は2つあります。"
                "★タブレットを渡す／職員が聞き取って入力する。どちらでも構いません。",
        "flow": [
            "「＋ 新しく始める」で利用者を選ぶ（AIが質問を考えます）",
            "質問を確かめる。足したり消したりできます",
            "「タブレットを渡す」か「職員が聞き取って入力する」を選ぶ",
            "答えが返ってきたら確認して、評価の元データに足す",
        ],
        "fields": {},
        "checks": ["selfeval_waiting"],
    },

    # --------------------------------------------------------
    # 職員が聞き取って入力する
    # --------------------------------------------------------
    "/self-eval/interview": {
        "title": "聞き取って入力する",
        "what": "AIが考えた質問を、職員が順番に読み上げて、"
                "答えを代わりに入れていく画面です。"
                "タブレットの操作が難しい方でも答えてもらえます。",
        "flow": [
            "質問を1つずつ読み上げる",
            "答えの度合いと、話された言葉を入れる",
            "最後まで終わったら「聞き取り終了」",
        ],
        "fields": {},
        "checks": [],
    },

    # --------------------------------------------------------
    # 記録充足チェック（その日）
    # --------------------------------------------------------
    "/record_check": {
        "title": "記録充足チェック（その日）",
        "what": "選んだ【1日】について、利用者ごと・カテゴリごとに"
                "記録が書けているかを一覧で見る画面です。"
                "抜けている所がすぐ分かります。",
        "flow": [
            "見たい日を選ぶ",
            "空いているマスを探す",
            "「表示設定」で、並び順とチェックするカテゴリを変えられます",
        ],
        "fields": {},
        "checks": ["today_missing_records"],
    },

    # --------------------------------------------------------
    # 記録充足チェック（その月）
    # --------------------------------------------------------
    "/monitoring_check": {
        "title": "記録充足チェック（その月）",
        "what": "選んだ【1か月】について、記録が足りているかを見る画面です。"
                "モニタリング文章を作る前の確認に使います。"
                "★1日ぶんを見たいときは「記録充足チェック」のほうです。",
        "flow": [
            "月を選ぶ",
            "記録の少ない利用者・カテゴリを探す",
            "足りていればモニタリング文章生成へ",
        ],
        "fields": {},
        "checks": [],
    },

    # --------------------------------------------------------
    # 利用者情報
    # --------------------------------------------------------
    "/patient-info": {
        "title": "利用者情報",
        "what": "利用者ごとの情報を見たり直したりする画面です。"
                "★介護区分（要介護／要支援／事業対象者）もここで決まります。"
                "空のままだと、評価の目標欄の出方が決まりません。",
        "flow": [
            "利用者を選ぶ",
            "見たい情報のタブを開く",
            "直したい所を直して保存",
        ],
        "fields": {},
        "checks": ["careclass_missing"],
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



# ★案内を絶対に出さない画面（完全一致）
#   利用者にタブレットを渡している画面。職員向けの案内が見えてはいけない。
#   いまは利用者モード中に /api/ が403で止まるので実害は無いが、
#   モード外で開いたときに前方一致で /self-eval の案内が付くのを防ぐ。
_NO_GUIDE = (
    "/self-eval/run",
    "/self-eval/locked",
)


def _match_screen(path):
    """完全一致 → いちばん長い前方一致 の順で探す。

    ★前方一致は【/ で区切れている所】だけ。
      これをしないと /inputXXX が /input に当たってしまう。
    返す形: (見つかったキー, 中身) または (None, None)
    """
    p = _norm_path(path)
    if p in _NO_GUIDE:
        return None, None
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


def _this_month(tokyo_tz):
    return datetime.now(tokyo_tz).strftime("%Y-%m")


def _active_patient_names(supabase, f_code):
    """利用中の方の名前。

    ★care_level も利用状況も patient_profiles にある。
      evaluation_helper のコメントには「patients.care_level」とあるが、
      実際に画面へ渡しているのは patient_profiles のほう（get_patients を参照）。
      ここを取り違えると、件数がまるごと狂う。
    """
    res = (supabase.table("patient_profiles")
           .select("user_name,care_level,is_discontinued")
           .eq("facility_code", f_code).execute())
    return [r for r in (res.data or []) if not r.get("is_discontinued")]


def _check_eval_this_month(supabase, tokyo_tz, f_code, my_name):
    """今月の評価が、何人ぶんできているか。"""
    ym = _this_month(tokyo_tz)
    people = _active_patient_names(supabase, f_code)
    if not people:
        return None
    res = (supabase.table("patient_evaluations").select("user_name")
           .eq("facility_code", f_code).eq("year_month", ym).execute())
    done = {(r.get("user_name") or "").strip() for r in (res.data or [])}
    done.discard("")
    n, tot = len(done), len(people)
    if n >= tot:
        return {"say": "%s の評価は、%d人ぶんそろっています。" % (ym, tot), "ok": True}
    return {"say": "%s の評価は %d人ぶん。あと %d人 残っています。" % (ym, n, tot - n)}


def _check_monitoring_this_month(supabase, tokyo_tz, f_code, my_name):
    """今月のモニタリング報告が、何人ぶん確定しているか。

    ★target_month は <input type="month"> の値なので "YYYY-MM"。
    """
    ym = _this_month(tokyo_tz)
    res = (supabase.table("monitoring_reports").select("user_name,confirmed_at")
           .eq("facility_code", f_code).eq("target_month", ym).execute())
    rows = res.data or []
    if not rows:
        return {"say": "%s のモニタリング文章は、まだ1件も作られていません。" % ym}
    fixed = {(r.get("user_name") or "") for r in rows if r.get("confirmed_at")}
    draft = len({(r.get("user_name") or "") for r in rows}) - len(fixed)
    if draft <= 0:
        return {"say": "%s のモニタリング文章は %d人ぶん確定ずみです。" % (ym, len(fixed)),
                "ok": True}
    return {"say": "%s のモニタリング文章: 確定 %d人、下書きのまま %d人。"
                   % (ym, len(fixed), draft)}


def _check_selfeval_waiting(supabase, tokyo_tz, f_code, my_name):
    """答えが返ってきて、職員の確認を待っているセルフ評価。"""
    res = (supabase.table("patient_self_evaluations").select("user_name")
           .eq("facility_code", f_code).eq("status", "answered").execute())
    n = len(res.data or [])
    if not n:
        return None
    return {"say": "答えが返ってきて確認待ちのセルフ評価が %d 件あります。" % n}


def _check_careclass_missing(supabase, tokyo_tz, f_code, my_name):
    """介護区分が空のまま の方。

    ★空だと、評価の画面で目標欄をいくつ出すかが決まらない。
      本番では86人中7人が空だった（2026-08 の調査）。
    """
    people = _active_patient_names(supabase, f_code)
    if not people:
        return None
    bad = [r for r in people
           if (r.get("care_level") or "").strip().lower() in ("", "none", "null")]
    if not bad:
        return {"say": "介護区分は %d人ぶん、全員入っています。" % len(people), "ok": True}
    names = "、".join([(r.get("user_name") or "") for r in bad[:3]])
    if len(bad) > 3:
        names += " ほか%d人" % (len(bad) - 3)
    return {"say": "介護区分が空の方が %d人 います（%s）。評価の目標欄が正しく出ません。"
                   % (len(bad), names)}


_CHECKS = {
    "today_no_record": _check_today_no_record,
    "today_missing_records": _check_today_missing_records,
    # guide-batchA
    "unread_must_read": _check_unread_must_read,
    "my_tasks_overdue": _check_my_tasks_overdue,
    "today_no_vitals": _check_today_no_vitals,
    "today_missing_vitals": _check_today_missing_vitals,
    # guide-batchB
    "eval_this_month": _check_eval_this_month,
    "monitoring_this_month": _check_monitoring_this_month,
    "selfeval_waiting": _check_selfeval_waiting,
    "careclass_missing": _check_careclass_missing,
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
