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

# --- 🎨 カスタムCSS ---
st.markdown("""
    <style>
    .admin-title { font-size: 22px; font-weight: bold; color: #ff4b4b !important; padding-bottom: 10px; border-bottom: 2px solid #ff4b4b; margin-bottom: 20px; display: block; }
    .stTabs [data-baseweb="tab-list"] button { color: #31333F !important; font-size: 16px !important; font-weight: 600 !important; }
    .stTabs [aria-selected="true"] { color: #ff4b4b !important; }
    .stMarkdown p, .stText, label { color: #31333F !important; }
    div.stButton > button:first-child:contains("TOP") {
        background-color: #ff4b4b !important; color: white !important; border-radius: 10px !important;
        width: 100% !important; height: 50px !important; font-weight: bold !important;
        margin-top: 10px !important; margin-bottom: 10px !important; border: none !important;
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
# 🔐 端末ブロック & 認証
# ==========================================
cookie_manager.get_all()
time.sleep(1.2)
device_id = cookie_manager.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id)

res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
if res_block.data:
    st.error("🚫 この端末は管理者によってブロックされています。"); st.stop()

if not st.session_state.get("is_authenticated"):
    saved_f = cookie_manager.get("saved_f_code"); saved_n = cookie_manager.get("saved_my_name")
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n}); st.rerun()
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.text_input("👤 あなたのお名前")
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in); cookie_manager.set("saved_my_name", n_in)
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in}); st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]; my_name = st.session_state["my_name"]

# ==========================================
# 🏠 TOP / 🛠️ 管理者メニュー
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

elif st.session_state["page"] == "admin_menu":
    if st.button("◀ TOPに戻る", key="adm_up"): st.session_state["page"] = "top"; st.rerun()
    res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
    current_stored_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
    if not st.session_state["admin_authenticated"]:
        st.markdown("<div class='admin-title'>🛠️ 管理者認証</div>", unsafe_allow_html=True)
        admin_pw = st.text_input("管理者パスワード", type="password")
        if st.button("認証"):
            if admin_pw == current_stored_pw: st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("パスワードが違います")
        st.stop()
    st.markdown("<div class='admin-title'>🛠️ 管理者設定メニュー</div>", unsafe_allow_html=True)
    tab1, tab2, tab3, tab4 = st.tabs(["👥 利用者登録", "🚫 端末ブロック", "🔄 復活・解除", "🔑 パスワード変更"])
    with tab1:
        with st.form("reg_v14"):
            c_no = st.text_input("カルテ番号"); u_na = st.text_input("氏名"); u_ka = st.text_input("ふりがな(ひらがな)")
            if st.form_submit_button("登録"):
                if c_no and u_na and u_ka:
                    supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute(); st.rerun()
    # (中略: tab2, 3, 4)
    with tab2:
        res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        staff_names = list(set([r['staff_name'] for r in res_staff.data])) if res_staff.data else []
        target_staff = st.selectbox("ブロック対象", ["(未選択)"] + staff_names)
        if st.button("🚨 この端末をブロック", type="primary", use_container_width=True):
            if target_staff != "(未選択)":
                supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target_staff, "facility_code": f_code, "is_active": True}).execute()
                st.session_state.clear(); st.rerun()
    with tab3:
        res_list = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        for b in res_list.data:
            col_b1, col_b2 = st.columns([3, 1])
            with col_b1: st.write(f"🚫 {b['staff_name']} (ID: {b['device_id'][:8]})")
            with col_b2:
                if st.button("復活", key=b['device_id']):
                    supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute(); st.rerun()
    with tab4:
        new_pw = st.text_input("新パスワード", type="password"); confirm_pw = st.text_input("確認用", type="password")
        if st.button("更新"):
            if new_pw and new_pw == confirm_pw:
                if res_pw.data: supabase.table("admin_settings").update({"value": new_pw}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": new_pw}).execute()
                st.success("完了"); st.rerun()
    st.divider(); st.button("◀ TOPに戻る", key="adm_down")

# ==========================================
# ✍️ 記録入力（カメラ機能搭載）
# ==========================================
elif st.session_state["page"] == "input":
    if st.button("◀ TOPに戻る", key="inp_up"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    st.info(f"✍️ 記入者: {my_name}")
    
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    patient_options = ["(未選択)"] + [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("👤 利用者を選択", patient_options)

    # --- 📸 カメラ & 画像アップロード ---
    st.markdown("---")
    img_file = st.camera_input("📷 写真を撮る (背面カメラ推奨)")
    up_file = st.file_uploader("📁 または画像を選択", type=["jpg", "png", "jpeg"])
    aud_file = st.audio_input("🎙️ 声で入力")
    
    target_img = img_file if img_file else up_file

    if (target_img or aud_file) and st.button("✨ AIで文章を整理する"):
        with st.spinner("AIが内容を確認中..."):
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                inputs = []
                
                # 画像があれば追加
                if target_img:
                    img = Image.open(target_img)
                    inputs.append(img)
                    inputs.append("画像に写っている状況（食事の量、皮膚の状態、書類の内容など）を介護記録として客観的に説明してください。")

                # 音声があれば追加
                if aud_file:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(aud_file.getvalue()); tmp_path = tmp.name
                    f_up = genai.upload_file(path=tmp_path)
                    while f_up.state.name != "ACTIVE":
                        time.sleep(1); f_up = genai.get_file(f_up.name)
                    inputs.append(f_up)
                    inputs.append("音声の内容を、介護職員が仲間に送る自然な口調で整理してください。")

                response = model.generate_content(inputs)
                st.session_state["edit_content"] = response.text
                if aud_file: os.remove(tmp_path)
                st.rerun()
            except Exception as e: st.error(f"解析エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=250)
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no = match.group(1); u_name = match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.session_state["edit_content"] = ""; st.session_state["page"] = "top"; st.rerun()
    st.divider(); st.button("◀ TOPに戻る", key="inp_down")

# ==========================================
# 📊 履歴・モニタリング
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOPに戻る", key="his_up"): st.session_state["page"] = "top"; st.rerun()
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
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')).execute()
                if res.data:
                    all_txt = "\n".join([r['content'] for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    resp = model.generate_content(f"以下の介護記録を200字程度で要約。支援内容は漏らさず記載せよ。\n\n{all_txt}")
                    st.info(f"📅 要約:\n\n{resp.text}")
        if st.button("📈 1ヶ月モニタリング作成", use_container_width=True):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(40).execute()
            if res.data:
                all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                resp = model.generate_content(f"ケアマネ向けモニタリング。支援内容重視。\n\n{all_txt}")
                st.session_state["monitoring_result"] = resp.text
        if st.session_state["monitoring_result"]:
            with st.container(border=True):
                st.write(st.session_state["monitoring_result"])
                st.code(st.session_state["monitoring_result"], language=None)
        if st.button("📜 過去の履歴を表示" if not st.session_state["show_history_list"] else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state["show_history_list"]; st.rerun()
        if st.session_state["show_history_list"]:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')} - 記: {r.get('staff_name','--')}"):
                    st.write(r['content'])
    st.divider(); st.button("◀ TOPに戻る", key="his_down")