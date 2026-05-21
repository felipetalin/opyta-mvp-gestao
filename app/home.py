import streamlit as st
from ui.brand import apply_brand, apply_app_chrome, page_header

from services.auth import require_login, logout

st.set_page_config(page_title="Opyta - Gestão de Projetos (MVP)", layout="wide")

require_login()
apply_brand()
apply_app_chrome()

email = st.session_state.get("user_email", "")
page_header("Opyta - Gestão de Projetos (MVP)", "Ambiente de testes (MVP)", user_email=email)

# (o resto do seu home continua igual)

# (se você já tinha botões/atalhos aqui, mantém abaixo)


# Se você tiver botão de sair:
# if st.button("Sair"):
#     logout()


st.write("Use o menu à esquerda para navegar: Portfólio Gantt, Projetos e Tarefas.")



