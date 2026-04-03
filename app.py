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
import streamlit.components.v1 as components

# --- 1. 基本設定 ---
tokyo_tz = pytz.timezone('Asia/Tokyo')
now_tokyo = datetime.now(tokyo_tz)
st.set_page_config(page_title="TASUKARU", page_icon="logo.png", layout="wide")

# Cookieマネージャーの初期化（重複エラー回避のため一箇所で定義）
if "cookie_manager" not in st.session_state:
    st.session_state["cookie_manager"] = stx.CookieManager()
cookie_manager = st.session_state["cookie_manager"]

# --- 🎨 カスタムCSS ---
st.markdown("""
    <style>
    .main-title {
        font-size: clamp(18px, 5vw, 24px);
        font-weight: bold; color: #ff4b4b;
        border-bottom: 2px solid #ff4b4b; padding-bottom: 5px;
        margin-bottom: 20px; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis; display: block;
    }
    div.stButton > button { border-radius: 10px !important; }
    .top-back-btn button {
        background-color: #ff4b4b !important; color: white !important;
        width: 100% !important; height: 60px !important;
        font-weight: bold !important; font-size: 18px !important;
        margin-top: 20px !important; border: none !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
    }
    section[data-testid="stAudioInput"] {
        border: 2px solid #ff4b4b !important; border-radius: 20px !important;
        padding: 10px !important; background-color: #fff5f5 !important;
    }
    code { white-space: pre-wrap !important; word-break: break-all !important; }
    .stTextArea textarea { border: 2px solid #ff4b4b !important; border-radius: 10px !important; }
    </style>
    """, unsafe_allow_html=True)

# 💡 スリープ防止
components.html("""
<script>
(function() {
    let wakeLock = null;
    async function requestWakeLock() {
        try {
            if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); }
        } catch (err) { console.log(err); }
    }
    function createNoSleepVideo() {
        const video = document.createElement('video');
        video.setAttribute('loop', ''); video.setAttribute('playsinline', '');
        video.style.display = 'none';
        video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
        return video;
    }
    const videoElement = createNoSleepVideo();
    document.addEventListener('touchstart', function() { videoElement.play(); requestWakeLock(); }, { once: false });
    requestWakeLock();
})();
</script>
""", height=0)

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

# 状態管理
if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "monitoring_month" not in st.session_state: st.session_state["monitoring_month"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 ログイン・端末認証
# ==========================================
cookie_manager.get_all()
time.sleep(0.5)

# 端末ID取得
device_id = cookie_manager.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="init_device_id")

res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
if res_block.data: st.error("🚫 アクセス制限中。"); st.stop()

if not st.session_state.get("is_authenticated"):
    saved_f = cookie_manager.get("saved_f_code")
    saved_n = cookie_manager.get("saved_my_name")
    if saved_f and saved_n:
        st.session_state.update({"is_authenticated": True, "facility_code": saved_f, "my_name": saved_n}); st.rerun()
    
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="login_f_code")
        n_in = st.text_input("👤 あなたのお名前", key="login_my_name")
        if st.button("利用を開始する", use_container_width=True, key="login_submit"):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="save_f")
                cookie_manager.set("saved_my_name", n_in, key="save_n")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in}); st.rerun()
    st.stop()

f_code = st.session_state["facility_code"]; my_name = st.session_state["my_name"]

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"btn_back_{key_suffix}", use_container_width=True):
        st.session_state["page"] = "top"; st.session_state["edit_content"] = ""; st.session_state["monitoring_result"] = ""; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

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
    if st.button("🛠️ 管理者メニュー", use_container_width=True):
        st.session_state["page"] = "admin_menu"; st.session_state["admin_authenticated"] = False; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

