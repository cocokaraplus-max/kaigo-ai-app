# -*- coding: utf-8 -*-
"""
keiyaku_seed_cocokara.py  (marker: keiyaku-seed-v1)
ココカラプラス（cocokaraplus-5526）の契約書・重要事項説明書 初期データ。

投入先キー（admin_settings）:
  keiyaku_facility : 法人/事業所/サービス種別/第三者評価/運営/苦情/保険者 等
  keiyaku_jihi     : 自費項目の配列
  keiyaku_staff    : 職員配置の配列
  keiyaku_adds     : 取得加算の選択

app.py の初期データ投入APIから import して使用。
"""

KEIYAKU_FACILITY = {
    "houjin": {
        "name": "合同会社LIFE PLUS",
        "name_kana": "ゴウドウガイシャ　ライフプラス",
        "zip": "471-0832",
        "address": "愛知県豊田市丸山町7丁目49番地6",
        "tel": "(0565)27-2837",
        "fax": "(0565)41-7814",
        "daihyo": "岸本　洋幸",
        "founded": "平成26年11月19日",
    },
    "jigyosho": {
        "type": "指定地域密着型通所介護事業所",
        "type_date": "平成27年4月1日指定",
        "shitei_no": "2373003330",
        "name": "機能訓練型デイサービス　ココカラプラス",
        "zip": "471-0832",
        "address": "愛知県豊田市丸山町7丁目49番地6",
        "tel": "(0565)41-7804",
        "fax": "(0565)41-7814",
        "kanrisha": "岸本　洋幸",
        "opened": "平成27年4月1日",
        "area": "（豊南、朝日丘、竜神、末野原）中学校区　＊その他の地域の方は相談下さい。",
        "setsubi": "食堂兼機能訓練室1室、静養室1室、送迎車両4台、相談室1室",
    },
    "service": {
        "han": {
            "teiin": "午前10名、午後10名",
            "eigyobi": "月～金曜日（祝日は営業しております）／土曜日・日曜日は定休日",
            "eigyo_time": "午前8時30分～午後17時30分",
            "teikyo_time": "午前の部：9時00分〜12時00分　午後の部：13時00分〜16時00分",
            "teikyo_hours": "3時間",
            "svc_naiyo": "送迎、おやつの提供、その他必要な介護",
            "svc_keiyaku": "送迎、おやつの提供、その他必要な介護をおこないます。",
            "kanran_time": "午前9時00分",
        },
        "ichi": {
            "teiin": "10名",
            "eigyobi": "日曜日のみ営業",
            "eigyo_time": "9時00分～17時30分",
            "teikyo_time": "9時30分〜16時30分",
            "teikyo_hours": "7時間",
            "svc_naiyo": "送迎、食事・おやつの提供、その他必要な介護",
            "svc_keiyaku": "送迎、お食事・おやつの提供、その他必要な介護をおこないます。",
            "kanran_time": "午前9時30分",
        },
    },
    "hyoka": {
        "jisshi": True,
        "last_date": "令和2年3月7日",
        "kikan": "株式会社ユニバーサルリンク愛知調査室",
        "note": "介護サービス情報公表システムに情報の公表をしております。",
    },
    "unei": {
        "houshin": "事業所の従事者は、ご契約者の要介護状態等の心身の特徴を踏まえて、可能な限りその居宅において、その有する能力に応じ自立した生活を営むことができるよう、さらに、利用者の社会的孤立感の解消および心身機能の維持並びに家族の身体的・精神的負担の軽減を図るために、必要な日常生活上の介護および機能訓練等、その他必要な事業を行うものとします。",
        "shime": "月末締め",
        "seikyu_date": "毎月15日まで",
        "hikiotoshi_date": "毎月26日",
    },
    "kujo": {
        "uketsuke": "生活相談員　　加藤鮎美",
        "uketsuke_tel": "(0565)41-7804",
        "taio": "管理者　　　　岸本洋幸",
        "sekinin": "統括事業所長　岸本洋幸",
        "time": "8：30〜17：30",
    },
    "hokensha": {
        "name": "豊田市",
        "kaigo_tel": "0565-34-6634",
        "kaigo_fax": "0565-34-6793",
        "kokuho_name": "愛知県国民健康保険団体連合会",
        "kokuho_tel": "052-971-4165",
        "kokuho_fax": "052-962-8870",
    },
    "area_level": 3,
    "visits_per_month": 4,
}

KEIYAKU_JIHI = [
    {"name": "お飲み物代", "price": "200", "unit": "1日", "note": "サービス時間内は、すべてのお飲み物が上記金額でお飲みいただけます。"},
    {"name": "おむつ代", "price": "150", "unit": "1枚", "note": ""},
    {"name": "パット代", "price": "50", "unit": "1枚", "note": ""},
    {"name": "リハビリパンツ代", "price": "150", "unit": "1枚", "note": ""},
    {"name": "キャンセル料", "price": "2,000", "unit": "1回", "note": "サービス実施中の帰宅や救急搬送など3時間の利用に満たない場合（介護保険の請求ができないため）"},
    {"name": "実施記録の複写", "price": "10", "unit": "1枚", "note": "サービス実施記録等の複写物を請求した場合"},
]

KEIYAKU_STAFF = [
    {"role": "管理者", "work": "事業の管理、運営", "count": "0.5名（機能訓練指導員兼務）"},
    {"role": "生活相談員", "work": "相談援助業務、業務管理等", "count": "1名"},
    {"role": "介護職員", "work": "利用者の介護業務", "count": "3.2名"},
    {"role": "機能訓練指導員", "work": "機能訓練の指導", "count": "0.5名（柔道整復師）"},
]

KEIYAKU_ADDS = {"kunren1": True, "kunren2": True, "kagaku": True, "shoguu": True}
