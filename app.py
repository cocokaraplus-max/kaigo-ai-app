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

def load_css(file_name):
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception: pass

load_css("style.css")

try:
    s_url = st.secrets["SUPABASE_URL"]
    s_key = st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e:
    st.error(f"⚠️ 接続設定エラー: {e}"); st.stop()

def normalize_text(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ""
    return unicodedata.normalize('NFKC', str(s).strip())

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

STAFF_LIST = ["管理者", "サービス提供責任者", "介護職員A", "介護職員B", "看護師"]

# ==========================================
# 🔐 ログイン & Cookie同期
# ==========================================
cookie_manager.get_all()
time.sleep(0.5)
saved_f = cookie_manager.get("saved_f_code")
saved_n = cookie_manager.get("saved_my_name")

if not st.session_state.get("is_authenticated"):
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n})
        st.rerun()
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526")
        n_in = st.selectbox("👤 あなたのお名前 (職員)", STAFF_LIST)
        if st.button("利用を開始する", use_container_width=True):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in); cookie_manager.set("saved_my_name", n_in)
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]
my_name = st.session_state["my_name"]

# ==========================================
# 🏠 TOP / ✍️ 入力（前回同様）
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): 
            st.session_state["page"] = "history"; st.session_state["show_history_list"] = False; st.rerun()
    if st.button("⚙️ マスター登録", use_container_width=True): st.session_state["page"] = "settings"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name")
        st.session_state.clear(); st.rerun()

elif st.session_state["page"] == "input":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("✍️ ケース記録入力")
    current_staff = st.selectbox("記入者", STAFF_LIST, index=STAFF_LIST.index(my_name) if my_name in STAFF_LIST else 0)
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
                    time.sleep(1)
                prompt = ("不要な言葉を削除し、介護職員が仲間に送る自然な口調で、話した内容のみを正確に記録として整えてください。")
                response = model.generate_content([f_up, prompt])
                st.session_state["edit_content"] = response.text
                os.remove(tmp_path); st.rerun()
            except Exception as e: st.error(f"解析エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=250)
    if st.button("💾 クラウド保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no = match.group(1); u_name = match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": current_staff, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.success("保存完了！"); st.session_state["edit_content"] = ""; time.sleep(1); st.session_state["page"] = "top"; st.rerun()

# ==========================================
# 📊 履歴・モニタリング（改修版）
# ==========================================
elif st.session_state["page"] == "history":
    if st.button("◀ TOP"): st.session_state["page"] = "top"; st.rerun()
    display_logo(); st.subheader("📊 履歴・モニタリング")

    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    sel = st.selectbox("利用者を選択", ["---"] + [f"(No.{r['chart_number']}) {r['user_name']}" for _, r in p_df.iterrows()])
    
    if sel != "---":
        u_name = re.search(r'\) (.*)', sel).group(1)
        
        st.markdown("#### 📅 記録の集計・モニタリング生成")
        col_date, col_btn = st.columns([2, 2])
        with col_date:
            target_date = st.date_input("集計する日を選択", value=date.today())
        with col_btn:
            if st.button("✨ 指定日の記録をまとめる", use_container_width=True):
                date_str = target_date.strftime('%Y-%m-%d')
                # 指定日の全記録を取得 (gteはその日の0時, ltは翌日の0時)
                next_day = (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", next_day).execute()
                if res.data:
                    with st.spinner("AIで指定日の記録を統合中..."):
                        all_txt = "\n".join([r['content'] for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        prompt = f"以下の{target_date}の介護記録を、1日のまとめとして200字程度で要約してください。口調は介護職員が報告書で使う丁寧な口調（〜です、〜でした）とし、推測や飛躍した内容は一切含めず、記載されている事実のみを整理してください。"
                        resp = model.generate_content(prompt + "\n\n" + all_txt)
                        st.info(f"📅 {target_date} の要約:\n\n{resp.text}")
                else: st.warning(f"{target_date} の記録は見つかりませんでした。")

        if st.button("📈 ケアマネ向け1ヶ月モニタリング作成", use_container_width=True):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(40).execute()
            if res.data:
                with st.spinner("モニタリング文を作成中..."):
                    all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    prompt = f"あなたは介護職員です。ケアマネジャーに報告するための月間モニタリング文を作成してください。ルール：1.提供された事実のみを扱うこと 2.200字程度の簡潔な文章にすること 3.専門的な報告書口調であること 4.別の用紙にコピペして使うための純粋な本文のみを出力すること。"
                    resp = model.generate_content(prompt + "\n\n" + all_txt)
                    st.success("📈 生成完了 (コピーして利用してください)"); st.code(resp.text, language=None)
            else: st.warning("集計に必要なデータが足りません。")

        st.divider()
        if st.button("📜 過去の履歴を表示する" if not st.session_state["show_history_list"] else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state["show_history_list"]

        if st.session_state["show_history_list"]:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            if res.data:
                for r in res.data:
                    with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')} - 記: {r.get('staff_name','--')}"):
                        st.write(r['content'])