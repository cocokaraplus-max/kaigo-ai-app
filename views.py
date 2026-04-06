import streamlit as st
import google.generativeai as genai
import pandas as pd
from datetime import datetime, timedelta
import uuid
import time
from PIL import Image
import re
from utils import tokyo_tz, display_logo, back_to_top_button

def render_top(supabase, cookie_manager, f_code, my_name):
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with c2: 
        if st.button("📊 モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    if st.button("📅 ケース記録閲覧", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    st.divider()
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    else:
        if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

def render_input(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録修正' if is_edit else '✍️ 記録入力'}</div>", unsafe_allow_html=True)
    kid = st.session_state["input_key_id"]
    p_opts = ["(未選択)"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}]" for r in res_p.data]
    except: pass
    sel = st.selectbox("👤 利用者", p_opts, disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=st.session_state.get("edit_date", now_tokyo.date()), disabled=is_edit)
    if not is_edit:
        imgs = st.file_uploader("📷 写真", type=["jpg","png","jpeg"], accept_multiple_files=True)
        aud = st.audio_input("🎤 音声")
        if (imgs or aud) and st.button("✨ AI文章化", type="primary"):
            model = genai.GenerativeModel('models/gemini-2.5-flash')
            contents = ["介護記録を丁寧なです・ます調で書いてください。事実のみを抽出してください。"]
            if imgs: [contents.append(Image.open(i)) for i in imgs]
            if aud: contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
            st.session_state["edit_content"] = model.generate_content(contents).text.strip(); st.rerun()
    txt = st.text_area("内容", value=st.session_state.get("edit_content", ""), height=200)
    if st.button("💾 保存", use_container_width=True):
        if sel != "(未選択)" and txt:
            try:
                if is_edit: supabase.table("records").update({"content": txt}).eq("id", st.session_state["editing_record_id"]).execute()
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    supabase.table("records").insert({"facility_code": f_code, "chart_number": m.group(1), "user_name": m.group(2), "staff_name": my_name, "content": txt, "created_at": dt.isoformat()}).execute()
                st.session_state.update({"page": "top", "editing_record_id": None, "edit_content": "", "input_key_id": str(uuid.uuid4())}); st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    p_opts = ["---"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data: p_opts += [f"(No.{r['chart_number']}) {r['user_name']}" for r in res_p.data]
    except: pass
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = sel.split(") ")[1]
        
        # 🚀 AI口調切り替えセレクター
        summary_target = st.radio("生成する目的を選択", ["内部申し送り用（簡潔）", "ご家族向け（優しい言葉）", "ケアマネ向け（専門的）"], horizontal=True)
        
        month_opts = [f"{now_tokyo.year}年{m:02d}月" for m in range(now_tokyo.month, now_tokyo.month-6, -1)]
        selected_month_str = st.selectbox("対象月", month_opts)
        
        if st.button("✨ モニタリング生成", type="primary"):
            with st.spinner("AIが目的別に分析中..."):
                t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                s_date = tokyo_tz.localize(datetime(t_y, t_m, 1))
                e_date = (s_date + timedelta(days=32)).replace(day=1)
                res = supabase.table("records").select("staff_name, content").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
                if res.data:
                    recs = "\n".join([f"[{r['staff_name']}] {r['content']}" for r in res.data])
                    model = genai.GenerativeModel('models/gemini-2.5-flash')
                    
                    # 🚀 目的別プロンプトの出し分け
                    prompt_map = {
                        "内部申し送り用（簡潔）": "現場職員向けの申し送りです。事実を箇条書きを交えて極めて簡潔に要約してください。",
                        "ご家族向け（優しい言葉）": "ご家族に安心していただけるよう、一ヶ月の様子を温かみのある丁寧な言葉で200文字程度にまとめてください。",
                        "ケアマネ向け（専門的）": "ケアマネジャーへの報告です。ADLや変化の兆候、専門職としての観察視点を中心に公的な文章で要約してください。"
                    }
                    prompt = f"{prompt_map[summary_target]}\n\n【記録】\n{recs}"
                    st.session_state["monitoring_result"] = model.generate_content(prompt).text
                else: st.warning("記録なし")
        
        if st.session_state.get("monitoring_result"):
            st.text_area("編集・コピー", value=st.session_state["monitoring_result"], height=150)
            st.code(st.session_state["monitoring_result"], language="text")
            if "ご家族向け" in summary_target:
                st.info("💡 この文章を家族の連絡帳や将来のLINE連携に活用できます。")
        
        if st.button("📜 過去履歴を表示"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16]} ({r['staff_name']})"):
                    st.write(r['content'])
    back_to_top_button("hs_d")

def render_daily_view(supabase, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 ケース記録閲覧</div>", unsafe_allow_html=True)
    selected_date = st.date_input("日付", value=now_tokyo.date())
    
    if f_code:
        t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
        res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            for user in df["user_name"].unique():
                with st.expander(f"👤 {user} 様"):
                    # 🚀 利用者詳細（フェイスシート）ボタン
                    if st.button(f"📄 {user} 様の基本情報を表示", key=f"face_{user}"):
                        try:
                            p_info = supabase.table("patients").select("*").eq("facility_code", f_code).eq("user_name", user).single().execute()
                            if p_info.data:
                                st.success(f"【基本情報】 No.{p_info.data['chart_number']} / カナ: {p_info.data['user_kana']}")
                                st.info("※将来、ここに既往歴やアレルギー、緊急連絡先を追加します。")
                        except: st.error("情報取得失敗")
                    
                    user_recs = df[df["user_name"] == user]
                    for _, r in user_recs.iterrows():
                        with st.container(border=True):
                            st.write(f"🕒 {r['created_at'][11:16]} ({r['staff_name']})")
                            st.write(r['content'])
        else: st.info("記録なし")
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if not st.session_state.get("admin_authenticated"):
        pw = st.text_input("パスワード", type="password")
        if st.button("認証"):
            res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
            if pw == (res.data[0]['value'] if res.data else "8888"): st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("不一致")
        st.stop()
    t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 スタッフ管理", "⚙️ 設定", "🚫 セキュリティ"])
    # ...（前回のスタッフ管理・復帰ロジックを全記述）...