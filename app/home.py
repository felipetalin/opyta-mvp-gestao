import os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
from dotenv import load_dotenv
from services.auth import login, logout

load_dotenv()

st.set_page_config(page_title="Opyta - Gestão de Projetos", layout="wide")
st.title("Opyta - Gestão de Projetos (MVP)")

if "sb_session" not in st.session_state:
    st.session_state["sb_session"] = None
    st.session_state["sb_user"] = None

if st.session_state["sb_session"] is None:
    st.subheader("Login")
    email = st.text_input("Email")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        try:
            login(email, password)
            st.success("Logado com sucesso.")
            st.rerun()
        except Exception as e:
            st.error(f"Falha no login: {e}")
else:
    st.success(f"Logado como: {st.session_state['sb_user'].email}")
    if st.button("Sair"):
        logout()
        st.rerun()

st.markdown("Depois do login, vamos criar as páginas do Portfólio (Gantt) e Projetos.")
