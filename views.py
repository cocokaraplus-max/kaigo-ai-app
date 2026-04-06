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
    
    # 更新履歴
    hist_limit = 30
    try:
        res_limit = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_limit.data: hist_limit = int(res_limit.data[0]['value'])
    except: pass

    st.markdown(f"##### 📝 更新履歴 (最新{hist_limit}名まで)")
    today_start = datetime.now(tokyo_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        res_today = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).gte("created_at", today_start.isoformat()).execute()
        if res_today.data:
            df = pd.DataFrame(res_today.data).sort_values("created_at", ascending=False).head(hist_limit)
            for _, row in df.iterrows():
                if st.button(f"👤 {row['user_name']} ({row['created_at'][11:16]})", key=f"h_{row['created_at']}", use_container_width=True):
                    st.session_state.update({"page": "daily_view", "dv_target_user": row['user_name']}); st.rerun()
    except: pass

    st.divider()
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    else:
        if st.button("🛠️ 管理者メニュー", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

def render_input(supabase, cookie_manager, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録修正' if is_edit else '✍️ 記録入力'}</div>", unsafe_allow_html=True)
    p_opts = ["(未選択)"]
    try:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}]" for r in res_p.data]
    except: pass
    
    sel = st.selectbox("👤 利用者", p_opts, disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=st.session_state.get("edit_date", now_tokyo.date()), disabled=is_edit)
    
    if not is_edit:
        imgs = st.file_uploader("📷 写真", type=["jpg","png","jpeg"], accept_multiple_files=True)
        aud = st.audio_input("🎤 音声入力")
        if (imgs or aud) and st.button("✨ AI文章化", type="primary"):
            with st.spinner("AI変換中..."):
                model = genai.GenerativeModel('models/gemini-2.0-flash')
                prompt = "介護職が仲間に共有する申し送り口調（～です、～されています、等の丁寧な専門用語）で、事実を簡潔にまとめてください。職員名は不要です。主語は利用者様にしてください。"
                contents = [prompt]
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
                st.session_state.update({"page": "top", "editing_record_id": None, "edit_content": ""}); st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, cookie_manager, f_code, my_name):
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
        month_opts = [f"{now_tokyo.year}年{m:02d}月" for m in range(now_tokyo.month, now_tokyo.month-6, -1)]
        selected_month_str = st.selectbox("対象月", month_opts)
        
        if st.button("✨ 1ヶ月のまとめを生成", type="primary"):
            with st.spinner("要約中..."):
                t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                s_date = tokyo_tz.localize(datetime(t_y, t_m, 1)); e_date = (s_date + timedelta(days=32)).replace(day=1)
                res = supabase.table("records").select("content").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).execute()
                if res.data:
                    recs = "\n".join([r['content'] for r in res.data])
                    model = genai.GenerativeModel('models/gemini-2.0-flash')
                    prompt = f"以下の1ヶ月分の介護記録を、介護職員が仲間に報告する専門的な口調で、一つの連続した文章にまとめてください。職員名は不要です。主語は利用者様にしてください。\n\n【記録】\n{recs}"
                    st.session_state["monitoring_result"] = model.generate_content(prompt).text
                else: st.warning("記録なし")
        
        if st.session_state.get("monitoring_result"):
            st.text_area("生成結果", value=st.session_state["monitoring_result"], height=200)