# ==========================================
# ✍️ 記録入力
# ==========================================
elif st.session_state["page"] == "input":
    back_to_top_button("inp_up")
    st.markdown("<div class='main-title'>✍️ ケース記録入力</div>", unsafe_allow_html=True)
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    p_opts = ["(未選択)"] + [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("👤 利用者を選択", p_opts)
    st.markdown("---")
    target_img = st.file_uploader("📷 写真（背面カメラ）/ 画像", type=["jpg", "png", "jpeg"])
    st.write("🎙️ **指でボタンを押して録音を開始してください**")
    st.caption("※画面のスリープ機能がある場合には画面に触れながら話してください")
    aud_file = st.audio_input("録音ボタン")
    if (target_img or aud_file) and st.button("✨ AIで文章にする", type="primary"):
        with st.spinner("整理中..."):
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                inputs = ["解説なし、ナレーションなし。内容のみを介護記録の口調で出力してください。"]
                if target_img: inputs.append(Image.open(target_img))
                if aud_file:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(aud_file.getvalue()); tmp_path = tmp.name
                    f_up = genai.upload_file(path=tmp_path)
                    while f_up.state.name != "ACTIVE": time.sleep(1); f_up = genai.get_file(f_up.name)
                    inputs.append(f_up)
                resp = model.generate_content(inputs)
                st.session_state["edit_content"] = resp.text
                if aud_file: os.remove(tmp_path)
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    content = st.text_area("内容", value=st.session_state["edit_content"], height=200)
    if st.button("💾 クラウドに保存", use_container_width=True):
        if sel != "(未選択)" and content:
            match = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
            c_no, u_name = match.group(1), match.group(2)
            supabase.table("records").insert({"facility_code": f_code, "chart_number": str(c_no), "user_name": u_name, "staff_name": my_name, "content": content, "created_at": now_tokyo.isoformat()}).execute()
            st.success(f"✅ {u_name}さんの記録を保存。"); st.session_state["edit_content"] = ""; time.sleep(1.2); st.rerun()
    back_to_top_button("inp_down")

# ==========================================
# 📊 履歴・モニタリング 
# ==========================================
elif st.session_state["page"] == "history":
    back_to_top_button("his_up")
    st.markdown("<div class='main-title'>📊 履歴・モニタリング</div>", unsafe_allow_html=True)
    res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
    p_df = pd.DataFrame(res_p.data) if res_p.data else pd.DataFrame()
    p_opts = ["---"] + [f"(No.{r['chart_number']}) {r['user_name']} [{r['user_kana']}]" for _, r in p_df.iterrows()]
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = re.search(r'\) (.*?) \[', sel).group(1) if '[' in sel else re.search(r'\) (.*)', sel).group(1)
        st.markdown("---")
        st.write("▼ 指定日のまとめ作成")
        col_d, col_b = st.columns([2, 2])
        with col_d: target_date = st.date_input("日付", value=date.today())
        with col_b:
            if st.button("✨ 作成", use_container_width=True):
                date_str = target_date.strftime('%Y-%m-%d')
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", date_str).lt("created_at", (target_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')).execute()
                if res.data:
                    all_txt = "\n".join([r['content'] for r in res.data])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    resp = model.generate_content(f"介護職の口調で200字要約。\n\n{all_txt}")
                    st.session_state["monitoring_result"] = resp.text; st.session_state["monitoring_month"] = "指定日"
        st.write("▼ モニタリング作成")
        col_m, col_btn = st.columns([2, 2])
        with col_m: selected_m = st.selectbox("月を選択", [f"{i}月" for i in range(1, 13)], index=now_tokyo.month-1)
        with col_btn:
            if st.button("📈 生成", use_container_width=True):
                month_num = int(selected_m.replace("月", ""))
                res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).execute()
                m_recs = [r for r in res.data if datetime.fromisoformat(r['created_at']).month == month_num]
                if m_recs:
                    all_txt = "\n".join([r['content'] for r in m_recs])
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    resp = model.generate_content(f"200字以内の一続きの文章で介護報告。内容のみ出力。\n記録:\n{all_txt}")
                    st.session_state["monitoring_result"] = resp.text; st.session_state["monitoring_month"] = selected_m
        if st.session_state["monitoring_result"]:
            st.markdown(f"### ✨ {st.session_state['monitoring_month']}のモニタリング")
            st.session_state["monitoring_result"] = st.text_area("修正", value=st.session_state["monitoring_result"], height=200)
            st.code(st.session_state["monitoring_result"], language=None)
            if st.button("🗑️ クリア"): st.session_state["monitoring_result"] = ""; st.rerun()
        st.divider()
        if st.button("📜 過去の履歴を表示" if not st.session_state.get("show_history_list") else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state.get("show_history_list", False); st.rerun()
        if st.session_state.get("show_history_list"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16].replace('T',' ')}"): st.write(r['content'])
    back_to_top_button("his_down")

# ==========================================
# 🛠️ 管理者メニュー 
# ==========================================
elif st.session_state["page"] == "admin_menu":
    back_to_top_button("adm_up")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
    cur_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
    if not st.session_state["admin_authenticated"]:
        admin_pw = st.text_input("パスワード", type="password", key="admin_pw_in")
        if st.button("認証"):
            if admin_pw == cur_pw: st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("違います")
        st.stop()
    t1, t2, t3, t4 = st.tabs(["👥 登録", "🚫 ブロック", "🔄 解除", "🔑 パス変更"])
    with t1:
        with st.form("reg"):
            c_no = st.text_input("カルテNo"); u_na = st.text_input("氏名"); u_ka = st.text_input("ふりがな")
            if st.form_submit_button("登録"):
                supabase.table("patients").insert({"facility_code": f_code, "chart_number": c_no, "user_name": u_na, "user_kana": u_ka}).execute(); st.rerun()
    with t2:
        res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        s_names = list(set([r['staff_name'] for r in res_s.data])) if res_s.data else []
        target = st.selectbox("ブロック対象", ["(選択)"] + s_names, key="block_target")
        # 🛡️ 安全ガード：自分の名前や今の端末をブロックしないための警告
        st.warning("※実行すると「今操作しているこの端末」がアクセス禁止になります。自分自身の端末で行わないようご注意ください。")
        if st.button("🚨 ブロック実行", key="block_submit"):
            if target != "(選択)":
                supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target, "facility_code": f_code, "is_active": True}).execute()
                st.session_state.clear(); st.rerun()
    with t3:
        res_l = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        for b in res_l.data:
            if st.button(f"復活: {b['staff_name']} (ID:{b['device_id'][:5]})", key=f"revive_{b['device_id'][:5]}"):
                supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute(); st.rerun()
    with t4:
        new_p = st.text_input("新パスワード", type="password"); con_p = st.text_input("確認用", type="password")
        if st.button("更新"):
            if new_p == con_p:
                if res_pw.data: supabase.table("admin_settings").update({"value": new_p}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": new_p}).execute()
                st.success("完了"); st.rerun()
    back_to_top_button("adm_down")