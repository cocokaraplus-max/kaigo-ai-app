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
    """keiyaku-timeclass-v1: adds から処遇改善率を取得。shoguu_type 優先、無ければ既定Ⅱロ。
    旧データ(shoguu:bool のみ)は True で 12.5%、False/未設定で 0。"""
    if not adds.get("shoguu"):
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
    tc = _resolve_tc(F, st)
    per_visit = _BASE[tc][lv] + (_KUNREN1 if adds.get("kunren1") else 0)
    monthly = per_visit * visits
    if adds.get("kunren2"):
        monthly += _KUNREN2
    if adds.get("kagaku"):
        monthly += _KAGAKU
    rate = _shoguu_rate(adds)
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
<p>{_adds_line(F)}</p>
<p class="note">上記加算率にて算出した単位（一単位未満の端数四捨五入）　※当該加算は、すべてのご契約者に加算されます。　※区分支給限度基準額の算定対象外です。</p></div>'''

    sec_jihi = f'''<div class="sec"><div class="sec-h">自費料金・その他の費用</div>
{_jihi_table(F)}
<p class="note">通常の事業の実施地域を越えて行う送迎費用：片道5km未満200円（税込）／片道5km以上400円（税込）。サービス提供時間を超えて行った通所介護の費用：30分あたり500円（税込）。レクリエーションに係る費用等は自己負担となります。</p></div>'''

    sec_shiharai = f'''<div class="sec"><div class="sec-h">利用料のお支払方法（契約書第6条参照）</div>
<p>前記の料金・費用は{_esc(un.get("shime"))}のうえ1か月ごとに計算し、{_esc(un.get("seikyu_date"))}に前月分の請求書をお渡しいたします。お支払いは利用者様ご指定の口座より、{_esc(un.get("hikiotoshi_date"))}に口座自動引落となります。引落に必要な手数料は事業所で負担します。事業所は料金の支払いを受けたときは領収証を発行します。</p></div>'''

    sec_kinkyu = '''<div class="sec"><div class="sec-h">緊急時の対応方法と健康上の理由による利用中止について</div>
<p>①ご契約者に容体の変化等があった場合は、医師または歯科医師など医療機関に連絡をとるなど必要な措置を講じるほか、緊急連絡先に速やかに連絡いたします。②風邪・病気の場合および当日の健康チェックの結果体調が不調の場合は、サービス内容の変更またはサービスを中止することがあります。</p>
<table class="ptab"><tr><td class="k">主治医</td><td class="L">氏名／連絡先</td></tr><tr><td class="k">緊急時の病院</td><td class="L">病院名</td></tr><tr><td class="k">ご家族</td><td class="L">氏名／連絡先</td></tr></table></div>'''

    sec_shuryo = '''<div class="sec"><div class="sec-h">契約の終了について（契約書第15条参照）</div>
<p>当事業所との契約では契約が終了する期日は特に定めていません。以下のような事由がない限り継続してサービスを利用できますが、該当するに至った場合には書面による契約解除を交わすことなく契約は終了します。①ご契約者が死亡した場合　②要介護認定により自立または要支援1・要支援2と判定された場合　③やむを得ない事由により事業所を閉鎖した場合　④事業所の重大な毀損により提供が不可能になった場合　⑤介護保険の指定を取り消された場合または辞退した場合　⑥ご契約者から中途解約・契約解除の申し出があった場合　⑦事業所から退所の申し出を行った場合</p></div>'''

    sec_kujo = f'''<div class="sec"><div class="sec-h">サービス内容に関する苦情と相談</div>
