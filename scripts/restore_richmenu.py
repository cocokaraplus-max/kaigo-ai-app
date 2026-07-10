# -*- coding: utf-8 -*-
# TASUKARU 職員用リッチメニュー復旧スクリプト (restore-richmenu-v1)
# 使い方(トークンを画面に出さずCloud Runの値を直接渡す):
#   LINE_CHANNEL_ACCESS_TOKEN=$(gcloud run services describe tasukaru \
#     --region asia-northeast1 \
#     --format="value(spec.template.spec.containers[0].env[?(@.name=='LINE_CHANNEL_ACCESS_TOKEN')].value)") \
#   IMG=~/Downloads/richmenu_final3.png python3 restore_richmenu.py
#
# 動作(冪等):
#   1) 既存のデフォルトリッチメニューを解除・全リッチメニュー削除
#   2) 新規リッチメニュー作成(3ボタン)
#   3) final3画像をアップロード
#   4) デフォルトに設定
# トークンは os.environ から読むのみ。絶対にprintしない。
import os, sys, json, ssl, urllib.request, urllib.error

# Mac(Python公式版)のSSL証明書問題対策: certifiがあれば使う
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
IMG_PATH = os.path.expanduser(os.environ.get("IMG", "~/Downloads/richmenu_final3.png"))

if not TOKEN:
    print("ERROR: LINE_CHANNEL_ACCESS_TOKEN が渡されていません。")
    print("  Cloud Runの値を環境変数で渡してください(READMEの使い方参照)。")
    sys.exit(1)
if not os.path.exists(IMG_PATH):
    print(f"ERROR: 画像が見つかりません: {IMG_PATH}")
    sys.exit(1)

API = "https://api.line.me/v2/bot"
API_DATA = "https://api-data.line.me/v2/bot"
AUTH = {"Authorization": "Bearer " + TOKEN}


def _req(url, method="GET", headers=None, data=None):
    h = dict(AUTH)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX) as res:
            body = res.read().decode("utf-8") if res.length != 0 else ""
            return res.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


# --- リッチメニュー定義: 2500x843 を横3分割(各833/834px) ---
# 左: 利用開始(LIFF), 中: パスワード再発行(message"パスワード"), 右: アプリ改善依頼(message"アプリ改善依頼")
RICHMENU = {
    "size": {"width": 2500, "height": 843},
    "selected": True,
    "name": "TASUKARU職員メニュー",
    "chatBarText": "メニュー",
    "areas": [
        {"bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
         "action": {"type": "uri", "uri": "https://liff.line.me/2010588249-eVxq4tL5"}},
        {"bounds": {"x": 833, "y": 0, "width": 833, "height": 843},
         "action": {"type": "message", "text": "パスワード"}},
        {"bounds": {"x": 1666, "y": 0, "width": 834, "height": 843},
         "action": {"type": "message", "text": "アプリ改善依頼"}},
    ],
}


def main():
    print("=== TASUKARU リッチメニュー復旧 ===")

    # 1) 既存リッチメニューを全削除(冪等化)
    st, body = _req(API + "/richmenu/list")
    if st == 200:
        menus = json.loads(body).get("richmenus", [])
        print(f"既存リッチメニュー: {len(menus)}件")
        for m in menus:
            rid = m.get("richMenuId")
            ds, _ = _req(API + "/richmenu/" + rid, method="DELETE")
            print(f"  削除 {rid[:12]}... -> {ds}")
    else:
        print(f"list取得 失敗: HTTP {st} {body[:200]}")

    # 2) 新規作成
    data = json.dumps(RICHMENU).encode("utf-8")
    st, body = _req(API + "/richmenu", method="POST",
                    headers={"Content-Type": "application/json"}, data=data)
    if st != 200:
        print(f"作成 失敗: HTTP {st} {body[:300]}")
        sys.exit(1)
    rid = json.loads(body).get("richMenuId")
    print(f"作成OK richMenuId={rid[:16]}...")

    # 3) 画像アップロード
    with open(IMG_PATH, "rb") as f:
        img = f.read()
    st, body = _req(API_DATA + "/richmenu/" + rid + "/content", method="POST",
                    headers={"Content-Type": "image/png"}, data=img)
    if st != 200:
        print(f"画像アップロード 失敗: HTTP {st} {body[:300]}")
        # 失敗したら作りかけを削除
        _req(API + "/richmenu/" + rid, method="DELETE")
        sys.exit(1)
    print(f"画像アップロードOK ({len(img)} bytes)")

    # 4) デフォルト設定
    st, body = _req(API + "/user/all/richmenu/" + rid, method="POST")
    if st != 200:
        print(f"デフォルト設定 失敗: HTTP {st} {body[:300]}")
        sys.exit(1)
    print("デフォルト設定OK")
    print("=== 復旧完了。LINEアプリで確認してください ===")


if __name__ == "__main__":
    main()
