# -*- coding: utf-8 -*-
"""
keiyaku_render.py  (marker: keiyaku-render-v1)
契約書・重要事項説明書の印刷用HTML生成モジュール。

設計:
- render_juyo(F, st) / render_keiyaku(F, st) が各書類本文HTMLを返す。
- render_print_html(F, doc, st) が wkhtmltopdf 向けの完全なHTML（CSS込み）を返す。
- F は keiyaku_facility 設定 dict（houjin/jigyosho/service/hyoka/unei/kujo/hokensha/
  jihi/staff/adds/area_level/visits_per_month、任意で overrides）。
- 料金計算は app.py の _kk_* と同一ロジック（処遇改善12.5%・floor(x+0.5)四捨五入）。
- overrides: F.get("overrides",{}) に {テンプレID: 上書きHTML} があればテンプレより優先。
  半日/1日やプレースホルダ差込が要る条文は、上書き時もプレースホルダを使える。

依存なし（標準ライブラリのみ）。app.py から import して使用。
"""
import math

# ===== 料金計算（app.py の _kk_* と同一ロジック） =====
# keiyaku-timeclass-v1: 地域密着型通所介護 基本単位数を国の所要時間区分(time_class)で保持。
# 出典: 介護給付費単位数等サービスコード表(令和8年6月施行版) 78 1xxx 地域密着型通所介護費(本体)。
_BASE = {
    "3-4h": {1: 416, 2: 478, 3: 540, 4: 600, 5: 663},
    "4-5h": {1: 436, 2: 501, 3: 566, 4: 629, 5: 695},
    "5-6h": {1: 657, 2: 776, 3: 896, 4: 1013, 5: 1134},
    "6-7h": {1: 678, 2: 801, 3: 925, 4: 1049, 5: 1172},
    "7-8h": {1: 753, 2: 890, 3: 1032, 4: 1172, 5: 1312},
    "8-9h": {1: 783, 2: 925, 3: 1072, 4: 1220, 5: 1365},
}
# 旧種別キー(han/ichi)→time_class の後方互換マッピング。
_LEGACY_TC = {"han": "3-4h", "ichi": "7-8h"}
_AREA_UP = {1: 0.20, 2: 0.16, 3: 0.15, 4: 0.12, 5: 0.10, 6: 0.06, 7: 0.03, 0: 0.0}
_KUNREN1 = 56
_KUNREN2 = 20
_KAGAKU = 40
# keiyaku-timeclass-v1: 介護職員等処遇改善加算 6区分の率(/1000)。既定はⅡロ(2ro)=12.5%。
_SHOGUU_RATES = {
    "1i": 0.117, "1ro": 0.127, "2i": 0.115, "2ro": 0.125, "3": 0.105, "4": 0.089,
}
_SHOGUU_LABELS = {
    "1i": "介護職員等処遇改善加算（Ⅰ）イ……11.7％/月",
    "1ro": "介護職員等処遇改善加算（Ⅰ）ロ……12.7％/月",
    "2i": "介護職員等処遇改善加算（Ⅱ）イ……11.5％/月",
    "2ro": "介護職員等処遇改善加算Ⅱロ（Ⅱ２）……12.5％/月（令和8年6月〜）",
    "3": "介護職員等処遇改善加算（Ⅲ）……10.5％/月",
    "4": "介護職員等処遇改善加算（Ⅳ）……8.9％/月",
}
_SHOGUU_RATE = 0.125  # 後方互換: 旧コードが参照する既定率(Ⅱロ)。
_JINKENHI = 0.45


