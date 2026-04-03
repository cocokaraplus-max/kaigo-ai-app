import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, date
import pytz 
from supabase import create_client, Client # type: ignore
import uuid
import time
from PIL import Image # type: ignore
import extra_streamlit_components as stx 
import unicodedata
import re

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

cookie_manager = stx.CookieManager()

# --- 🎨 カスタムCSS（画面固定ボタン & 視認性向上） ---
st.markdown("""
    <style>
    /* 管理者メニューのタイトル */
    .admin-title {
        font-size: 22px; font-weight: bold; color: #ff4b4b !important;
        padding-bottom: 10px; border-bottom: 2px solid #ff4b4b;
        margin-bottom: 20px; display: block;
    }
    
    /* タブとラベルの視認性 */
    .stTabs [data-baseweb="tab-list"] button {
        color: #31333F !important; font-size: 16px !important; font-weight: 600 !important;
    }
    .stTabs [aria-selected="true"] { color: #ff4b4b !important; }
    .stMarkdown p, .stText, label { color: #31333F !important; }
    div[data-baseweb="select"] > div { color: #31333F !important; }

    /* 🚀 スマホ用：画面下部固定の「TOPに戻る」ボタン設定 */
    @media (max-width: 768px) {
        .stButton > button[data-testid="baseButton-secondary"] {
            /* '◀ TOP' という文字を含むボタンを特定してスタイル適用 */
        }
        
        /* 特定のクラスを付与できないため、下部の固定エリアを作成 */
        .fixed-bottom-nav {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 999;
        }
    }
    
    /* 固定ボタンの装飾 */
    .stButton > button:contains("◀ TOP") {
        position: fixed !important;
        bottom: 30px !important;
        right: 20px !important;
        background-color: #ff4b4b !important;
        color: white !important;
        border-radius: 50px !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.3) !important;
        padding: 10px 20px !important;
        z-index: 1000 !important;
        border: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

def display_logo(show_line=False):
    try:
        image = Image.open('logo.png')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

# --- 2. 状態管理 ---
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "show_history_list" not in st.session_state: st.session_state["show_history_list"] = False
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 端末チェック & ログイン (省略なし)
# ==========================================
cookie_manager.get_all()
time.sleep(1.2)

device_id = cookie_manager.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id)

res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
if res_block.data:
    st.error("🚫 この端末は管理者によってブロックされています。")
    st.stop()

if not st.session_state.get("is_authenticated"):
    saved_f = cookie_manager.get("saved_f_code")
    saved_n = cookie_manager.get("saved_my_name")
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n})
        st.rerun()
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in); cookie_manager.set("saved_my_name", n_in)
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

# ==========================================
# 🏠 TOP 
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    st.divider()
    if st.button("🛠️ 管理者メニューを開く", use_container_width=True):
        st.session_state["page"] = "admin_menu"; st.session_state["admin_authenticated"] = False; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
        st.session_state.clear(); st.rerun()

# ==========================================
# 🛠️ 管理者メニュー
# ==========================================
elif st.session_state["page"] == "admin_menu":
    # 🚀 固定ボタン仕様
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    
    res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
    current_stored_pw = res_pw.data[0]['value'] if res_pw.data else "8888"

    if not st.session_state["admin_authenticated"]:
        st.markdown("<div class='admin-title'>🛠️ 管理者認証</div>", unsafe_allow_html=True)
        admin_pw = st.text_input("管理者パスワード", type="password")
        if st.button("認証"):
            if admin_pw == current_stored_pw:
                st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("パスワードが違います")
        st.stop()

    st.markdown("<div class='admin-title'>🛠️ 管理者設定メニュー</div>", unsafe_allow_html=True)
    tab1, tab2, tab3, tab4 = st.tabs(["👥 利用者登録", "🚫 端末ブロック", "🔄 復活・解除", "🔑 パスワード変更"])

    with tab1:
        with st.form("reg_master_v10"):
            c_no = st.text_input("カルテ番号"); u_na = st.text_input("氏名 (漢字)"); u_ka = st.text_input("ふりがな (ひらがな)")
            if st.form_submit_button("マスターに登録"):
                if c_no and u_na and u_ka:
                    supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute()
                    st.success("登録完了"); time.sleep(1); st.rerun()
    # (中略: tab2, tab3, tab4 のブロック・復活・パスワード変更ロジックは前回同様)
    with tab2:
        res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        staff_names = list(set([r['staff_name'] for r in res_staff.data])) if res_staff.data else []
        target_staff = st.selectbox("ブロック対象の職員名", ["(選択してください)"] + staff_names)
        if st.button("🚨 この端末を永久ブロック", type="primary", use_container_width=True):
            if target_staff != "(選択してください)":
                supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target_staff, "facility_code": f_code, "is_active": True}).execute()
                cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
                st.session_state.clear(); time.sleep(2); st.rerun()
    with tab3:
        res_list = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        if res_list.data:
            for b in res_list.data:
                col_b1, col_b2 = st.columns([3, 1])
                with col_b1: st.write(f"🚫 {b['staff_name']} (ID: {b['device_id'][:8]})")
                with col_b2:
                    if st.button("復活", key=b['device_id']):
                        supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute()
                        st.success("解除完了"); time.sleep(1); st.rerun()
    with tab4:
        new_pw = st.text_input("新しいパスワード", type="password")
        confirm_pw = st.text_input("確認用", type="password")
        if st.button("パスワードを更新"):
            if new_pw and new_pw == confirm_pw:
                if res_pw.data: supabase.table("admin_settings").update({"value": new_pw}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": new_pw}).execute()
                st.success("更新完了！"); time.sleep(1); st.rerun()

# ==========================================
# ✍️ 記録入力
# ==========================================
elif st.session_state["page"] == "input":
    # 🚀 固定ボタン仕様
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    
    display_logo(); st.subheader("✍️ ケース記録入力")
    st.info(f"✍️ 記入者: {my_name}")
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    patient_options = ["(未選択)"] + [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("👤 利用者を選択", patient_options)
    aud = st.audio_input("🎙️ 声で入力")
    if aud and st.button("✨ AIで文章にする"):
        with st.spinner("整理中..."):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(aud.getvalue()); tmp_path = tmp.name
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                f_up = genai.upload_file(path=tmp_path)
                for _ in range(10):
                    f_up = genai.get_file(f_up.name); 
                    if f_up.state.name == "ACTIVE": break
                    time.sleep(1.5)
                prompt = ("不要な言葉を削除し、介護職員が仲間に送る自然な口調で、話した内容のみを正確に記録として整えてください。")
                response = model.generate_content([f_up, prompt])
                st.session_state["edit_content"] = response.text
                os.remove(tmp_path); st.rerun()
            except Exception as e: st.error(f"解析エラー: {e}")
    content = st.text_area("内容", value=st.session_state["edit_content"], height=250)
    if st.button("💾 保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no = match.group(1); u_name = match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.success("保存完了！"); st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

# ==========================================
# 📊 履歴・モニタリング
# ==========================================
elif st.session_state["page"] == "history":
    # 🚀 固定ボタン仕様
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    
    display_logo(); st.subheader("📊 履歴・モニタリング")
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    sel = st.selectbox("利用者を選択", ["---"] + [f"(No.{r['chart_number']}) {r['user_name']}" for _, r in p_df.iterrows()])
    if sel != "---":
        u_name = re.search(r'\) (.*)', sel).group(1)
        col_date, col_btn = st.columns([2, 2])
        with col_date: target_date = st.date_input("集計日", value=date.today())
        with col_btn:
            if st.button("✨ 指定日まとめ", use_container_width=True):
                date_str = target_date.strftime('%Y-%m-%d')
                next_day = (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", next_day).execute()
                if res.data:
                    with st.spinner("AIで統合中..."):
                        all_txt = "\n".join([r['content'] for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        prompt = f"以下の介護記録を200字程度で要約。支援内容は全て含めること。"
                        resp = model.generate_content(prompt + "\n\n" + all_txt)
                        st.info(f"📅 要約:\n\n{resp.text}")
        if st.button("📈 1ヶ月モニタリング作成", use_container_width=True):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(40).execute()
            if res.data:
                all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                prompt = "ケアマネ向けの200字モニタリング。支援内容重視。"
                resp = model.generate_content(prompt + "\n\n" + all_txt)
                st.session_state["monitoring_result"] = resp.text
        if st.session_state["monitoring_result"]:
            with st.container(border=True):
                st.write(st.session_state["monitoring_result"])
                st.code(st.session_state["monitoring_result"], language=None)