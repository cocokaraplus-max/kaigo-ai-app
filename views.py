import streamlit as st
import google.generativeai as genai
import tempfile
import os
import pandas as pd
from datetime import datetime, timedelta
import uuid
import time
from PIL import Image # type: ignore
import re
from utils import tokyo_tz, display_logo, back_to_top_button

def render_top(supabase, cookie_manager, f_code, my_name):
    """TOP画面: 権限に応じたメニュー表示"""
    now_tokyo = datetime.now(tokyo_tz)
    display_logo(show_line=True)
    st.markdown(f"<p style='text-align: center;'>🏢 <b>{f_code}</b> ／ 👤 <b>{my_name}</b> さん</p>", unsafe_allow_html=True)
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        if st.button("✍️ 記録を書く", use_container_width=True): st.session_state["page"] = "input"; st.rerun()
    with col_m2:
        if st.button("📊 モニタリング生成", use_container_width=True): st.session_state["page"] = "history"; st.rerun()
    
    if st.button("📅 ケース記録閲覧", use_container_width=True): st.session_state["page"] = "daily_view"; st.rerun()
    
    st.divider()
    
    # 更新履歴の表示（管理者の設定件数に従う）
    hist_limit = 30
    try:
        res_limit = supabase.table("admin_settings").select("value").eq("key", "history_limit").eq("facility_code", f_code).execute()
        if res_limit.data: hist_limit = int(res_limit.data[0]['value'])
    except: pass

    st.markdown(f"##### 📝 更新履歴 (最新{hist_limit}名まで)")
    if f_code:
        today_start = tokyo_tz.localize(datetime.combine(now_tokyo.date(), datetime.min.time()))
        try:
            res_today = supabase.table("records").select("user_name, created_at").eq("facility_code", f_code).gte("created_at", today_start.isoformat()).lt("created_at", (today_start + timedelta(days=1)).isoformat()).execute()
            if res_today.data:
                df = pd.DataFrame(res_today.data)
                grouped = df.groupby("user_name").agg(count=("user_name", "size"), last_time=("created_at", "max")).reset_index()
                grouped = grouped.sort_values("last_time", ascending=False).head(hist_limit)
                with st.container(height=250):
                    for _, row in grouped.iterrows():
                        try:
                            dt_utc = datetime.fromisoformat(str(row['last_time']).replace('Z', '+00:00'))
                            time_str = dt_utc.astimezone(tokyo_tz).strftime('%m/%d %H:%M')
                        except: time_str = str(row['last_time'])[5:16].replace('-', '/')
                        if st.button(f"👤 {row['user_name']} 様 ({row['count']}件) 最終 {time_str}", key=f"h_{row['user_name']}", use_container_width=True):
                            st.session_state.update({"page": "daily_view", "dv_target_user": row['user_name'], "dv_target_date": now_tokyo.date()}); st.rerun()
            else: st.info("本日の記録はまだありません。")
        except: pass

    st.divider()
    
    # 🚀 管理者メニューへの導線（認証済みならダイレクトに表示）
    if st.session_state.get("admin_authenticated"):
        if st.button("🛠️ 管理者メニュー (認証済み)", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()
    else:
        if st.button("🛠️ 管理者メニューへログイン", use_container_width=True): st.session_state["page"] = "admin_menu"; st.rerun()

    if st.button("🚪 ログアウト"):
        cookie_manager.delete("saved_f_code"); cookie_manager.delete("saved_my_name"); st.session_state.clear(); st.rerun()

def render_input(supabase, f_code, my_name):
    """入力画面: AI変換とクラウド保存"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("ip_u")
    is_edit = st.session_state.get("editing_record_id") is not None
    st.markdown(f"<div class='main-title'>{'📝 記録を修正' if is_edit else '✍️ ケース記録入力'}</div>", unsafe_allow_html=True)
    
    kid = st.session_state["input_key_id"]
    p_opts = ["(未選択)"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) [{r['user_name']}] [{r['user_kana']}]" for r in res_p.data]
        except: pass
    
    default_sel = st.session_state.get("edit_user_label", "(未選択)")
    default_date = st.session_state.get("edit_date", now_tokyo.date())
    sel = st.selectbox("👤 利用者を選択", p_opts, index=p_opts.index(default_sel) if default_sel in p_opts else 0, key=f"sel_{kid}", disabled=is_edit)
    record_date = st.date_input("📅 記録日", value=default_date, key=f"date_{kid}", disabled=is_edit)
    st.markdown("---")
    
    if not is_edit:
        t_imgs = st.file_uploader("📷 写真（最大5枚）", type=["jpg", "png", "jpeg"], accept_multiple_files=True, key=f"img_{kid}")
        aud = st.audio_input("録音ボタン", key=f"aud_{kid}")
        if (t_imgs or aud) and st.button("✨ AIで文章にする", type="primary", key="btn_ai"):
            with st.spinner("AIが現場の声を文章に変換中..."):
                try:
                    model = genai.GenerativeModel('models/gemini-2.5-flash')
                    prompt = "あなたは介護のプロです。入力された音声や画像から事実のみを読み取り、職員間の連絡に適した「丁寧なです・ます調」で簡潔に記録を書いてください。挨拶や余計な解説は一切書かず、文章のみを出力してください。"
                    contents = [prompt]
                    if t_imgs:
                        for img in t_imgs: contents.append(Image.open(img))
                    if aud:
                        contents.append({"mime_type": "audio/wav", "data": aud.getvalue()})
                    response = model.generate_content(contents)
                    if response.text.strip():
                        st.session_state["edit_content"] = response.text.strip()
                        st.session_state[f"txt_{kid}"] = response.text.strip()
                        st.rerun()
                except Exception as e: st.error(f"AIエラー: {e}")
            
    txt = st.text_area("内容", value=st.session_state.get(f"txt_{kid}", st.session_state["edit_content"]), height=200, key=f"txt_{kid}")
    
    if st.button("🆙 修正を保存" if is_edit else "💾 クラウドに保存", use_container_width=True, key="btn_save"):
        if sel != "(未選択)" and txt and f_code:
            try:
                if is_edit:
                    supabase.table("records").update({"content": txt, "updated_at": now_tokyo.isoformat()}).eq("id", st.session_state["editing_record_id"]).execute()
                else:
                    m = re.search(r'\(No\.(.*?)\) \[(.*?)\]', sel)
                    dt = tokyo_tz.localize(datetime.combine(record_date, datetime.now(tokyo_tz).time()))
                    urls = []
                    if t_imgs:
                        for img in t_imgs[:5]: 
                            f_name = f"{uuid.uuid4()}.{img.name.split('.')[-1]}"
                            supabase.storage.from_("case-photos").upload(f_name, img.getvalue())
                            res_url = supabase.storage.from_("case-photos").get_public_url(f_name)
                            urls.append(res_url.public_url if hasattr(res_url, 'public_url') else str(res_url))
                    supabase.table("records").insert({
                        "facility_code": f_code, "chart_number": str(m.group(1)), "user_name": m.group(2), 
                        "staff_name": my_name, "content": txt, "image_url": urls if urls else None, "created_at": dt.isoformat()
                    }).execute()
                st.session_state.update({"edit_content": "", "input_key_id": str(uuid.uuid4()), "editing_record_id": None, "page": "top"})
                time.sleep(0.5); st.rerun()
            except Exception as e: st.error(f"エラー: {e}")
    back_to_top_button("ip_d")

def render_history(supabase, f_code, my_name):
    """モニタリング生成: 1ヶ月要約と編集・コピー枠"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("hs_u")
    st.markdown("<div class='main-title'>📊 モニタリング生成</div>", unsafe_allow_html=True)
    
    p_opts = ["---"]
    if f_code:
        try:
            res_p = supabase.table("patients").select("*").eq("facility_code", f_code).order("user_kana").execute()
            if res_p.data: p_opts += [f"(No.{r['chart_number']}) {r['user_name']} [{r['user_kana']}]" for r in res_p.data]
        except: pass
    
    sel = st.selectbox("利用者を選択", p_opts)
    if sel != "---":
        u_name = re.search(r'\) (.*?) \[', sel).group(1) if '[' in sel else re.search(r'\) (.*)', sel).group(1)
        st.divider()
        st.markdown("##### ✨ 1ヶ月分のAIモニタリング作成")
        
        # 過去6ヶ月の選択肢
        month_opts = []
        for i in range(6):
            dt = now_tokyo.date().replace(day=1) - timedelta(days=i*30)
            month_opts.append(f"{dt.year}年{dt.month:02d}月")
            
        selected_month_str = st.selectbox("対象月を選択", month_opts)
        
        if st.button(f"✨ {selected_month_str} の報告書を生成", type="primary"):
            with st.spinner("AIが記録を分析中..."):
                try:
                    t_y, t_m = int(selected_month_str[:4]), int(selected_month_str[5:7])
                    s_date = tokyo_tz.localize(datetime(t_y, t_m, 1))
                    e_date = (s_date + timedelta(days=32)).replace(day=1)
                    
                    res_mon = supabase.table("records").select("created_at, staff_name, content").eq("facility_code", f_code).eq("user_name", u_name).gte("created_at", s_date.isoformat()).lt("created_at", e_date.isoformat()).order("created_at").execute()
                    
                    if res_mon.data:
                        records_text = "\n".join([f"[{r['staff_name']}] {r['content']}" for r in res_mon.data])
                        model = genai.GenerativeModel('models/gemini-2.5-flash')
                        prompt = f"あなたは介護職員です。以下の{u_name}様の1ヶ月分のケース記録を、200文字以内の自然な口語調で報告書として要約してください。事実のみをありのままに伝えてください。挨拶や解説は不要です。\n\n【記録】\n{records_text}"
                        response = model.generate_content(prompt)
                        st.session_state["monitoring_result"] = response.text
                    else: st.warning("対象月の記録が見つかりませんでした。")
                except Exception as e: st.error(f"エラー: {e}")

        if st.session_state.get("monitoring_result"):
            st.markdown("---")
            edited = st.text_area("📝 生成されたモニタリング（編集可能）", value=st.session_state["monitoring_result"], height=150)
            st.session_state["monitoring_result"] = edited
            st.markdown("##### 📋 コピー用枠")
            st.code(edited, language="text")

        st.divider()
        st.markdown("##### 📜 過去の個別ケース記録")
        if st.button("全履歴を表示" if not st.session_state.get("show_history_list") else "閉じる"):
            st.session_state["show_history_list"] = not st.session_state.get("show_history_list", False); st.rerun()
        
        if st.session_state.get("show_history_list"):
            res = supabase.table("records").select("*").eq("facility_code", f_code).eq("user_name", u_name).order("created_at", desc=True).execute()
            for r in res.data:
                with st.expander(f"📅 {r['created_at'][:16]} (担当: {r['staff_name']})"):
                    st.write(r['content'])
                    # 🚀 権限チェック: 本人 OR 管理者
                    if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                        if st.button("✏️ 編集", key=f"ed_h_{r['id']}"):
                            st.session_state.update({
                                "page": "input", "editing_record_id": r['id'], "edit_content": r['content'], 
                                "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]", 
                                "edit_date": datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()
                            }); st.rerun()
    back_to_top_button("hs_d")

def render_daily_view(supabase, f_code, my_name):
    """閲覧画面: アコーディオン即時表示とオンデマンド要約"""
    now_tokyo = datetime.now(tokyo_tz)
    back_to_top_button("dv_u")
    st.markdown("<div class='main-title'>📅 ケース記録閲覧</div>", unsafe_allow_html=True)
    
    dv_date = st.session_state.pop("dv_target_date", now_tokyo.date())
    selected_date = st.date_input("表示する日付を選択", value=dv_date)
    
    if selected_date and f_code:
        try:
            t_start = tokyo_tz.localize(datetime.combine(selected_date, datetime.min.time()))
            res = supabase.table("records").select("*").eq("facility_code", f_code).gte("created_at", t_start.isoformat()).lt("created_at", (t_start + timedelta(days=1)).isoformat()).order("created_at", desc=True).execute()
            
            if res.data:
                df = pd.DataFrame(res.data)
                unique_users = df["user_name"].unique()
                st.write(f"✅ {selected_date}: **{len(unique_users)}名** の記録")
                
                target_u = st.session_state.pop("dv_target_user", None)
                for user in unique_users:
                    user_recs = df[df["user_name"] == user]
                    with st.expander(f"👤 {user} 様 ({len(user_recs)}件)", expanded=(user == target_u)):
                        sum_key = f"sum_{selected_date}_{user}"
                        if sum_key not in st.session_state:
                            if len(user_recs) > 1:
                                if st.button("✨ 1日のまとめを作成する", key=f"btn_{sum_key}"):
                                    with st.spinner("要約中..."):
                                        model = genai.GenerativeModel('models/gemini-2.5-flash')
                                        daily_txt = "\n".join([f"[{r['staff_name']}] {r['content']}" for _, r in user_recs.iterrows()])
                                        prompt = f"以下の1日分の介護記録を、丁寧なです・ます調で1つの申し送りに要約してください。挨拶は不要です。\n\n{daily_txt}"
                                        response = model.generate_content(prompt)
                                        st.session_state[sum_key] = response.text; st.rerun()
                            else: st.session_state[sum_key] = user_recs.iloc[0]['content']
                        
                        if sum_key in st.session_state:
                            st.info(st.session_state[sum_key])
                        
                        st.markdown("---")
                        for _, r in user_recs.iterrows():
                            with st.expander(f"🕒 {r['created_at'][11:16]} ／ 担当: {r['staff_name']}"):
                                st.write(r['content'])
                                if r.get('image_url'):
                                    for url in r['image_url']: st.image(url, use_container_width=True)
                                # 🚀 権限チェック: 本人 OR 管理者
                                if str(r['staff_name']) == str(my_name) or st.session_state.get("admin_authenticated"):
                                    if st.button("✏️ 編集", key=f"ed_dv_{r['id']}"):
                                        st.session_state.update({
                                            "page": "input", "editing_record_id": r['id'], "edit_content": r['content'], 
                                            "edit_user_label": f"(No.{r['chart_number']}) [{r['user_name']}]", 
                                            "edit_date": datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date()
                                        }); st.rerun()
            else: st.info("本日の記録はありません。")
        except Exception as e: st.error(f"失敗: {e}")
    back_to_top_button("dv_d")

def render_admin_menu(supabase, cookie_manager, f_code, my_name, device_id):
    """管理者メニュー: パスワード認証と各種設定"""
    back_to_top_button("ad_u")
    st.markdown("<div class='main-title'>🛠️ 管理者メニュー</div>", unsafe_allow_html=True)
    
    if not st.session_state.get("admin_authenticated"):
        try:
            res_pw = supabase.table("admin_settings").select("value").eq("key", "admin_password").eq("facility_code", f_code).execute()
            cur_pw = res_pw.data[0]['value'] if res_pw.data else "8888"
            ad_pw_in = st.text_input("管理者パスワードを入力してください", type="password")
            if st.button("認証"):
                if ad_pw_in == cur_pw:
                    st.session_state["admin_authenticated"] = True
                    st.success("管理者認証に成功しました！")
                    time.sleep(0.5); st.rerun()
                else: st.error("パスワードが違います。")
            st.stop()
        except: st.error("設定の読み込みに失敗しました。")

    t1, t2, t3 = st.tabs(["👥 利用者/スタッフ管理", "⚙️ システム設定", "🚫 セキュリティ"])
    
    with t1:
        st.markdown("##### 👥 利用者の新規登録・管理")
        # ここに利用者登録フォーム等のロジック（既存維持）を配置...
        st.info("※利用者・スタッフのマスター管理機能をここに実装予定")

    with t2:
        st.markdown("##### ⚙️ 表示・パスワード設定")
        # 履歴表示件数（スライダー）やパスワード変更ロジックを配置...
        st.info("※施設ごとの動作設定をここに実装予定")

    with t3:
        st.markdown("##### 🚫 端末ブロック解除")
        # ブロック済みデバイスのリストと解除ボタン...
        st.info("※不正アクセス端末の管理機能をここに実装予定")
    
    if st.button("🛠️ 管理者モードを終了"):
        st.session_state["admin_authenticated"] = False; st.rerun()
    back_to_top_button("ad_d")