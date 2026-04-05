import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, date, timedelta
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

if "cookie_manager" not in st.session_state:
    st.session_state["cookie_manager"] = stx.CookieManager(key="tasukaru_stable_v34")
cookie_manager = st.session_state["cookie_manager"]

# 🚀 保存後にウィジェットを強制リセットするための識別子
if "input_key_id" not in st.session_state:
    st.session_state["input_key_id"] = str(uuid.uuid4())

# --- 🎨 カスタムCSS ---
st.markdown("""
    <style>
    .main-title { font-size: clamp(18px, 5vw, 24px); font-weight: bold; color: #ff4b4b; border-bottom: 2px solid #ff4b4b; padding-bottom: 5px; margin-bottom: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
    div.stButton > button { border-radius: 10px !important; }
    .top-back-btn button { background-color: #ff4b4b !important; color: white !important; width: 100% !important; height: 60px !important; font-weight: bold !important; font-size: 18px !important; margin-top: 20px !important; border: none !important; box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; }
    section[data-testid="stAudioInput"] { border: 2px solid #ff4b4b !important; border-radius: 20px !important; padding: 10px !important; background-color: #fff5f5 !important; }
    code { white-space: pre-wrap !important; word-break: break-all !important; }
    .stTextArea textarea { border: 2px solid #ff4b4b !important; border-radius: 10px !important; }
    
    .scrollable-history {
        max-height: 250px;
        overflow-y: auto;
        border: 2px solid #ff4b4b;
        border-radius: 10px;
        padding: 15px;
        background-color: #fffaf0;
    }
    .history-item {
        font-size: 16px;
        margin-bottom: 10px;
        border-bottom: 1px dashed #ccc;
        padding-bottom: 5px;
    }
    .history-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    
    div.stButton > button p, div.stButton > button div, div.stButton > button span {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        font-size: clamp(10px, 3vw, 14px) !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 💡 スリープ防止
components.html("""
<script>
(function() {
    let wakeLock = null;
    async function requestWakeLock() { try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); } } catch (err) { } }
    function createNoSleepVideo() {
        const video = document.createElement('video'); video.setAttribute('loop', ''); video.setAttribute('playsinline', ''); video.style.display = 'none';
        video.src = "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21hdmMxbXA0MgAAAAhZy1mcmVlAAAALW1kYXQAAAHpYXZjMQEAL0AvYmxhY2stZHVtbXkAAAAIZnJlZQAAABdtb292AAAAbG12aGQAAAAA3pYpId6WKSEAAAPoAAAAKAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAGWlvZHMAAAAAEAAf/yADAAACAAABAAAAAA== ";
        return video;
    }
    const v = createNoSleepVideo();
    document.addEventListener('touchstart', function() { v.play(); requestWakeLock(); }, { once: false });
    requestWakeLock();
})();
</script>
""", height=0)

try:
    s_url, s_key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    g_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=g_key)
    supabase: Client = create_client(s_url, s_key)
except Exception as e: st.error(f"⚠️ 接続エラー: {e}"); st.stop()

def display_logo(show_line=False):
    try:
        try: image = Image.open('logo.png')
        except: image = Image.open('logo.jpg')
        col_l, col_m, col_r = st.columns([1, 1, 1])
        with col_m: st.image(image, use_container_width=True)
        if show_line: st.markdown('<div class="has-markdown-stitle"></div>', unsafe_allow_html=True)
    except Exception: st.markdown("<h2 style='text-align: center;'>🦝 TASUKARU</h2>", unsafe_allow_html=True)

if "page" not in st.session_state: st.session_state["page"] = "top"
if "edit_content" not in st.session_state: st.session_state["edit_content"] = ""
if "monitoring_result" not in st.session_state: st.session_state["monitoring_result"] = ""
if "admin_authenticated" not in st.session_state: st.session_state["admin_authenticated"] = False

# ==========================================
# 🔐 ログイン・端末認証
# ==========================================
cookies = cookie_manager.get_all()
if not cookies:
    time.sleep(0.5); st.rerun()

device_id = cookies.get("device_id")
if not device_id:
    device_id = str(uuid.uuid4())
    cookie_manager.set("device_id", device_id, key="save_dev_v34")

if device_id:
    try:
        res_block = supabase.table("blocked_devices").select("*").eq("device_id", device_id).eq("is_active", True).execute()
        if res_block.data: st.error("🚫 アクセス制限中。"); st.stop()
    except: pass

if not st.session_state.get("is_authenticated"):
    sf, sn = cookies.get("saved_f_code"), cookies.get("saved_my_name")
    if sf and sn:
        st.session_state.update({"is_authenticated": True, "facility_code": sf, "my_name": sn}); st.rerun()
    
    display_logo()
    with st.container(border=True):
        f_in = st.text_input("🏢 施設コード", value="cocokaraplus-5526", key="f_login")
        n_in = st.text_input("👤 あなたのお名前", key="n_login")
        if st.button("利用を開始する", use_container_width=True, key="btn_login"):
            if f_in and n_in:
                cookie_manager.set("saved_f_code", f_in, key="f_sv_v34")
                cookie_manager.set("saved_my_name", n_in, key="n_sv_v34")
                st.session_state.update({"is_authenticated": True, "facility_code": f_in, "my_name": n_in})
                time.sleep(0.5); st.rerun()
    st.stop()

f_code, my_name = st.session_state["facility_code"], st.session_state["my_name"]

def back_to_top_button(key_suffix):
    st.markdown('<div class="top-back-btn">', unsafe_allow_html=True)
    if st.button("◀ TOPに戻る", key=f"bk_{key_suffix}", use_container_width=True):
        st.session_state.update({"page": "top", "edit_content": "", "monitoring_result": ""}); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 🏠 画面遷移
# ==========================================

# --- 🏠 TOP画面 ---
if st.session_state["page"] == "top":
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    
    col_main1, col_main2 = st.columns(2)
    with col_main1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col_main2:
        if st.button("📊 履歴・モニタリング", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    
    if st.button("📅 日別記録閲覧", use_container_width=True):
        st.session_state["page"] = "daily_view"; st.rerun()
        
    st.divider()
    
    st.markdown("##### 📝 更新履歴 (最新30名まで)")
    if f_code:
        today_start = tokyo_tz.localize(datetime.combine(now_tokyo.date(), datetime.min.time()))
        today_end = today_start + timedelta(days=1)
        try:
            res_today = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).gte("created_at", today_start.isoformat()).lt("created_at", today_end.isoformat()).execute()
            if res_today.data:
                df = pd.DataFrame(res_today.data)
                grouped = df.groupby("user_name").agg(count=("user_name", "size"), last_time=("created_at", "max")).reset_index()
                grouped = grouped.sort_values("last_time", ascending=False).head(30)
                
                with st.container(height=250):
                    for _, row in grouped.iterrows():
                        try:
                            dt_utc = datetime.fromisoformat(str(row['last_time']).replace('Z', '+00:00'))
                            time_str = dt_utc.astimezone(tokyo_tz).strftime('%m/%d %H:%M')
                        except:
                            time_str = str(row['last_time'])[5:16].replace('-', '/')
                        
                        btn_label = f"👤 {row['user_name']} 様 （{row['count']}件） 最終記録 {time_str}"
                        if st.button(btn_label, key=f"hist_btn_{row['user_name']}", use_container_width=True):
                            st.session_state["page"] = "daily_view"
                            st.session_state["dv_target_user"] = row['user_name']
                            st.session_state["dv_target_date"] = now_tokyo.date()
                            st.rerun()
            else:
                st.info("本日の記録はまだありません。")
        except Exception as e: st.error(f"履歴の取得に失敗しました: {e}")
            
    st.divider()
    if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

# --- ✍️ 記録入力画面 ---
elif st.session_state["page"] == "input":
    back_to_top_button("ip_u")
    st.markdown("<div class='main-title'>✍️ ケース記録入力</div>", unsafe_allow_html=True)
    
    kid = st.session_state["input_key_id"]
    p_opts = ["(未選択)"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for r in res_p.data]
        except: pass
    
    sel = st.selectbox("👤 利用者を選択", p_opts, key=f"sel_{kid}")
    record_date = st.date_input("📅 記録日", value=now_tokyo.date(), key=f"date_{kid}")
        
    st.markdown("---")
    # 📸 【修正】複数枚対応 (最大5枚)
    t_imgs = st.file_uploader("📷 写真（最大5枚）", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key=f"img_{kid}")
    st.write("🎙️ **指でボタンを押して録音を開始してください**")
    st.caption("※画面のスリープ機能がある場合には画面に触れながら話してください")
    aud = st.audio_input("録音ボタン", key=f"aud_{kid}")
    
    if (t_imgs or aud) and st.button("✨ AIで文章にする", type="primary", key="btn_ai"):
        with st.spinner("整理中..."):
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                ins = ["音声や画像にある事実のみを文章化し、推測や事実以外の追加情報は絶対に書かないこと。「え〜」「あ〜」などの無意味な言葉（フィラー）は完全に削除すること。介護職員が職場の仲間に申し送りをするような、簡潔で分かりやすい「です・ます調」で出力すること。解説や挨拶などの余計な文章は一切不要。"]
                if t_imgs:
                    for img in t_imgs: ins.append(Image.open(img))
                if aud:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp.write(aud.getvalue()); tmp_p = tmp.name
                    f = genai.upload_file(path=tmp_p)
                    while f.state.name != "ACTIVE": time.sleep(1); f = genai.get_file(f.name)
                    ins.append(f)
                
                r = model.generate_content(ins)
                st.session_state["edit_content"] = r.text
                st.session_state[f"txt_{kid}"] = r.text
                if aud: os.remove(tmp_p)
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
            
    txt = st.text_area("内容", value=st.session_state["edit_content"], height=200, key=f"txt_{kid}")
    
    if st.button("💾 クラウドに保存", use_container_width=True, key="btn_save"):
        if sel != "(未選択)" and txt and f_code:
            try:
                m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                current_time = datetime.now(tokyo_tz).time()
                target_datetime = tokyo_tz.localize(datetime.combine(record_date, current_time))
                
                # --- 📸 【修正】複数枚保存ロジック (配列形式対応) ---
                urls = []
                if t_imgs:
                    for img in t_imgs[:5]: # 5枚制限
                        f_name = f"{uuid.uuid4()}.{img.name.split('.')[-1]}"
                        supabase.storage.from_("case-photos").upload(f_name, img.getvalue())
                        res_url = supabase.storage.from_("case-photos").get_public_url(f_name)
                        if hasattr(res_url, 'public_url'): urls.append(res_url.public_url)
                        else: urls.append(str(res_url))

                # --- 💾 データベースへ保存 ---
                supabase.table("records").insert({
                    "facility_code": f_code,
                    "chart_number": str(m.group(1)),
                    "user_name": m.group(2),
                    "staff_name": my_name,
                    "content": txt,
                    "image_url": urls if urls else None, # リストとしてそのまま保存
                    "created_at": target_datetime.isoformat()
                }).execute()
                
                st.session_state["edit_content"] = ""
                st.session_state["input_key_id"] = str(uuid.uuid4())
                st.success("✅ 保存完了"); time.sleep(0.5); st.rerun()
            except Exception as e:
                st.error(f"保存エラー: {e}")
            
    back_to_top_button("ip_d")

# --- 📊 履歴・モニタリング画面 ---
elif st.session_state["page"] == "history":
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 履歴・モニタリング</div>", unsafe_allow_html=True)
    p_opts = ["---"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) {r['user_name']} [{r['user_kana']}]" for r in res_p.data]
        except: pass
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = re.search(r'\) (.*?) \[', sel).group(1) if '[' in sel else re.search(r'\) (.*)', sel).group(1)
        st.markdown("---")
        st.write("▼ 指定日のまとめ作成")
        col_d, col_b = st.columns([2, 2])
        with col_d: t_date = st.date_input("日付", value=now_tokyo.date())
        with col_b:
            if st.button("✨ 作成", use_container_width=True):
                if f_code:
                    target_start = tokyo_tz.localize(datetime.combine(t_date, datetime.min.time()))
                    res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", target_start.isoformat()).lt("created_at", (target_start + timedelta(days=1)).isoformat()).execute()
                    if res.data:
                        all_t = "\n".join([r['content'] for r in res.data])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        resp = model.generate_content(f"介護要約200字。\n\n{all_t}")
                        st.session_state["monitoring_result"] = resp.text
        st.write("▼ モニタリング作成")
        col_m, col_btn = st.columns([2, 2])
        with col_m: s_m = st.selectbox("月を選択", [f"{i}月" for i in range(1, 13)], index=now_tokyo.month-1)
        with col_btn:
            if st.button("📈 生成", use_container_width=True):
                if f_code:
                    m_num = int(s_m.replace("月", ""))
                    res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).execute()
                    m_recs = [r for r in res.data if datetime.fromisoformat(r['created_at']).month == m_num]
                    if m_recs:
                        all_t = "\n".join([r['content'] for r in m_recs])
                        model = genai.GenerativeModel("models/gemini-2.5-flash")
                        resp = model.generate_content(f"200字報告。内容のみ。\n記録:\n{all_t}")
                        st.session_state["monitoring_result"] = resp.text
        if st.session_state["monitoring_result"]:
            st.session_state["monitoring_result"] = st.text_area("修正", value=st.session_state["monitoring_result"], height=200)
            st.code(st.session_state["monitoring_result"], language=None)
            if st.button("🗑️ クリア"): st.session_state["monitoring_result"] = ""; st.rerun()
        st.divider()
        if st.button("📜 過去の履歴を表示" if not st.session_state.get("show_history_list") else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state.get("show_history_list", False); st.rerun()
        if st.session_state.get("show_history_list") and f_code:
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                try:
                    dt_utc = datetime.fromisoformat(str(r['created_at']).replace('Z', '+00:00'))
                    time_str_hist = dt_utc.astimezone(tokyo_tz).strftime('%Y-%m-%d %H:%M')
                except:
                    time_str_hist = str(r['created_at'])[:16].replace('T', ' ')
                with st.expander(f"📅 {time_str_hist}"):
                    st.write(r['content'])
                    # --- 📸 履歴でも複数枚表示 ---
                    if r.get('image_url') and isinstance(r['image_url'], list):
                        cols = st.columns(min(len(r['image_url']), 5))
                        for idx, url in enumerate(r['image_url']):
                            with cols[idx]: st.image(url, use_container_width=True)
    back_to_top_button("hs_d")

# --- 📅 日別記録閲覧 ---
elif st.session_state["page"] == "daily_view":
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 日別記録閲覧</div>", unsafe_allow_html=True)
    
    dv_date = st.session_state.pop("dv_target_date", now_tokyo.date())
    selected_date = st.date_input("表示する日付を選択", value=dv_date)
    
    if selected_date and f_code:
        try:
            target_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
            target_end = target_start + timedelta(days=1)
            
            with st.spinner("記録を読み込み中..."):
                res = supabase.table("records").select("user_name, content, created_at, staff_name, image_url").eq("facility_code", f_code).gte("created_at", target_start.isoformat()).lt("created_at", target_end.isoformat()).order("created_at", desc=True).execute()
            
            if res.data:
                df_day = pd.DataFrame(res.data).fillna("不明")
                unique_users = df_day["user_name"].unique()
                st.write(f"✅ {selected_date} は **{len(unique_users)}名** の記録があります")
                st.divider()
                
                target_u = st.session_state.pop("dv_target_user", None)
                
                for target_user in unique_users:
                    user_records = df_day[df_day["user_name"] == target_user]
                    is_expanded = (target_user == target_u)
                    
                    with st.expander(f"👤 {target_user} 様 ({len(user_records)}件)", expanded=is_expanded):
                        for _, row in user_records.iterrows():
                            try:
                                dt_utc = datetime.fromisoformat(str(row['created_at']).replace('Z', '+00:00'))
                                time_str = dt_utc.astimezone(tokyo_tz).strftime('%H:%M')
                            except:
                                time_str = str(row['created_at'])[11:16]
                            st.markdown(f"**🕒 {time_str}** （担当: {row['staff_name']}）")
                            st.info(str(row['content']))
                            # --- 📸 【修正】スマートUI：サムネイル横並び表示 (配列対応) ---
                            if row.get('image_url') and isinstance(row['image_url'], list):
                                cols = st.columns(min(len(row['image_url']), 5))
                                for idx, url in enumerate(row['image_url']):
                                    with cols[idx]: st.image(url, use_container_width=True)
                            st.write("")
            else:
                st.info(f"📭 {selected_date} の記録は見つかりませんでした。")
        except Exception as e:
            st.error(f"データの取得に失敗しました: {e}")
            
    back_to_top_button("dv_d")

# --- 🛠️ 管理者メニュー画面 ---
elif st.session_state["page"] == "admin_menu":
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if f_code:
        res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
        if not st.session_state["admin_authenticated"]:
            ad_pw = st.text_input("パスワード", type="password", key="ad_pass")
            if st.button("認証"):
                if ad_pw == cur_pw: st.session_state["admin_authenticated"] = True; st.rerun()
                else: st.error("違います")
            st.stop()
        t1, t2, t3, t4 = st.tabs(["👥 登録", "🚫 ブロック", "🔄 解除", "🔑 パス変更"])
        with t1:
            with st.form("ad_reg"):
                c, n, k = st.text_input("No"), st.text_input("氏名"), st.text_input("ふりがな")
                if st.form_submit_button("登録"):
                    supabase.table("patients").insert({"facility_code": f_code, "chart_number": c, "user_name": n, "user_kana": k}).execute(); st.rerun()
        with t2:
            res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
            s_names = list(set([r['staff_name'] for r in res_s.data])) if res_s.data else []
            target = st.selectbox("ブロック対象", ["(選択)"] + s_names)
            st.warning("※注意！この端末がブロックされます。")
            if st.button("🚨 実行"):
                if target != "(選択)":
                    supabase.table("blocked_devices").insert({"device_id": device_id, "staff_name": target, "facility_code": f_code, "is_active": True}).execute()
                    st.session_state.clear(); st.rerun()
        with t3:
            res_l = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
            for b in res_l.data:
                if st.button(f"復活: {b['staff_name']} (ID:{b['device_id'][:5]})", key=f"re_{b['device_id'][:5]}"):
                    supabase.table("blocked_devices").update({"is_active": False}).eq("device_id", b['device_id']).execute(); st.rerun()
        with t4:
            np, cp = st.text_input("新パス", type="password"), st.text_input("確認", type="password")
            if st.button("更新"):
                if np == cp:
                    if res_pw.data: supabase.table("admin_settings").update({"value": np}).eq("key", "admin_password").eq("facility_code", f_code).execute()
                    else: supabase.table("admin_settings").insert({"facility_code": f_code, "key": "admin_password", "value": np}).execute()
                    st.success("完了"); st.rerun()
    back_to_top_button("ad_d")