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
    div.stButton > button { border-radius: 10px !important; }
    .top-back-btn button {
        background-color: #ff4b4b !important; color: white !important;
        width: 100% !important; height: 60px !important;
        font-weight: bold !important; font-size: 18px !important;
        margin-top: 30px !important; border: none !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
    }
    /* モニタリング結果の強調表示 */
    .monitoring-box {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        margin-bottom: 10px;
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
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 セキュリティ
# ==========================================
cookie_manager.get_all()
time.sleep(1.0)
device_id = cookie_manager.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4()); cookie_manager.set("device_id", device_id)

res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
if res_block.data: st.error("🚫 ブロックされています。"); st.stop()

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

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"btn_back_{key_suffix}", use_container_width=True):
        st.session_state["page"] = "top"; st.session_state["edit_content"] = ""; st.session_state["monitoring_result"] = ""; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 🏠 TOP 画面
# ==========================================
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    st.divider()
    if st.button("🛠️ 管理者メニュー", use_container_width=True):
        st.session_state["page"] = "admin_menu"; st.session_state["admin_authenticated"] = False; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

# ==========================================
# ✍️ 記録入力（背面カメラ・連続入力対応）
# ==========================================
elif st.session_state["page"] == "input":
    back_to_top_button("inp_up")
    display_logo(); st.subheader("✍️ ケース記録入力")
    
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    patient_options = ["(未選択)"] + [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("👤 利用者を選択", patient_options)

    st.markdown("---")
    target_img = st.file_uploader("📷 写真を撮る / 画像を選択", type=["jpg", "png", "jpeg"])
    aud_file = st.audio_input("🎙️ 声で入力")
    
    if (target_img or aud_file) and st.button("✨ AIで文章にする", type="primary"):
        with st.spinner("AIが内容のみを抽出中..."):
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                inputs = ["あなたは介護記録の作成補助者です。解説やナレーション（〜と言っています、等）は一切書かず、事実と発言内容のみを介護記録として自然な口調で書き出してください。"]
                if target_img: inputs.append(Image.open(target_img))
                if aud_file:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(aud_file.getvalue()); tmp_path = tmp.name
                    f_up = genai.upload_file(path=tmp_path)
                    while f_up.state.name != "ACTIVE": time.sleep(1); f_up = genai.get_file(f_up.name)
                    inputs.append(f_up)
                
                response = model.generate_content(inputs)
                st.session_state["edit_content"] = response.text
                if aud_file: os.remove(tmp_path)
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")

    content = st.text_area("内容", value=st.session_state["edit_content"], height=200)
    
    if st.button("💾 クラウドに保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no, u_name = match.group(1), match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.success(f"✅ {u_name}さんの記録を保存しました。")
            st.session_state["edit_content"] = ""; time.sleep(1.5); st.rerun()
    
    st.divider(); back_to_top_button("inp_down")

# ==========================================
# 📊 履歴・モニタリング（コピー機能 & 専門職口調 復元）
# ==========================================
elif st.session_state["page"] == "history":
    back_to_top_button("his_up")
    display_logo(); st.subheader("📊 履歴・モニタリング")
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    patient_options = ["---"] + [f"(No.{r['chart_number']}) {r['user_name']} [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("利用者を選択", patient_options)
    
    if sel != "---":
        u_name = re.search(r'\) (.*?) \[', sel).group(1) if '[' in sel else re.search(r'\) (.*)', sel).group(1)
        
        col_sum, col_mon = st.columns(2)
        with col_sum:
            target_date = st.date_input("集計日", value=date.today())
            if st.button("✨ 指定日まとめ", use_container_width=True):
                date_str = target_date.strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')).execute()
                if res.data:
                    all_txt = "\n".join([r['content'] for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    resp = model.generate_content(f"以下の介護記録を、申し送り用に簡潔に200字程度で要約してください。\n\n{all_txt}")
                    st.session_state["monitoring_result"] = resp.text
                else: st.warning("該当日時の記録がありません。")
        
        with col_mon:
            st.write("ヶ月単位の推移")
            if st.button("📈 モニタリング生成", use_container_width=True):
                # 直近1ヶ月（最大40件）のデータを取得
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).limit(40).execute()
                if res.data:
                    all_txt = "\n".join([f"{r['created_at'][:10]}: {r['content']}" for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    # 🚀 ケアマネ向け専門口調プロンプト
                    prompt = f"""
                    あなたは熟練の介護福祉士です。以下の日々のケース記録に基づき、ケアマネジャーに提出する「月間モニタリング（経過報告）」を生成してください。
                    
                    【ルール】
                    1. 口調は「〜です」「〜ます」の丁寧な敬体を用いる。
                    2. 介護専門職としての視点（ADLの変化、意欲、健康状態）を含める。
                    3. そのまま資料にコピー＆ペーストできる形式で出力する。
                    4. ナレーションや「はい、作成しました」等の挨拶は一切不要。内容のみを出力。
                    
                    対象利用者: {u_name}
                    記録データ:
                    {all_txt}
                    """
                    resp = model.generate_content(prompt)
                    st.session_state["monitoring_result"] = resp.text
                else: st.warning("記録データが足りません。")

        # 📋 結果表示 & コピー機能
        if st.session_state["monitoring_result"]:
            st.markdown("### ✨ 生成結果 (そのままコピーして使用できます)")
            st.info("💡 下の枠内の文字を長押し、または右上のアイコンで一括コピーできます。")
            # st.code を使うことで、クリック一つでコピー可能なUIを提供
            st.code(st.session_state["monitoring_result"], language=None)
            
            if st.button("🗑️ 結果をクリア"):
                st.session_state["monitoring_result"] = ""; st.rerun()

        st.divider()
        if st.button("📜 過去の全履歴を表示" if not st.session_state.get("show_history_list") else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state.get("show_history_list", False); st.rerun()
        if st.session_state.get("show_history_list"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')}"): st.write(r['content'])
    
    st.divider(); back_to_top_button("his_down")

# ==========================================
# 🛠️ 管理者メニュー（省略なし）
# ==========================================
elif st.session_state["page"] == "admin_menu":
    back_to_top_button("adm_up")
    res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
    current_stored_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
    if not st.session_state["admin_authenticated"]:
        admin_pw = st.text_input("管理者パスワード", type="password")
        if st.button("認証"):
            if admin_pw == current_stored_pw: st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("パスワードが違います")
        st.stop()
    st.markdown("<div class='admin-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    t1, t2, t3, t4 = st.tabs(["👥 利用者登録", "🚫 端末ブロック", "🔄 復活・解除", "🔑 パス変更"])
    with t1:
        with st.form("reg"):
            c_no = st.text_input("カルテNo"); u_na = st.text_input("氏名"); u_ka = st.text_input("ふりがな(ひらがな)")
            if st.form_submit_button("登録"):
                supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute(); st.rerun()
    with t2:
        res_staff = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        staff_names = list(set([r['staff_name'] for r in res_staff.data])) if res_staff.data else []
        target = st.selectbox("ブロック対象", ["(選択)"] + staff_names)
        if st.button("🚨 ブロック実行"):
            supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target, "facility_code": f_code, "is_active": True}).execute(); st.session_state.clear(); st.rerun()
    with t3:
        res_list = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        for b in res_list.data:
            if st.button(f"復活: {b['staff_name']} (ID:{b['device_id'][:5]})"):
                supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute(); st.rerun()
    with t4:
        new_pw = st.text_input("新パスワード", type="password"); confirm_pw = st.text_input("確認用", type="password")
        if st.button("更新"):
            if new_pw == confirm_pw:
                if res_pw.data: supabase.table("admin_settings").update({"value": new_pw}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": new_pw}).execute()
                st.success("完了"); st.rerun()
    st.divider(); back_to_top_button("adm_down")