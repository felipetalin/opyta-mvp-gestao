import streamlit as st
from services.auth import require_login, logout

st.set_page_config(page_title="Opyta - Gestão de Projetos (MVP)", layout="wide")

require_login()

st.title("Opyta - Gestão de Projetos (MVP)")

email = st.session_state.get("user_email", "")
st.success(f"Logado como: {email}")

col1, _ = st.columns([1, 6])
with col1:
    if st.button("Sair"):
        logout()
        st.rerun()

st.write("Use o menu à esquerda para navegar: Portfólio Gantt, Projetos e Tarefas.")