<p>当事業所ご利用相談・苦情担当　【受付時間】{_esc(ku.get("time"))}<br>苦情受付担当者　{_esc(ku.get("uketsuke"))}　TEL{_esc(ku.get("uketsuke_tel"))}／苦情対応担当者　{_esc(ku.get("taio"))}／苦情解決責任者　{_esc(ku.get("sekinin"))}</p>
<p class="note">下記の窓口でも受け付けております。{_esc(ho.get("name"))}　介護保険課　TEL {_esc(ho.get("kaigo_tel"))}　FAX {_esc(ho.get("kaigo_fax"))}／{_esc(ho.get("kokuho_name"))}　TEL {_esc(ho.get("kokuho_tel"))}　FAX {_esc(ho.get("kokuho_fax"))}</p></div>'''

    sec_saigai = '''<div class="sec"><div class="sec-h">非常災害時の対応方法</div><p>災害発生時にはスタッフが速やかに最寄りの避難所まで誘導いたします。スタッフの指示に従って行動をお願いいたします。</p></div>'''

    sec_souchou = '''<div class="sec"><div class="sec-h">早朝ご連絡時の注意点</div><p>当日のキャンセル連絡を早朝にされる場合には、8:00〜8:15の時間でご連絡いただけるようお願いいたします。それ以外の時間ですと送迎等でスタッフが不在の場合がございます。</p></div>'''

    sign = f'''<div class="sign">
<p>指定地域密着型通所介護の提供の開始に際し、本書面に基づき重要事項の説明を行いました。</p>
<p class="center">令和　　年　　月　　日</p>
<div class="sign-block"><p>{_esc(j.get("name"))}</p><div class="r"><span>説明者　職名　　　　　　氏名</span><span>㊞</span></div></div>
<p>私は、本書面に基づいて事業所から重要事項の説明を受け、指定地域密着型通所介護の開始に同意しました。</p>
<div class="sign-block"><div class="r"><span>ご契約者　　　　　　　　　　様</span><span>㊞</span></div><div class="r"><span>代理人</span><span>㊞</span></div></div></div>'''

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

    sign = f'''<div class="sign">
<p>上記の契約を証するため、本書2通を作成し、ご契約者、代理人及び事業所が署名押印の上、各1通を保有するものとします。</p>
<p class="center">令和　　年　　月　　日</p>
<div class="sign-block"><p>【事業所】　事業所名　　　{jname}</p>
<p>　　　　　　事業所所在地　〒{_esc(j.get("zip"))}　{_esc(j.get("address"))}</p>
<p>　　　　　　事業者名　　　{_esc(h.get("name"))}</p>
<div class="r"><span>　　　　　　代表者名　　　{_esc(h.get("daihyo"))}</span><span>㊞</span></div></div>
<div class="sign-block"><div class="r"><span>【ご契約者】　住所　〒</span><span></span></div><div class="r"><span>　　　　　　　氏名</span><span>㊞</span></div></div>
<div class="sign-block"><div class="r"><span>【代理人】　　住所　〒</span><span></span></div><div class="r"><span>　　　　　　　氏名</span><span>㊞</span></div></div></div>'''

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
.sign-block{margin:2.5mm 0;padding:2mm 0;border-top:1px dashed #ccc;page-break-inside:avoid}
.sign-block p{margin:0 0 1.5mm}
.sign .r{display:flex;justify-content:space-between;border-bottom:1px solid #999;padding:2.5mm 0 1mm;margin-bottom:1mm}
'''


def render_print_html(F, doc, st):
    """印刷用の完全HTMLを返す。
    doc: 'juyo' | 'keiyaku' | 'both'
    st : 'han' | 'ichi'
    """
    if st not in ("han", "ichi"):
        st = "han"
    blocks = []
    if doc in ("juyo", "both"):
        blocks.append('<div class="page-pad">' + render_juyo(F, st) + '</div>')
    if doc in ("keiyaku", "both"):
        cls = "page-pad page-break" if doc == "both" else "page-pad"
        blocks.append(f'<div class="{cls}">' + render_keiyaku(F, st) + '</div>')
    body = "".join(blocks)
    return ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            f'<style>{_PRINT_CSS}</style></head><body>{body}</body></html>')
