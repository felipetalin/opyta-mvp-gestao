# --- PATH BOOTSTRAP (Streamlit Cloud) ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ----------------------------------------

import streamlit as st
from services.auth import require_login, logout

st.set_page_config(page_title="Opyta - Gestão de Projetos (MVP)", layout="wide")

require_login()

st.title("Opyta - Gestão de Projetos (MVP)")

user_email = st.session_state.get("user_email", "(desconhecido)")
st.success(f"Logado como: {user_email}")

col1, col2 = st.columns([1, 6])
with col1:
    if st.button("Sair"):
        logout()
        st.rerun()

st.write("Use o menu à esquerda para navegar.")