def render_daily_view(supabase, cookie_manager, f_code, my_name):
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 ケース記録閲覧・生成</div>", unsafe_allow_html=True)
    selected_date = st.date_input("日付選択", value=now_tokyo.date())
    
    if f_code:
        t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
        res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at", asc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            for user in df["user_name"].unique():
                with st.container(border=True):
                    st.markdown(f"### 👤 {user} 様")
                    user_recs = df[df["user_name"] == user]
                    
                    if st.button(f"✨ 今日のまとめを生成", key=f"gen_{user}"):
                        with st.spinner("文章統合中..."):
                            recs_text = "\n".join([r['content'] for _, r in user_recs.iterrows()])
                            model = genai.GenerativeModel('models/gemini-2.0-flash')
                            prompt = f"以下の今日の介護記録を、介護職員の申し送り口調で一つの自然な文章にまとめてください。職員名は不要です。主語は利用者様にしてください。\n\n{recs_text}"
                            st.info(model.generate_content(prompt).text)

                    for _, r in user_recs.iterrows():
                        st.caption(f"🕒 {r['created_at'][11:16]} ({r['staff_name']})")
                        st.write(r['content'])
                        if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                            if st.button("✏️ 編集", key=f"ed_{r['id']}"):
                                st.session_state.update({"page":"input", "editing_record_id":r['id'], "edit_content":r['content'], "edit_user_label":f"(No.{r['chart_number']}) [{r['user_name']}]", "edit_date":selected_date}); st.rerun()
        else: st.info("記録なし")
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    if not st.session_state.get("admin_authenticated"):
        res = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
        cur_pw = res.data[0]['value'] if res.data else "8888"
        pw = st.text_input("パスワード", type="password")
        if st.button("認証"):
            if pw == cur_pw: st.session_state["admin_authenticated"] = True; st.rerun()
            else: st.error("不一致")
        st.stop()
    
    t1, t2, t3, t4 = st.tabs(["👥 利用者管理", "👮 スタッフ管理", "⚙️ 設定", "🚫 セキュリティ"])
    with t1:
        res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
        with st.expander("🆕 利用者を新規登録"):
            with st.form("reg"):
                c, n, k = st.text_input("No"), st.text_input("氏名"), st.text_input("かな")
                if st.form_submit_button("登録"):
                    supabase.table("patients").insert({"facility_code":f_code, "chart_number":c, "user_name":n, "user_kana":k}).execute(); st.rerun()
        for p in res_p.data:
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1: st.write(f"No.{p['chart_number']} {p['user_name']}")
            with c2: 
                if st.button("修正", key=f"pe_{p['id']}"): st.session_state[f"pedit_{p['id']}"] = True
            with c3: 
                if st.button("削除", key=f"pd_{p['id']}"): supabase.table("patients").delete().eq("id", p['id']).execute(); st.rerun()
            if st.session_state.get(f"pedit_{p['id']}"):
                with st.form(f"f_{p['id']}"):
                    un, uk, uc = st.text_input("氏名", p['user_name']), st.text_input("かな", p['user_kana']), st.text_input("No", p['chart_number'])
                    if st.form_submit_button("確定"): supabase.table("patients").update({"user_name":un, "user_kana":uk, "chart_number":uc}).eq("id", p['id']).execute(); st.rerun()

    with t2:
        st.markdown("##### 👮 スタッフ管理")
        res_s = supabase.table("records").select("staff_name").eq("facility_code", f_code).execute()
        if res_s.data:
            for s in sorted(list(set([r['staff_name'] for r in res_s.data if r['staff_name']]))):
                is_b = len(supabase.table("blocked_devices").select("id").eq("staff_name", s).eq("facility_code", f_code).eq("is_active", True).execute().data) > 0
                c1, c2 = st.columns([3, 1])
                with c1: st.write(f"{'🚫' if is_b else '👤'} **{s}**")
                with c2:
                    if not is_b and st.button("ブロック", key=f"blk_{s}"):
                        supabase.table("blocked_devices").insert({"staff_name":s, "facility_code":f_code, "is_active":True, "device_id":"NAME_LOCK"}).execute(); st.rerun()
    
    with t3:
        st.markdown("##### ⚙️ パスワード・表示件数設定")
        np = st.text_input("新パスワード", type="password")
        if st.button("パスワード更新") and np:
            supabase.table("admin_settings").upsert({"facility_code":f_code, "key":"admin_password", "value":np}, on_conflict="facility_code,key").execute(); st.success("完了")
        res_l = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        cur_l = int(res_l.data[0]['value']) if res_l.data else 30
        new_l = st.slider("履歴表示人数", 10, 100, cur_l, 5)
        if st.button("件数保存"):
            supabase.table("admin_settings").upsert({"facility_code":f_code, "key":"history_limit", "value":str(new_l)}, on_conflict="facility_code,key").execute(); st.success("保存完了")

    with t4:
        st.markdown("##### 🚫 制限解除・復帰")
        res_b = supabase.table("blocked_devices").select("*").eq("facility_code", f_code).eq("is_active", True).execute()
        for b in res_b.data:
            c1, c2 = st.columns([3, 1])
            with c1: st.write(f"🚫 **{b['staff_name'] if b['staff_name'] else b['device_id']}**")
            with c2:
                if st.button("復帰", key=f"res_{b['id']}"):
                    supabase.table("blocked_devices").update({"is_active":False}).eq("id", b['id']).execute(); st.rerun()
    
    if st.button("管理者終了"): st.session_state["admin_authenticated"] = False; st.rerun()
    back_to_top_button("ad_d")