# ===== keiyaku-addmaster-v1 : 加算マスタ（地域密着型通所介護） =====
# 各加算の定義。C-1ではまず現状4加算(kunren1/kunren2/kagaku/shoguu)を
# マスタ駆動で従来と完全一致させることを最優先とする。C-2以降で他加算を追加。
#
# calc 種別と月額換算ルール（計算の芯）:
#   per_visit      : units × 月利用回数（毎回算定。例 個別Ⅰ・中重度・認知症）
#   per_month      : units（月1回定額。例 個別Ⅱ・科学的介護）
#   per_month_cap  : units × min(月利用回数, cap)（限度つき。例 口腔機能向上 月2回）
#   rate_on_total  : 他加算込みの月総単位 × 率（処遇改善のみ。最後に乗算）
# in_fee_default : 料金表(要介護別月額自己負担)に金額で織り込む既定値。
#   True  = 毎月確実に乗る加算 → 料金表の数字に反映。
#   False = 利用者/頻度依存 → 料金表には載せず、加算一覧表に「単位×条件」で明記。
# group : 排他グループ（同一グループは1つのみ算定可）。
# scope : 'service'=種別ごと / 'facility'=施設共通。
# note  : 加算一覧表に出す条件文（単位数＋限度の説明）。
_ADD_MASTER = {
    # --- C-1 対象（現状4加算。従来と完全一致させる） ---
    "kunren1": {"units": _KUNREN1, "calc": "per_visit", "scope": "service",
                "group": "kunren_kobetsu", "in_fee_default": True,
                "label": "個別機能訓練加算Ⅰ１",
                "note": "56単位／回（利用日ごと）"},
    "kunren2": {"units": _KUNREN2, "calc": "per_month", "scope": "service",
                "in_fee_default": True,
                "label": "個別機能訓練加算Ⅱ",
                "note": "20単位／月"},
    "kagaku":  {"units": _KAGAKU, "calc": "per_month", "scope": "service",
                "in_fee_default": True,
                "label": "科学的介護推進体制加算",
                "note": "40単位／月"},
    "shoguu":  {"calc": "rate_on_total", "scope": "facility",
                "in_fee_default": True,
                "label": "介護職員等処遇改善加算",
                "note": "月総単位数に所定の率を乗じて算定"},
    # --- C-2 追加（毎回算定 per_visit・in_fee:true で料金表に反映） ---
    # 単位数は介護給付費単位数等サービスコード表(78系)・告示で確認済み。
    "kunren1ro": {"units": 76, "calc": "per_visit", "scope": "service",
                  "group": "kunren_kobetsu", "in_fee_default": True,
                  "label": "個別機能訓練加算Ⅰ２（Ⅰロ）",
                  "note": "76単位／回（利用日ごと。Ⅰ１と排他）"},
    "chuju":   {"units": 45, "calc": "per_visit", "scope": "service",
                "in_fee_default": True,
                "label": "中重度者ケア体制加算",
                "note": "45単位／回（利用日ごと。利用者全員に算定可）"},
    "ninchi":  {"units": 60, "calc": "per_visit", "scope": "service",
                "in_fee_default": True,
                "label": "認知症加算",
                "note": "60単位／回（利用日ごと。要件を満たす場合）"},
    "nyuyoku1": {"units": 40, "calc": "per_visit", "scope": "service",
                 "group": "nyuyoku", "in_fee_default": True,
                 "label": "入浴介助加算Ⅰ",
                 "note": "40単位／回（入浴介助実施日。Ⅱと排他）"},
    "nyuyoku2": {"units": 55, "calc": "per_visit", "scope": "service",
                 "group": "nyuyoku", "in_fee_default": True,
                 "label": "入浴介助加算Ⅱ",
                 "note": "55単位／回（入浴介助実施日。Ⅰと排他）"},
    # --- C-4 追加（限度つき・低頻度。既定 in_fee:False＝料金表でなく一覧表に条件のみ） ---
    # 口腔機能向上加算: 1回150/160単位、3月以内に限り月2回を限度（要介護は月最大2回）。
    "koukuu1": {"units": 150, "calc": "per_month_cap", "cap": 2, "scope": "service",
                "group": "koukuu", "in_fee_default": False,
                "label": "口腔機能向上加算Ⅰ",
                "note": "150単位／回（月2回を限度。Ⅱと排他）"},
    "koukuu2": {"units": 160, "calc": "per_month_cap", "cap": 2, "scope": "service",
                "group": "koukuu", "in_fee_default": False,
                "label": "口腔機能向上加算Ⅱ",
                "note": "160単位／回（月2回を限度。Ⅰと排他。LIFE提出要件）"},
    # --- C-4b 追加（栄養・連携・ADL・若年性。単位数は78系コード表で確認済み） ---
    "eiyou_assess": {"units": 50, "calc": "per_month", "scope": "service",
                     "in_fee_default": False,
                     "label": "栄養アセスメント加算",
                     "note": "50単位／月（LIFE提出要件）"},
    "eiyou_kaizen": {"units": 200, "calc": "per_month_cap", "cap": 2, "scope": "service",
                     "in_fee_default": False,
                     "label": "栄養改善加算",
                     "note": "200単位／回（月2回を限度）"},
    "screening1": {"units": 20, "calc": "low_freq", "scope": "service",
                   "group": "screening", "in_fee_default": False,
                   "label": "口腔・栄養スクリーニング加算Ⅰ",
                   "note": "20単位／回（6月に1回を限度）"},
    "renkei1": {"units": 100, "calc": "low_freq", "scope": "service",
                "group": "renkei", "in_fee_default": False,
                "label": "生活機能向上連携加算Ⅰ",
                "note": "100単位／回（原則3月に1回を限度。Ⅱと排他）"},
    "renkei2": {"units": 200, "calc": "per_month", "scope": "service",
                "group": "renkei", "in_fee_default": False,
                "label": "生活機能向上連携加算Ⅱ",
                "note": "200単位／月（Ⅰと排他）"},
    "adl1": {"units": 30, "calc": "per_month", "scope": "service",
             "group": "adl", "in_fee_default": False,
             "label": "ADL維持等加算Ⅰ",
             "note": "30単位／月（Ⅱと排他。LIFE提出要件）"},
    "adl2": {"units": 60, "calc": "per_month", "scope": "service",
             "group": "adl", "in_fee_default": False,
             "label": "ADL維持等加算Ⅱ",
             "note": "60単位／月（Ⅰと排他。LIFE提出要件）"},
    "jakunen": {"units": 60, "calc": "per_visit", "scope": "service",
                "in_fee_default": False,
                "label": "若年性認知症利用者受入加算",
                "note": "60単位／回（利用日ごと。要件を満たす場合）"},
    "soudan": {"units": 13, "calc": "per_visit", "scope": "service",
               "in_fee_default": False,
               "label": "生活相談員配置等加算",
               "note": "13単位／回（利用日ごと。※共生型地域密着型通所介護のみ算定可。"
                       "共生型は基本報酬が所定単位の93/100となる点に留意）"},
}

# in_fee_default が True の加算キー集合（C-1の現状4加算）。
_ADD_KEYS_IN_FEE = tuple(k for k, m in _ADD_MASTER.items()
                         if m.get("in_fee_default"))


def _add_state(adds, key):
    """keiyaku-addmaster-v1: adds[key] を {on, in_fee} に正規化して返す。
    後方互換: 旧 bool 値（adds={kunren1:True,...}）は
    {on:True, in_fee:マスタ既定} に読み替える。dict なら on/in_fee を尊重。
    keiyaku-c4b-v1: calc='low_freq'（6月/3月1回等の超低頻度）は料金表に載せる概念が
    無いため in_fee を常に False に強制（一覧表専用）。"""
    m = _ADD_MASTER.get(key, {})
    in_fee_def = bool(m.get("in_fee_default"))
    v = adds.get(key)
    if isinstance(v, dict):
        st = {"on": bool(v.get("on")),
              "in_fee": bool(v.get("in_fee", in_fee_def))}
    else:
        st = {"on": bool(v), "in_fee": in_fee_def}
    if m.get("calc") == "low_freq":
        st["in_fee"] = False
    return st


def _resolve_tc(F, key):
    """keiyaku-timeclass-v1: 種別キー/旧キーから time_class を解決して _BASE 参照キーを返す。
    優先順: service[key]['time_class'] → 旧キー名(han/ichi)変換 → そのまま(既に time_class)。"""
    if key in _BASE:
        return key
    sv = _g(F, "service", key, default={})
    tc = sv.get("time_class") if isinstance(sv, dict) else None
    if tc in _BASE:
        return tc
    if key in _LEGACY_TC:
        return _LEGACY_TC[key]
    return "3-4h"


def _shoguu_rate(adds):
    """keiyaku-timeclass-v1 / addmaster-v1: adds から処遇改善率を取得。
    on 判定は _add_state 経由で旧bool/新dictの両形式に対応。
    率は shoguu_type 優先、無ければ既定Ⅱロ。off時は 0。"""
    if not _add_state(adds, "shoguu")["on"]:
        return 0.0
    stype = adds.get("shoguu_type", "2ro")
    return _SHOGUU_RATES.get(stype, _SHOGUU_RATES["2ro"])


def _floor(x):
    return math.floor(x)


def _round_half(x):
    return math.floor(x + 0.5)


def _tanka(area_level):
    raw = 10 * (1 + _AREA_UP.get(area_level, 0.0) * _JINKENHI)
    return math.floor(raw * 100 + 0.5) / 100


def _jiko_monthly(F, st, lv, wari, visits, adds, area):
    """keiyaku-addmaster-v1: 加算マスタ駆動で月額自己負担を算出。
    料金表に金額で織り込むのは on かつ in_fee の加算のみ。
    処遇改善(rate_on_total)は他加算込みの月総単位に率を乗じ最後に加算。
    現状4加算では従来ロジックと完全一致する（C-1検証要件）。"""
    tc = _resolve_tc(F, st)
    base = _BASE[tc][lv]

    # 毎回乗る加算(per_visit)を1回あたり単位に合算 → ×回数
    per_visit = base
    monthly_fixed = 0  # per_month / per_month_cap の月額単位合計
    rate = 0.0
    for key, m in _ADD_MASTER.items():
        stt = _add_state(adds, key)
        if not (stt["on"] and stt["in_fee"]):
            continue
        calc = m.get("calc")
        if calc == "per_visit":
            per_visit += m["units"]
        elif calc == "per_month":
            monthly_fixed += m["units"]
        elif calc == "per_month_cap":
            monthly_fixed += m["units"] * min(visits, m.get("cap", visits))
        elif calc == "rate_on_total":
            rate = _shoguu_rate(adds)

    monthly = per_visit * visits + monthly_fixed
    if rate:
        monthly += _round_half(monthly * rate)
    total_yen = _floor(monthly * _tanka(area))
    kyufu = _floor(total_yen * (10 - wari) / 10)
    return total_yen - kyufu


