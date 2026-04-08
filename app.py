import streamlit as st
import os
import uuid
import time
from supabase import create_client
from utils import init_config, init_clients, get_cookie_manager, display_logo, apply_custom_style, get_facility_config, tokyo_tz
import views

# --- 1. PWA・アイコン設定（スマホのホーム画面用） ---
def set_app_manifest():
    # ロゴのURL（GitHub上のRawデータを指定）
    # ※あなたのユーザー名とリポジトリ名に書き換えてくれ！
    icon_url = "https://raw.githubusercontent.com/cocokaraplus-max/kaigo-ai-app/cloudrun/assets/logo.png"
    
    st.markdown(f"""
        <head>
            <title>TASUKARU</title>
            <link rel="apple-touch-icon" href="{icon_url}">
            <link rel="icon" type="image/png" href="{icon_url}">
            <meta name="theme-color" content="#ff4b4b">
            <meta name="apple-mobile-web-app-capable" content="yes">
            <meta name="apple-mobile-web-app-status-bar-style" content="default">
        </head>
    """, unsafe_allow_html=True)

# システム初期化
init_config()
set_app_manifest()

# --- 2. 環境変数取得（今回の勝利の鍵） ---
def get_safe_secret(key):
    # Cloud Runの環境変数を最優先、次にStreamlit Secretsを確認
    val = os.environ.get(key) or st.secrets.get(key)
    if val:
        return str(val).strip().strip('"').strip("'")
    return None

SUPABASE_URL = get_safe_secret("SUPABASE_URL")
SUPABASE_KEY = get_safe_secret("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("🚨 接続設定（URL/KEY）が読み込めません。Cloud Runの環境変数を確認してください。")
    st.stop()

# クライアント初期化
try:
    _ = init_clients()
except:
    pass

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 3. セッションとクッキーの管理 ---
cookie_manager = get_cookie_manager()
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# クッキー読み込みの同期
cookies = cookie_manager.get_all()
if not cookies:
    time.sleep(0.5)
    st.rerun()

device_id = cookies.get("device_id") or str(uuid.uuid4())

# --- 4. 認証処理 ---
if not st.session_state.get("is_authenticated"):
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

# --- 5. メイン画面の描画 ---
f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

try:
    # 施設ごとのカラー設定などをDBから取得
    f_config = get_facility_config(supabase, f_code)
    apply_custom_style(f_config.get("primary_color", "#ff4b4b"))
except:
    apply_custom_style("#ff4b4b")

p = st.session_state["page"]
if p == "admin_menu":
    views.render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id)
else:
    pages = {
        "top": views.render_top,
        "input": views.render_input,
        "history": views.render_history,
        "daily_view": views.render_daily_view
    }
    pages[p](supabase, cookie_manager, f_code, my_name)
