#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEVに入れてしまった届出のデータを、本番へ写す。

使い方
------
  python3 copy_todokede_dev_to_prod.py          … 【見るだけ】何が写るかを出して止まる
  python3 copy_todokede_dev_to_prod.py --go     … 本当に写す

決めごと
--------
★鍵は画面に出ません。打った文字も表示されず、コマンド履歴にも残りません。
  （環境変数に入っていればそれを使います。無ければ聞きます）
★まず「見るだけ」で走ります。件数と中身を見てから --go を付けてください。
★DEVは【読むだけ】です。このスクリプトはDEVを1文字も変えません。
  消すのは、写し終わったあとにDEVの画面から。
★すでに本番にあるものは飛ばします。二度流しても二重になりません。
★施設コードを差し替えます。DEVは DEMO001、本番は cocokaraplus-5526 なので、
  そのまま写すと本番で【誰にも見えない】届出になります。
  ファイルの置き場所（todokede/DEMO001/...）も一緒に差し替えます。
★追加の道具は要りません（Python標準のものだけ）。

先にやっておくこと
------------------
  ① 本番にコードを流してある（git merge → push）
  ② 本番のSupabaseで ddl_todokede_v1.sql の7つを流してある
  表が無いと、ここで止まります。
"""

import os
import sys
import json
import getpass
import urllib.request
import urllib.error
import urllib.parse

BUCKET = os.environ.get("TODOKEDE_BUCKET", "case-photos")
FROM_FCODE = os.environ.get("FROM_FCODE", "DEMO001")
TO_FCODE = os.environ.get("TO_FCODE", "cocokaraplus-5526")

GO = "--go" in sys.argv


def ask(label, env_key, secret=False):
    v = os.environ.get(env_key)
    if v:
        print("  %s: 環境変数 %s を使います" % (label, env_key))
        return v.strip()
    if secret:
        return getpass.getpass("  %s（画面には出ません）: " % label).strip()
    return input("  %s: " % label).strip()


def call(url, key, path, method="GET", body=None, headers=None, raw=False):
    """SupabaseのRESTを叩く。返りは (ステータス, 中身)。"""
    h = {"apikey": key, "Authorization": "Bearer " + key}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        if raw:
            data = body
        else:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
    req = urllib.request.Request(url.rstrip("/") + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode("utf-8")


def rows(url, key, table, query):
    st, body = call(url, key, "/rest/v1/%s?%s" % (table, query))
    if st != 200:
        raise SystemExit("★%s を読めませんでした（%s）: %s" % (table, st, body.decode("utf-8", "ignore")[:300]))
    return json.loads(body.decode("utf-8"))


def main():
    if FROM_FCODE == TO_FCODE:
        raise SystemExit("★写し元と写し先の施設コードが同じです。差し替える意味がありません。")

    print("")
    print("=" * 56)
    print(" 届出データを DEV → 本番 へ写します")
    print("   施設コード : %s  →  %s" % (FROM_FCODE, TO_FCODE))
    print("   保管庫     : %s" % BUCKET)
    print("   いまの動き : %s" % ("★本当に写します（--go）" if GO else "見るだけ（書き込みません）"))
    print("=" * 56)
    print("")
    print("【DEV（写し元）】")
    dev_url = ask("DEVのURL（https://xxxx.supabase.co）", "DEV_SUPABASE_URL")
    dev_key = ask("DEVのサービスキー", "DEV_SUPABASE_KEY", secret=True)
    print("")
    print("【本番（写し先）】")
    prd_url = ask("本番のURL（https://xxxx.supabase.co）", "PROD_SUPABASE_URL")
    prd_key = ask("本番のサービスキー", "PROD_SUPABASE_KEY", secret=True)
    print("")

    if not (dev_url and dev_key and prd_url and prd_key):
        raise SystemExit("★入力が足りません。")
    if dev_url.rstrip("/") == prd_url.rstrip("/"):
        raise SystemExit("★DEVと本番に同じURLが入っています。取り違えていませんか。")

    q = urllib.parse.quote(FROM_FCODE, safe="")
    recs = rows(dev_url, dev_key, "todokede_records",
                "facility_code=eq.%s&select=*&order=filed_ym.asc" % q)
    files = rows(dev_url, dev_key, "todokede_files",
                 "facility_code=eq.%s&select=*&order=created_at.asc" % q)
    if not recs:
        raise SystemExit("★DEVに %s の届出がありません。施設コードを確かめてください。" % FROM_FCODE)

    # 本番にもう入っているものは飛ばす
    have = set(x["id"] for x in rows(prd_url, prd_key, "todokede_records",
                                     "select=id&limit=10000"))
    have_f = set(x["id"] for x in rows(prd_url, prd_key, "todokede_files",
                                       "select=id&limit=10000"))

    by_rec = {}
    for f in files:
        by_rec.setdefault(f.get("record_id"), []).append(f)

    print("【写すもの】")
    n_r = n_f = 0
    for r in recs:
        mark = "（本番にすでにあります・飛ばします）" if r["id"] in have else ""
        print("  %s  %s  %s %s" % (r.get("filed_ym"), r.get("doc_type"),
                                   (r.get("summary") or "")[:34], mark))
        if r["id"] not in have:
            n_r += 1
        for f in by_rec.get(r["id"], []):
            m2 = "（あり・飛ばす）" if f["id"] in have_f else ""
            print("      └ %s  %s %s" % (f.get("kind"), f.get("file_name"), m2))
            if f["id"] not in have_f:
                n_f += 1
    print("")
    print("  届出 %d件 / 書類 %d枚 を写します" % (n_r, n_f))
    print("")

    if not GO:
        print("見るだけで終わりました。よければ、同じコマンドに --go を付けて流してください。")
        print("  python3 copy_todokede_dev_to_prod.py --go")
        return

    if n_r == 0 and n_f == 0:
        print("写すものがありません。終わります。")
        return

    # ---- ① 届出の行（★先に入れる。書類がこれを指しているため）----
    put_r = []
    for r in recs:
        if r["id"] in have:
            continue
        x = dict(r)
        x["facility_code"] = TO_FCODE
        put_r.append(x)
    if put_r:
        st, body = call(prd_url, prd_key, "/rest/v1/todokede_records", "POST", put_r,
                        {"Prefer": "return=minimal"})
        if st not in (200, 201, 204):
            raise SystemExit("★届出を入れられませんでした（%s）: %s"
                             % (st, body.decode("utf-8", "ignore")[:400]))
        print("  届出 %d件を入れました" % len(put_r))

    # ---- ② 書類（DEVから落として、本番へ上げて、行を入れる）----
    ok = ng = 0
    for f in files:
        if f["id"] in have_f:
            continue
        old_path = f["storage_path"]
        new_path = old_path.replace("todokede/%s/" % FROM_FCODE, "todokede/%s/" % TO_FCODE, 1)
        if new_path == old_path:
            print("  ★置き場所を差し替えられません（飛ばします）: %s" % old_path)
            ng += 1
            continue
        st, blob = call(dev_url, dev_key,
                        "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(old_path)))
        if st != 200:
            print("  ★DEVから落とせません（飛ばします）: %s" % f.get("file_name"))
            ng += 1
            continue
        st, body = call(prd_url, prd_key,
                        "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(new_path)),
                        "POST", blob,
                        {"Content-Type": f.get("mime") or "application/octet-stream",
                         "x-upsert": "true"}, raw=True)
        if st not in (200, 201):
            print("  ★本番へ上げられません（飛ばします）: %s / %s"
                  % (f.get("file_name"), body.decode("utf-8", "ignore")[:160]))
            ng += 1
            continue
        x = dict(f)
        x["facility_code"] = TO_FCODE
        x["storage_path"] = new_path
        st, body = call(prd_url, prd_key, "/rest/v1/todokede_files", "POST", [x],
                        {"Prefer": "return=minimal"})
        if st not in (200, 201, 204):
            # ★行を入れられなかったら、上げたファイルは置き去りになる。名前を出しておく。
            print("  ★行を入れられません: %s / %s"
                  % (f.get("file_name"), body.decode("utf-8", "ignore")[:160]))
            print("     （本番の保管庫に %s が残っています）" % new_path)
            ng += 1
            continue
        ok += 1
        print("  書類 %s を写しました" % f.get("file_name"))

    print("")
    print("=" * 56)
    print(" 終わりました。書類 %d枚を写しました%s" % (ok, ("（%d枚は写せませんでした）" % ng) if ng else ""))
    print("")
    print(" 本番の 管理者MENU → 運営・契約 →「介護保険課への届出」で、")
    print(" 年ごとに並んでいること、一式が取り出せることを見てください。")
    print("")
    print(" ★DEVのデータは1文字も触っていません。")
    print("   確かめたあと、DEVの画面から「この届出を消す」で消してください。")
    print("=" * 56)


if __name__ == "__main__":
    main()