def _yen(n):
    return f"{n:,}"


def _esc(t):
    if t is None:
        return ""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ===== 取得設定の安全アクセス =====
def _g(d, *keys, default=""):
    """ネストした dict を安全に辿る。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


# ===== 料金表（コンパクト1表・rowspanなし） =====
def _fee_table(F, st):
    adds = F.get("adds", {})
    area = int(F.get("area_level", 3))
    vpm = int(F.get("visits_per_month", 4))
    tc = _resolve_tc(F, st)
    b = _BASE[tc]
    vmap = {1: vpm, 2: vpm * 2, 3: vpm * 3}
    head = (
        '<tr><th class="hh">負担割合</th><th class="hh">利用回数</th>'
        f'<th>要介護1<br><span class="u">{b[1]}単位</span></th>'
        f'<th>要介護2<br><span class="u">{b[2]}単位</span></th>'
        f'<th>要介護3<br><span class="u">{b[3]}単位</span></th>'
        f'<th>要介護4<br><span class="u">{b[4]}単位</span></th>'
        f'<th>要介護5<br><span class="u">{b[5]}単位</span></th></tr>'
    )
    body = ""
    for w in (1, 2, 3):
        for kai in (1, 2, 3):
            vals = "".join(
                f"<td>{_yen(_jiko_monthly(F, st, l, w, vmap[kai], adds, area))}</td>"
                for l in range(1, 6)
            )
            wlabel = f"{w}割" if kai == 1 else ""
            cls = ' class="wari"' if kai == 1 else ""
            body += f'<tr><td{cls}>{wlabel}</td><td class="kai">週{kai}回</td>{vals}</tr>'
    return f'<table class="ptab fee">{head}{body}</table>'


# ===== 加算概要（選択された加算のみ） =====
def _adds_line(F):
    adds = F.get("adds", {})
    parts = []
    if adds.get("kunren1"):
        parts.append("「個別機能訓練加算Ⅰ１」……56単位×利用回数")
    if adds.get("kunren2"):
        parts.append("「個別機能訓練加算Ⅱ」……20単位/月")
    if adds.get("kagaku"):
        parts.append("「科学的介護推進体制加算」……40単位/月")
    if adds.get("shoguu"):
        stype = adds.get("shoguu_type", "2ro")
        label = _SHOGUU_LABELS.get(stype, _SHOGUU_LABELS["2ro"])
        parts.append("「" + label.split("……")[0] + "」サービス別加算率……" + label.split("……")[1])
    return "／".join(parts)


# keiyaku-c4-table-v1: 加算一覧表。on の全加算を「名称／単位数・条件／料金表反映区分」で表示。
# in_fee:true（毎月確実）は料金表に金額反映済み、in_fee:false（限度つき・低頻度）は
# 「※実施月のみ・料金表別途」と明示し、HIROの方針「単位×条件（〇回まで算定）」を満たす。
def _adds_table(F):
    adds = F.get("adds", {})
    rows = ""
    for key, m in _ADD_MASTER.items():
        stt = _add_state(adds, key)
        if not stt["on"]:
            continue
        label = _esc(m.get("label", key))
        # 処遇改善は率表記（区分別ラベルを使う）。
        if m.get("calc") == "rate_on_total":
            stype = adds.get("shoguu_type", "2ro")
            slabel = _SHOGUU_LABELS.get(stype, _SHOGUU_LABELS["2ro"])
            jname, jrate = (slabel.split("……") + [""])[:2]
            cond = "月総単位数 × " + jrate if jrate else "月総単位数に所定の率を乗じて算定"
            label = _esc(jname)
            hanei = "料金表に反映済み"
        else:
            cond = _esc(m.get("note", ""))
            hanei = "料金表に反映済み" if stt["in_fee"] else "※実施月のみ算定／料金表とは別に加算"
        rows += (f'<tr><td class="k">{label}</td>'
                 f'<td class="L">{cond}</td>'
                 f'<td class="L">{hanei}</td></tr>')
    if not rows:
        return ""
    head = ('<tr><th class="L">加算名</th><th class="L">単位数・算定条件</th>'
            '<th class="L">料金表への反映</th></tr>')
    return f'<table class="ptab">{head}{rows}</table>'


# ===== 自費・職員 テーブル =====
def _jihi_table(F):
    rows = ""
    for x in F.get("jihi", []):
        if not str(x.get("name", "")).strip():
            continue
        note = f'<br><span class="sub">{_esc(x.get("note"))}</span>' if x.get("note") else ""
        rows += (f'<tr><td class="k">{_esc(x.get("name"))}{note}</td>'
                 f'<td style="text-align:right">{_esc(x.get("price"))}円</td>'
                 f'<td>{_esc(x.get("unit"))}</td></tr>')
    if not rows:
        return ""
    return f'<table class="ptab"><tr><th class="L">項目</th><th>料金</th><th>単位</th></tr>{rows}</table>'


def _staff_table(F):
    rows = ""
    for s in F.get("staff", []):
        if not str(s.get("role", "")).strip():
            continue
        rows += (f'<tr><td class="k">{_esc(s.get("role"))}</td>'
                 f'<td class="L">{_esc(s.get("work"))}</td>'
                 f'<td>{_esc(s.get("count"))}</td></tr>')
    if not rows:
        return ""
    return f'<table class="ptab"><tr><th class="L">職種</th><th class="L">業務内容</th><th>常勤換算数</th></tr>{rows}</table>'


# ===== overrides 解決 =====
def _ov(F, tpl_id, default_html):
    """overrides に tpl_id があればそれを返す。無ければ default_html。"""
    ov = F.get("overrides", {})
    if isinstance(ov, dict) and ov.get(tpl_id):
        return ov[tpl_id]
    return default_html


# keiyaku-stepb2-v1: その他特記事項（施設共通）。重説末尾に出力。
def _tokki_section(F):
    """F['tokki'] = [{'name':..., 'body':...}, ...]。
    改ページは F['tokki_page_break'] が真なら新ページから開始（案イ・トグル1個）。"""
    items = F.get("tokki", [])
    if not isinstance(items, list):
        items = []
    rows = ""
    for it in items:
        if not isinstance(it, dict):
            continue
        name = _esc(it.get("name", ""))
        body = _esc(it.get("body", "")).replace("\n", "<br>")
        if not (name or body):
            continue
        rows += (f'<div class="tokki-item">'
                 f'<div class="tokki-name">{name}</div>'
                 f'<div class="tokki-body">{body}</div></div>')
    if not rows:
        return ""
    cls = "sec tokki-sec page-break" if F.get("tokki_page_break") else "sec tokki-sec"
    inner = f'<div class="{cls}"><div class="sec-h">その他特記事項</div>{rows}</div>'
    return _ov(F, "juyo_tokki", inner)


# ===== 重要事項説明書 本文 =====
def render_juyo(F, st):
    sv = _g(F, "service", st, default={})
    h = F.get("houjin", {})
    j = F.get("jigyosho", {})
    hy = F.get("hyoka", {})
    un = F.get("unei", {})
    ku = F.get("kujo", {})
    ho = F.get("hokensha", {})
    area = int(F.get("area_level", 3))

    hyoka_html = (
        f'<p>{_esc(hy.get("note"))}　最終評価日　{_esc(hy.get("last_date"))}'
        f'／実施機関　{_esc(hy.get("kikan"))}</p>'
        if hy.get("jisshi") else "<p>実施しておりません。</p>"
    )

    sec_houjin = f'''<div class="sec"><div class="sec-h">1．法人（事業者）の概要</div>
<table class="ptab">
<tr><td class="k">法人名</td><td class="L">{_esc(h.get("name"))}（{_esc(h.get("name_kana"))}）</td></tr>
<tr><td class="k">法人所在地</td><td class="L">〒{_esc(h.get("zip"))}　{_esc(h.get("address"))}</td></tr>
<tr><td class="k">電話番号</td><td class="L">TEL{_esc(h.get("tel"))}　FAX{_esc(h.get("fax"))}</td></tr>
<tr><td class="k">代表者名</td><td class="L">{_esc(h.get("daihyo"))}</td></tr>
<tr><td class="k">設立年月日</td><td class="L">{_esc(h.get("founded"))}</td></tr>
</table></div>'''

    sec_jigyosho = f'''<div class="sec"><div class="sec-h">2．ご利用事業所の概要</div>
<table class="ptab">
<tr><td class="k">事業所の種類</td><td class="L">{_esc(j.get("type"))}（{_esc(j.get("type_date"))}）</td></tr>
<tr><td class="k">事業所の名称</td><td class="L">{_esc(j.get("name"))}</td></tr>
<tr><td class="k">所在地</td><td class="L">〒{_esc(j.get("zip"))}　{_esc(j.get("address"))}</td></tr>
<tr><td class="k">電話番号</td><td class="L">TEL{_esc(j.get("tel"))}　FAX{_esc(j.get("fax"))}</td></tr>
<tr><td class="k">管理者名</td><td class="L">{_esc(j.get("kanrisha"))}</td></tr>
<tr><td class="k">開設年月日</td><td class="L">{_esc(j.get("opened"))}</td></tr>
<tr><td class="k">利用定員</td><td class="L">{_esc(sv.get("teiin"))}</td></tr>
<tr><td class="k">サービス提供地域</td><td class="L">{_esc(j.get("area"))}</td></tr>
<tr><td class="k">設備の概要</td><td class="L">{_esc(j.get("setsubi"))}</td></tr>
<tr><td class="k">営業日</td><td class="L">{_esc(sv.get("eigyobi"))}（お盆・年末年始は休業）</td></tr>
<tr><td class="k">営業時間</td><td class="L">{_esc(sv.get("eigyo_time"))}</td></tr>
<tr><td class="k">サービス提供時間</td><td class="L">{_esc(sv.get("teikyo_time"))}</td></tr>
</table></div>'''

    sec_staff = f'''<div class="sec"><div class="sec-h">3．職員の配置状況</div>
<p>当事業所では、ご契約者に対して指定地域密着型通所介護を提供する職員として、以下の職種の職員を配置しています。職員配置については指定基準を遵守しています。</p>
{_staff_table(F)}
<p class="note">常勤換算＝勤務延べ時間数の総数を、常勤職員の所定労働勤務時間数（週40時間）で除した数です。配置基準：生活相談員1名以上／介護職員 当日の利用者数15名までは1名以上、それ以上5名またはその端数を増すごとに1名以上／機能訓練指導員1名以上</p></div>'''

    sec_hyoka = f'<div class="sec"><div class="sec-h">4．サービスの第三者評価の実施状況</div>{hyoka_html}</div>'

    sec_tokucho = _ov(F, "juyo_tokucho", f'''<div class="sec"><div class="sec-h">5．当事業所が提供するサービスの特徴</div>
<p><b>運営方針：</b>{_esc(un.get("houshin"))}</p>
<p><b>提供するサービス：</b>地域密着型通所介護計画に沿って、{_esc(sv.get("svc_naiyo"))}を行います。具体的な内容はお配りする予定表をご覧ください。</p></div>''')

    sec_ryokin = f'''<div class="sec"><div class="sec-h">6．当事業所の利用料金（契約書第6条参照）</div>
<p>下記の利用料金表により、要介護度に応じたサービス利用料金および加算料金から介護給付費額を除いた金額（自己負担額）と、おやつ等に係る自己負担額をお支払いください。自己負担額の変更があった場合には、契約書および重要事項説明書の再契約を必要とせず、下記の料金に変更といたします。</p>
<p>・介護報酬1単位あたりの単価は <b>{_tanka(area)}円</b>　・サービス提供時間 {_esc(sv.get("teikyo_hours"))}　・下表は月額自己負担額（円／全ての加算を含む）</p>
{_fee_table(F, st)}
<p class="note">※週1回＝月{int(F.get("visits_per_month",4))}回換算で算出。利用回数により金額は変わります。</p></div>'''

    sec_kasan = f'''<div class="sec"><div class="sec-h">各種加算の概要</div>
{_adds_table(F)}
<p class="note">「料金表に反映済み」の加算は、上記の月額自己負担額に含まれています。「※実施月のみ算定／料金表とは別に加算」の加算は、サービスを実施した月に限り、上記単位数・限度回数に基づき別途加算されます（一単位未満の端数四捨五入）。いずれも区分支給限度基準額の算定対象外です。</p></div>'''

    sec_jihi = f'''<div class="sec"><div class="sec-h">自費料金・その他の費用</div>
{_jihi_table(F)}
<p class="note">通常の事業の実施地域を越えて行う送迎費用：片道5km未満200円（税込）／片道5km以上400円（税込）。サービス提供時間を超えて行った通所介護の費用：30分あたり500円（税込）。レクリエーションに係る費用等は自己負担となります。</p></div>'''

    sec_shiharai = f'''<div class="sec"><div class="sec-h">利用料のお支払方法（契約書第6条参照）</div>
<p>前記の料金・費用は{_esc(un.get("shime"))}のうえ1か月ごとに計算し、{_esc(un.get("seikyu_date"))}に前月分の請求書をお渡しいたします。お支払いは利用者様ご指定の口座より、{_esc(un.get("hikiotoshi_date"))}に口座自動引落となります。引落に必要な手数料は事業所で負担します。事業所は料金の支払いを受けたときは領収証を発行します。</p></div>'''

    sec_kinkyu = '''<div class="sec"><div class="sec-h">緊急時の対応方法と健康上の理由による利用中止について</div>
<p>①ご契約者に容体の変化等があった場合は、医師または歯科医師など医療機関に連絡をとるなど必要な措置を講じるほか、緊急連絡先に速やかに連絡いたします。②風邪・病気の場合および当日の健康チェックの結果体調が不調の場合は、サービス内容の変更またはサービスを中止することがあります。</p>
<table class="ptab fill"><tr><td class="k">主治医</td><td class="hint">氏名／連絡先</td><td class="wr"></td></tr><tr><td class="k">緊急時の病院</td><td class="hint">病院名</td><td class="wr"></td></tr><tr><td class="k">ご家族</td><td class="hint">氏名／連絡先</td><td class="wr"></td></tr></table></div>'''

    sec_shuryo = '''<div class="sec"><div class="sec-h">契約の終了について（契約書第15条参照）</div>
<p>当事業所との契約では契約が終了する期日は特に定めていません。以下のような事由がない限り継続してサービスを利用できますが、該当するに至った場合には書面による契約解除を交わすことなく契約は終了します。①ご契約者が死亡した場合　②要介護認定により自立または要支援1・要支援2と判定された場合　③やむを得ない事由により事業所を閉鎖した場合　④事業所の重大な毀損により提供が不可能になった場合　⑤介護保険の指定を取り消された場合または辞退した場合　⑥ご契約者から中途解約・契約解除の申し出があった場合　⑦事業所から退所の申し出を行った場合</p></div>'''

    # keiyaku-fix-v1: 電話番号が担当者の間に挟まって読みにくかったので、行を分ける
    sec_kujo = f'''<div class="sec"><div class="sec-h">サービス内容に関する苦情と相談</div>
<table class="ptab kujo"><tr><td class="k">受付時間</td><td class="L">{_esc(ku.get("time"))}</td></tr>
<tr><td class="k">苦情受付電話番号</td><td class="L">TEL {_esc(ku.get("uketsuke_tel"))}</td></tr>
<tr><td class="k">苦情受付・対応担当者</td><td class="L">{_esc(ku.get("uketsuke"))}　／　{_esc(ku.get("taio"))}</td></tr>
<tr><td class="k">苦情解決責任者</td><td class="L">{_esc(ku.get("sekinin"))}</td></tr></table>
<p class="note">下記の窓口でも受け付けております。{_esc(ho.get("name"))}　介護保険課　TEL {_esc(ho.get("kaigo_tel"))}　FAX {_esc(ho.get("kaigo_fax"))}／{_esc(ho.get("kokuho_name"))}　TEL {_esc(ho.get("kokuho_tel"))}　FAX {_esc(ho.get("kokuho_fax"))}</p></div>'''

    sec_saigai = '''<div class="sec"><div class="sec-h">非常災害時の対応方法</div><p>災害発生時にはスタッフが速やかに最寄りの避難所まで誘導いたします。スタッフの指示に従って行動をお願いいたします。</p></div>'''

    sec_souchou = '''<div class="sec"><div class="sec-h">早朝ご連絡時の注意点</div><p>当日のキャンセル連絡を早朝にされる場合には、8:00〜8:15の時間でご連絡いただけるようお願いいたします。それ以外の時間ですと送迎等でスタッフが不在の場合がございます。</p></div>'''

    # keiyaku-sign-v1: 記入する欄の下だけに線を引き、全体を右寄せにする。
    # 「様」は上の氏名欄の右端にそろえる。
    sign = f'''<div class="sign">
<p>指定地域密着型通所介護の提供の開始に際し、本書面に基づき重要事項の説明を行いました。</p>
<p class="center">令和　　年　　月　　日</p>
<div class="sign-block"><p>{_esc(j.get("name"))}</p>
<table class="sigtab">
<tr><td class="lbl">説明者　職名</td><td class="fill w2"></td><td class="lbl">氏名</td><td class="fill"></td><td class="sama"></td></tr>
</table></div>
<p>私は、本書面に基づいて事業所から重要事項の説明を受け、指定地域密着型通所介護の開始に同意しました。</p>
<div class="sign-block">
<table class="sigtab">
<tr><td class="lbl">ご契約者</td><td class="fill" colspan="3"></td><td class="sama">様</td></tr>
<tr><td class="lbl">代理人</td><td class="fill" colspan="3"></td><td class="sama">様</td></tr>
</table></div></div>'''

    head = f'''<div class="doc-title">{_esc(j.get("name"))}</div>
<div class="doc-sub">地域密着型通所介護 重要事項説明書</div>
<p class="center note">当事業所は介護保険の指定を受けています。（指定　第{_esc(j.get("shitei_no"))}号）</p>
<p>当事業所はご契約者に対して指定地域密着型通所介護を提供します。事業所の概要や提供されるサービスの内容、契約上ご注意いただきたいことを次のとおり説明します。</p>'''

    return ("<div class=\"paper\">" + head + sec_houjin + sec_jigyosho + sec_staff +
            sec_hyoka + sec_tokucho + sec_ryokin + sec_kasan + sec_jihi +
            sec_shiharai + sec_kinkyu + sec_shuryo + sec_kujo + sec_saigai +
            sec_souchou + _tokki_section(F) + sign + "</div>")


# ===== 利用契約書 本文（全22条） =====
def render_keiyaku(F, st):
    sv = _g(F, "service", st, default={})
    h = F.get("houjin", {})
    j = F.get("jigyosho", {})
    jname = _esc(j.get("name"))

    art = {}
    art["1"] = '''<div class="sec"><div class="sec-h">第1条（契約の目的）</div>
<p>(1) 事業所は、介護保険法令の趣旨に従い、ご契約者が可能な限りその居宅において、その有する能力に応じ自立した日常生活を営むことができるよう支援し、第5条に定める指定地域密着型通所介護を提供します。</p>
<p>(2) ご契約者は、第15条に定める契約の終了事由がない限り、契約日より本契約に定めるところに従い、サービスを利用できるものとします。</p></div>'''
    art["2"] = '''<div class="sec"><div class="sec-h">第2条（契約期間）</div>
<p>この契約の契約期間は、契約日から第15条各号で定める契約終了日までとします。</p></div>'''
    art["3"] = '''<div class="sec"><div class="sec-h">第3条（地域密着型通所介護計画）</div>
<p>事業所は、ご契約者の日常生活全般の状況及び希望を踏まえて、「居宅サービス計画」に沿って「地域密着型通所介護計画」を作成します。事業所はこの「地域密着型通所介護計画」の内容をご契約者及び代理人に説明し同意を得るものとします。</p></div>'''
    art["4"] = f'''<div class="sec"><div class="sec-h">第4条（指定地域密着型通所介護の提供場所・内容）</div>
<p>(1) 指定地域密着型通所介護の提供場所は「{jname}」です。所在地及び設備の概要は重要事項説明書のとおりです。</p>
<p>(2) 事業所は、第3条に定めた地域密着型通所介護計画に沿って指定地域密着型通所介護を提供します。事業所は指定地域密着型通所介護の提供にあたり、その内容についてご契約者に説明します。</p>
<p>(3) ご契約者は、サービス内容の変更を希望する場合には、事業所に申し入れることができます。その場合、事業所は、可能な限りご契約者の希望に添うようにします。</p></div>'''
    art["5"] = f'''<div class="sec"><div class="sec-h">第5条（介護保険の基準サービス）</div>
<p>事業所は、第3条に定めた地域密着型通所介護計画に沿って、{_esc(sv.get("svc_keiyaku"))}</p></div>'''
    art["6"] = '''<div class="sec"><div class="sec-h">第6条（サービス利用料金の支払い）</div>
<p>(1) 事業所は、ご契約者が支払うべき介護保険給付サービスに要した費用について、ご契約者が居宅介護サービス費として市町村から給付を受ける額（以下、介護保険給付額という）の限度において、ご契約者に代わって市町村から支払いを受けます。</p>
<p>(2) ご契約者は、要介護度に応じて第5条に定めるサービスを受け、重要事項説明書に定める所定の料金体系に基づいたサービス利用料金から介護保険給付額を差し引いた差額分（自己負担分）を事業所に支払うものとします。但し、ご契約者がいまだ要介護認定を受けていない場合及び居宅サービス計画が作成されていない場合には、サービス利用料金の全額をいったん支払うものとします。要介護認定後又は居宅サービス計画作成後、自己負担分を除く金額が介護保険から払い戻されます。（償還払い）</p>
<p>(3) ご契約者は前2項の他、ご契約者へのサービス提供上必要となる諸費用実費を、事業所に支払うものとします。</p>
<p>(4) 前第2項、第3項に定めるサービス利用料、及び諸費用実費は利用日数に基づいて1か月ごとに計算し、ご契約者はこれを翌月26日（休日の場合は翌営業日）までに、事業所が指定する方法で支払うものとします。</p></div>'''
    art["7"] = '''<div class="sec"><div class="sec-h">第7条（利用料金の変更）</div>
<p>(1) 前条第1項及び第2項に定めるサービス利用料金について、介護給付費体系の変更があった場合、事業所は当該サービス利用料金を変更することができるものとします。</p>
<p>(2) 前条第3項に定める諸費用実費については、経済状況の著しい変化その他やむを得ない事由がある場合、事業所は、ご契約者に対して、変更をおこなう日の1か月前までに説明をした上で、相当な額に変更することができるものとします。</p>
<p>(3) ご契約者は、前項の変更に同意することができない場合には、本契約を解約することができます。</p></div>'''
    art["8"] = '''<div class="sec"><div class="sec-h">第8条（サービスの中止）</div>
<p>事業所は、ご契約者の体調不良等の理由により、指定地域密着型通所介護の実施が困難と判断した場合、重要事項説明書に定める通り指定地域密着型通所介護を中止することができます。</p></div>'''
    art["9"] = f'''<div class="sec"><div class="sec-h">第9条（事業所及びサービス従事者の義務）</div>
<p>(1) 事業所及びサービス従事者は、指定地域密着型通所介護の提供にあたって、ご契約者の生命、身体、財産の安全確保に配慮するものとします。</p>
<p>(2) 事業所は、現に指定地域密着型通所介護の提供を行っているときにご契約者の病状の急変が生じた場合、その他必要な場合は、あらかじめ届けられた連絡先へ可能な限り速やかに連絡するとともに、医師または歯科医師等医療機関に連絡を取る等、必要な措置を講じます。</p>
<p>(3) 事業所及びサービス従事者は、ご契約者または他の利用者等の生命、身体を保護するため緊急やむを得ない場合を除き、身体的拘束その他、ご契約者の行動を制限する行為を行わないものとします。</p>
<p>(4) 事業所は、指定地域密着型通所介護の提供にあたり、居宅介護支援事業者及び保健医療サービスまたは福祉サービスを提供する者との密接な連携に努めます。</p>
<p>(5) 事業所は、第18条第1項から第5項に基づいて解約通知をする際は、事前に居宅介護支援事業者に連絡します。</p>
<p>(6) 事業所は、指定地域密着型通所介護の提供に関する記録を作成し5年間保管します。</p>
<p>(7) ご契約者または代理人は、{_esc(sv.get("kanran_time"))}から午後5時30分までの間に事業所にて、当該ご契約者に関する前項のサービス実施記録を閲覧できます。</p>
<p>(8) ご契約者または代理人は、所定の手続きを経た上で、当該ご契約者に関する第6項のサービス実施記録の複写物の交付を受けることができます。複写に係る実費は、ご契約者の負担となります。</p></div>'''
    art["10"] = '''<div class="sec"><div class="sec-h">第10条（守秘義務等）</div>
<p>(1) 事業所及びサービス従事者は、指定地域密着型通所介護を提供する上で知り得たご契約者また代理人等に関する事項を正当な理由なく第三者に漏洩しません。この守秘義務は、本契約が終了した後も継続します。</p>
<p>(2) 事業所は、ご契約者に医療上、緊急の必要性がある場合には、医療機関等にご契約者に関する心身等の情報を提供できるものとします。</p>
<p>(3) 事業所は、ご契約者からあらかじめ文書で同意を得ない限り、サービス担当者会議等において、その個人情報を用いません。</p></div>'''
    art["11"] = '''<div class="sec"><div class="sec-h">第11条（契約者の事業所利用上の注意義務等）</div>
<p>(1) ご契約者は、共用施設、設備等をその本来の用途に従って、利用するものとします。</p>
<p>(2) ご契約者は、事業所の建物、設備について、故意または重大な過失により滅失、破損、汚損、もしくは変更した場合には、自己の費用により原状に復するか、または相当の対価を支払うものとします。</p></div>'''
    art["12"] = '''<div class="sec"><div class="sec-h">第12条（損害賠償責任）</div>
<p>(1) 事業所は、本契約に基づく指定地域密着型通所介護の実施に伴って、自己の責に帰すべき事由によりご契約者に生じた損害について賠償する責任を負います。第10条に定める守秘義務に違反した場合も同様とします。但し、ご契約者に故意または過失が認められる場合には、ご契約者の置かれた心身の状況を斟酌して相当と認められる時に限り、損害賠償の全部または一部を減じることができるものとします。</p>
<p>(2) 事業所は、前項の損害賠償責任を速やかに履行するものとします。</p></div>'''
    art["13"] = '''<div class="sec"><div class="sec-h">第13条（損害賠償がなされない場合）</div>
<p>事業所は、自己の責に帰すべき事由がない限り、損害賠償を負いません。とりわけ以下の各号に該当する場合には、事業所は損害賠償責任を免れます。</p>
<p>(1) ご契約者が、契約締結時にその心身の状況及び病歴等の重要事項について、故意にこれを告げず、または不実の告知をおこなったことに起因して損害が発生した場合</p>
<p>(2) ご契約者が、指定地域密着型通所介護の実施にあたって必要な事項に関する聴取・確認に対して故意にこれを告げず、または不実の告知をおこなったことに起因して損害が発生した場合</p>
<p>(3) ご契約者の急激な体調の変化等、事業所の実施したサービスを原因としない事由に起因して損害が発生した場合</p>
<p>(4) ご契約者が、事業所もしくはサービス従事者の指示・依頼に反しておこなった行為に起因して損害が発生した場合</p></div>'''
    art["14"] = '''<div class="sec"><div class="sec-h">第14条（事業所の責任によらない事由によるサービスの実施不能）</div>
<p>事業所は本契約の有効期間中、地震等の天災その他自己の責に帰すべからざる事由により指定地域密着型通所介護の実施が出来なくなった場合には、ご契約者に対して既に実施したサービスを除いて、所定のサービス利用料金の支払いを請求することはできないものとします。</p></div>'''
    art["15"] = '''<div class="sec"><div class="sec-h">第15条（契約の終了事由）</div>
<p>本契約は以下の各号に基づく場合終了します。</p>
<p>(1) ご契約者が死亡した場合<br>(2) 要介護認定により、ご契約者の心身の状況が自立または要支援1、要支援2と判定された場合<br>(3) やむを得ない事由により事業所を閉鎖した場合<br>(4) 事業所の滅失や重大な毀損により、指定地域密着型通所介護の提供が不可能になった場合<br>(5) 事業所が介護保険の指定を取り消された場合または指定を辞退した場合<br>(6) 第7条第3項及び第16条から第18条に基づき本契約が解約または解除された場合</p></div>'''
    art["16"] = '''<div class="sec"><div class="sec-h">第16条（契約者からの中途解約等）</div>
<p>本契約の有効期限中、ご契約者は7日間の予告期間をおいて申し出ることにより、本契約を解約することができます。</p></div>'''
    art["17"] = '''<div class="sec"><div class="sec-h">第17条（契約者からの契約解除）</div>
<p>ご契約者は、事業所もしくはサービス従事者が以下の事項に該当する行為を行った場合には、本契約を解除することができます。</p>
<p>(1) 事業所もしくはサービス従事者が正当な理由なく本契約に定める指定地域密着型通所介護を実施しない場合<br>(2) 事業所もしくはサービス従事者が第10条に定める守秘義務に違反した場合<br>(3) 事業所もしくはサービス従事者が故意または過失により、ご契約者の身体・財物・信用等を傷つけ、または著しい不信行為、その他本契約を継続しがたい重大な事情が認められる場合<br>(4) 他の利用者がご契約者の身体・財物・信用等を傷つけた場合もしくは傷つける恐れがある場合において、事業所が適切な対応をとらない場合</p></div>'''
    art["18"] = '''<div class="sec"><div class="sec-h">第18条（事業所からの契約解除）</div>
<p>事業所は、ご契約者が以下の事項に該当する場合には、本契約を解除することができます。</p>
<p>(1) ご契約者が、契約締結時にその心身の状況及び病歴等の重要事項について、故意にこれを告げず、または不実の告知を行い、その結果本契約を継続しがたい重大な事情を生じさせた場合<br>(2) ご契約者による、第6条第2項に定めるサービス利用料金の支払いが3か月以上遅延し、催告した後も30日以内に支払われない場合<br>(3) ご契約者が、故意または重大な過失により事業所またはサービス従事者もしくは他の利用者等の生命・身体・財物・信用等を傷つけ、または著しい不信行為を行うことなどによって、本契約を継続しがたい重大な事情を生じさせた場合<br>(4) ご契約者が正当な理由なくサービスの中止をしばしば繰り返した場合、又はご契約者の入院、病気等により、3か月以上にわたってサービスが利用できない状態であることが明らかになった場合<br>(5) ご契約者が指定介護福祉施設等に入所した場合</p></div>'''
    art["19"] = '''<div class="sec"><div class="sec-h">第19条（苦情の対応）</div>
<p>事業所は、その提供したサービスに関するご契約者等からの苦情に対して、苦情を受け付ける窓口を設置して適切に対応するものとします。</p></div>'''
    art["20"] = '''<div class="sec"><div class="sec-h">第20条（協議事項）</div>
<p>本契約に定められていない事項について問題が生じた場合には、事業所は介護保険法その他諸法令の定めるところに従い、ご契約者と誠意を持って協議するものとします。</p></div>'''
    art["21"] = '''<div class="sec"><div class="sec-h">第21条（裁判管轄）</div>
<p>この契約に関してやむを得ず訴訟となる場合は、ご契約者及び事業所は、事業所の所在地を管轄する裁判所を第一審管轄裁判所とすることを予め合意します。</p></div>'''
    art["22"] = '''<div class="sec"><div class="sec-h">第22条（代理人）</div>
<p>(1) 代理人はご契約者とともにこの契約を履行するものとします。</p>
<p>(2) ご契約者はやむを得ない事由により、代理人を変更する場合は、所定の届出書を用いて、14日以内に届出を行います。</p></div>'''

    # overrides 適用（条文ごと: keiyaku_artN）
    for n in art:
        art[n] = _ov(F, f"keiyaku_art{n}", art[n])

    chapters = (
        '<div class="ch">第一章　総則</div>' + art["1"] + art["2"] + art["3"] + art["4"] + art["5"] +
        '<div class="ch">第二章　サービスの利用と料金の支払い</div>' + art["6"] + art["7"] + art["8"] +
        '<div class="ch">第三章　事業所の義務等</div>' + art["9"] + art["10"] +
        '<div class="ch">第四章　契約者の義務等</div>' + art["11"] +
        '<div class="ch">第五章　損害賠償</div>' + art["12"] + art["13"] + art["14"] +
        '<div class="ch">第六章　契約の終了</div>' + art["15"] + art["16"] + art["17"] + art["18"] +
        '<div class="ch">第七章　その他</div>' + art["19"] + art["20"] + art["21"] + art["22"]
    )

    # keiyaku-sign-v1: 押印は廃止したので「署名押印」→「署名」。
    sign = f'''<div class="sign">
<p>上記の契約を証するため、本書2通を作成し、ご契約者、代理人及び事業所が署名の上、各1通を保有するものとします。</p>
<p class="center">令和　　年　　月　　日</p>
<div class="sign-block"><p>【事業所】　事業所名　　　{jname}</p>
<p>　　　　　　事業所所在地　〒{_esc(j.get("zip"))}　{_esc(j.get("address"))}</p>
<p>　　　　　　事業者名　　　{_esc(h.get("name"))}</p>
<p>　　　　　　代表者名　　　{_esc(h.get("daihyo"))}</p></div>
<div class="sign-block">
<table class="sigtab">
<tr><td class="lbl">【ご契約者】</td><td class="lbl2">住所</td><td class="fill">〒</td><td class="sama"></td></tr>
<tr><td class="lbl"></td><td class="lbl2">氏名</td><td class="fill"></td><td class="sama">様</td></tr>
</table></div>
<div class="sign-block">
<table class="sigtab">
<tr><td class="lbl">【代理人】</td><td class="lbl2">住所</td><td class="fill">〒</td><td class="sama"></td></tr>
<tr><td class="lbl"></td><td class="lbl2">氏名</td><td class="fill"></td><td class="sama">様</td></tr>
</table></div></div>'''

    head = f'''<div class="doc-title">{jname} 利用契約書</div>
<div class="doc-sub">地域密着型通所介護</div>'''

    return '<div class="paper">' + head + chapters + sign + '</div>'


# ===== 印刷用CSS（wkhtmltopdf向け: @page margin 0、余白は .page-pad で実寸） =====
_PRINT_CSS = '''
@page{size:A4;margin:0}
html,body{margin:0;padding:0}
*{box-sizing:border-box}
body{font-family:"Noto Sans CJK JP","Noto Sans JP","Hiragino Kaku Gothic ProN",sans-serif;color:#000;line-height:1.55}
.page-pad{padding:13mm}
.page-break{page-break-before:always}
/* keiyaku-duplex-v1: 重説と契約書の間に入れる白紙。両面印刷で裏写りさせないため。 */
.blank-page{height:100%;color:#fff}
.doc-title{text-align:center;font-weight:700;font-size:15pt;margin:0 0 2mm}
.doc-sub{text-align:center;font-size:10.5pt;margin:0 0 5mm}
.ch{font-weight:700;font-size:11.5pt;text-align:center;background:#eef3f1;padding:2mm 0;margin:3.5mm 0 2.5mm;letter-spacing:1px;page-break-after:avoid}
.sec{margin:0 0 3mm;page-break-inside:avoid}
.sec-h{font-weight:700;font-size:10pt;border-left:4px solid #2f6b5e;padding-left:6px;margin:0 0 1.5mm;page-break-after:avoid}
.tokki-sec .tokki-item{margin:0 0 2mm;page-break-inside:avoid}
.tokki-name{font-weight:700;font-size:9pt;margin:0 0 0.5mm}
.tokki-body{font-size:9pt;line-height:1.55;white-space:normal}
.sec p,.paper>p{margin:0 0 1.5mm;font-size:9pt;line-height:1.55}
.center{text-align:center}
.note{font-size:7.5pt;color:#333;margin:1mm 0;line-height:1.5}
.sub{font-size:7.5pt;color:#555}
.ptab{border-collapse:collapse;width:100%;font-size:8.5pt;margin:1.5mm 0;page-break-inside:avoid}
.ptab th,.ptab td{border:1px solid #555;padding:2px 4px;text-align:center;line-height:1.35}
/* keiyaku-fix-v1 / keiyaku-sign-v1: 手書きする欄は窮屈だと書けない。
   記入用の表だけ高さを持たせる（.L 全部に高さを付けると料金表まで間延びする）。
   案内文字（氏名／連絡先 など）は文字幅ぶんだけ取り、残りを全部「書く枠」にする。 */
.ptab.fill td{height:12mm;vertical-align:bottom}
/* ラベルと案内文字は文字幅ぶんだけ。残りは全部「書く枠」にする。 */
.ptab.fill td.k{width:30mm;white-space:nowrap;vertical-align:middle}
.ptab.fill td.hint{width:1%;white-space:nowrap;color:#999;font-size:7pt;
  text-align:left;vertical-align:bottom;padding:0 1mm 1mm 3px;border-right:none}
.ptab.fill td.wr{border-left:none}
.ptab.kujo td.k{width:38mm;white-space:nowrap}

/* 署名欄。ページ幅いっぱいの下線はやめ、書く欄の下だけに線を引く。
   ラベルは文字幅ぶんに詰め、書く欄をできるだけ広く取る。 */
.sigtab{width:100%;border-collapse:collapse;margin:3mm 0 1mm;font-size:9pt}
.sigtab td{padding:1mm 1.5mm;vertical-align:bottom;height:13mm}
.sigtab td.lbl{white-space:nowrap;width:1%;text-align:left;padding-right:3mm}
/* 「住所」「氏名」を同じ列にそろえるための2つ目のラベル列 */
.sigtab td.lbl2{white-space:nowrap;width:1%;text-align:left;padding-right:3mm}
.sigtab td.fill{border-bottom:1px solid #333;color:#555}
.sigtab td.w2{width:30mm}
.sigtab td.sama{white-space:nowrap;padding-left:2.5mm;width:1%}
.ptab th{background:#eef3f1;font-weight:700}
.ptab td.k{text-align:left;white-space:nowrap;background:#f7f6f3}
.ptab .L,.ptab td.L,.ptab th.L{text-align:left}
.ptab.fee th,.ptab.fee td{padding:2px 4px;font-size:8.5pt}
.ptab.fee .hh{background:#dfeae6;white-space:nowrap}
.ptab.fee .u{font-weight:400;font-size:7pt;color:#444}
.ptab.fee .wari{background:#dfeae6;font-weight:700;white-space:nowrap;border-top:2px solid #555}
.ptab.fee .kai{white-space:nowrap;background:#f7f6f3}
.ptab.fee td:not(.wari):not(.kai){text-align:right;white-space:nowrap}
.sign{margin-top:5mm;font-size:9pt}

.sign-block p{margin:0 0 1.5mm}
/* keiyaku-fix-v1: 署名欄は手書きするので、行の高さに余裕を持たせる */
.sign .r{display:flex;justify-content:space-between;align-items:flex-end;
  border-bottom:1px solid #999;padding:7mm 0 1.5mm;margin-bottom:2mm;min-height:11mm}
.sign-block{margin:3.5mm 0;padding:2.5mm 0;border-top:1px dashed #ccc;page-break-inside:avoid}
'''


def render_print_html(F, doc, st, blank_between=False):
    """印刷用の完全HTMLを返す。
    doc: 'juyo' | 'keiyaku' | 'both'
    st : 'han' | 'ichi'
    blank_between: keiyaku-duplex-v1
        True にすると、重説と契約書の間に白紙を1枚挟む。
        重説が奇数ページで終わったとき、両面印刷で契約書が重説の裏に
        刷られてしまうのを防ぐため。呼び出し側がページ数を見て決める。
    """
    if st not in ("han", "ichi"):
        st = "han"
    blocks = []
    if doc in ("juyo", "both"):
        blocks.append('<div class="page-pad">' + render_juyo(F, st) + '</div>')
    if doc == "both" and blank_between:
        # 白紙。中身が空だとページとして数えられないので、見えない文字を1つ置く。
        blocks.append('<div class="page-pad page-break blank-page">&nbsp;</div>')
    if doc in ("keiyaku", "both"):
        cls = "page-pad page-break" if doc == "both" else "page-pad"
        blocks.append(f'<div class="{cls}">' + render_keiyaku(F, st) + '</div>')
    body = "".join(blocks)
    return ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            f'<style>{_PRINT_CSS}</style></head><body>{body}</body></html>')
