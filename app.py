import streamlit as st

# ==========================================
# ⚙️ ページ基本設定（必ず最初に呼ぶ）
# ==========================================
st.set_page_config(
    page_title="TASUKARU",
    page_icon="🦝",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 📦 その他のimport
# ==========================================
from supabase import create_client, Client
from views import render_top, render_input, render_history, render_daily_view, render_admin_menu
from utils import cookie_manager, display_logo
import uuid

# ==========================================
# 🚀 Supabase 接続
# ==========================================
try:
    url: str = st.secrets["SUPABASE_URL"].strip()
    key: str = st.secrets["SUPABASE_KEY"].strip()
    supabase: Client = create_client(url, key)
except KeyError as e:
    st.error(f"🚨 Secrets の設定が見つかりません: {e}")
    st.info("👉 Streamlit Cloud の「Secrets」に SUPABASE_URL と SUPABASE_KEY を設定してください。")
    st.stop()
except Exception as e:
    st.error("🚨 データベースへの接続に失敗しました。")
    st.info(f"エラー詳細（管理者向け）: {e}")
    st.stop()

# ==========================================
# 🔄 セッション状態の初期化
# ==========================================
if "page" not in st.session_state:
    st.session_state["page"] = "login"

if "device_id" not in st.session_state:
    st.session_state["device_id"] = str(uuid.uuid4())

for key_name in ["edit_content", "monitoring_result", "admin_authenticated"]:
    if key_name not in st.session_state:
        st.session_state[key_name] = "" if "content" in key_name else False

# ==========================================
# 🔑 ログイン画面
# ==========================================
def render_login():
    display_logo(show_line=False)
    st.markdown("<h3 style='text-align: center;'>施設コードを入力してください</h3>", unsafe_allow_html=True)

    saved_f_code = cookie_manager.get("saved_f_code") or ""
    saved_my_name = cookie_manager.get("saved_my_name") or ""

    f_code = st.text_input("施設コード", value=saved_f_code)
    my_name = st.text_input("あなたの名前", value=saved_my_name)

    if st.button("ログイン", use_container_width=True, type="primary"):
        if f_code and my_name:
            try:
                res = supabase.table("blocked_devices") \
                    .select("*") \
                    .eq("facility_code", f_code) \
                    .eq("is_active", True) \
                    .execute()

                blocked = any(
                    b.get("device_id") == st.session_state.get("device_id")
                    or b.get("staff_name") == my_name
                    for b in res.data
                )

                if blocked:
                    st.error("🚫 この端末またはユーザーは利用できません。管理者にお問い合わせください。")
                else:
                    cookie_manager["saved_f_code"] = f_code
                    cookie_manager["saved_my_name"] = my_name
                    cookie_manager.save()
                    st.session_state["page"] = "top"
                    st.rerun()

            except Exception as e:
                st.error("🚨 ログイン中にエラーが発生しました。しばらく待ってから再試行してください。")
                st.caption(f"エラー詳細（管理者向け）: {e}")
        else:
            st.warning("⚠️ 施設コードと名前を両方入力してください。")

# ==========================================
# 🗺️ ページルーティング
# ==========================================
f_code = cookie_manager.get("saved_f_code")
my_name = cookie_manager.get("saved_my_name")

if st.session_state["page"] == "login":
    render_login()
elif not f_code or not my_name:
    st.session_state["page"] = "login"
    st.rerun()
else:
    p = st.session_state["page"]
    if p == "top":
        render_top(supabase, cookie_manager, f_code, my_name)
    elif p == "input":
        render_input(supabase, cookie_manager, f_code, my_name)
    elif p == "history":
        render_history(supabase, cookie_manager, f_code, my_name)
    elif p == "daily_view":
        render_daily_view(supabase, cookie_manager, f_code, my_name)
    elif p == "admin":
        render_admin_menu(supabase, cookie_manager, f_code, my_name, st.session_state.get("device_id"))

    st.divider()
    if st.button("🛠️ 管理者メニュー", key="admin_access_btn"):
        st.session_state["page"] = "admin"
        st.rerun()