# app/ui/brand.py
import streamlit as st
from pathlib import Path

# Ajuste se sua logo estiver em outro caminho
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "logo.png"


def apply_brand():
    """
    Tema/cores (tons de verde) + ajustes globais.
    """
    st.markdown(
        """
        <style>
          :root{
            --opyta-green:#5E7D3A;
            --opyta-green-2:#3F5E26;
            --opyta-soft:#F3F6F0;
            --opyta-border: rgba(90, 120, 60, 0.25);
          }

          /* Fundo geral */
          .stApp {
            background: var(--opyta-soft);
          }

          /* Títulos */
          h1, h2, h3, h4 {
            color: #1f2a17;
          }

          /* Containers/bordas suaves */
          div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stContainer"]) {
            border-color: var(--opyta-border);
          }

          /* Botão primário no verde */
          .stButton > button[kind="primary"]{
            background: var(--opyta-green);
            border: 1px solid var(--opyta-green-2);
          }
          .stButton > button[kind="primary"]:hover{
            background: var(--opyta-green-2);
            border: 1px solid var(--opyta-green-2);
          }

          /* Inputs com foco verde */
          .stTextInput input:focus,
          .stTextArea textarea:focus,
          .stSelectbox div:focus-within,
          .stDateInput input:focus{
            outline: none !important;
            box-shadow: 0 0 0 0.2rem var(--opyta-border) !important;
            border-color: var(--opyta-green) !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def apply_app_chrome():
    """
    Sidebar + logo com tamanho consistente.
    (Isso é o que evita a logo ficar minúscula.)
    """
    st.markdown(
        """
        <style>
          /* Sidebar mais “corporativa” */
          section[data-testid="stSidebar"]{
            background: #eef3e9;
            border-right: 1px solid rgba(90,120,60,0.18);
          }

          /* Padding interno da sidebar */
          section[data-testid="stSidebar"] > div {
            padding-top: 0.75rem;
          }

          /* Logo: força tamanho mínimo/consistente */
          section[data-testid="stSidebar"] img {
            width: 100% !important;
            max-width: 220px !important;   /* ajuste fino */
            height: auto !important;
            margin: 0.75rem auto 0.25rem auto !important;
            display: block;
          }

          /* Deixa o menu mais “limpo” */
          section[data-testid="stSidebar"] a,
          section[data-testid="stSidebar"] span {
            font-size: 0.92rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        # use_container_width evita ficar “thumbnail”
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), use_container_width=True)
        else:
            st.caption("Logo não encontrada em app/assets/logo.png")


def page_header(title: str, subtitle: str = "", user_email: str = ""):
    """
    Cabeçalho padrão no topo da página (card).
    """
    st.markdown(
        f"""
        <div style="
          background: white;
          border: 1px solid rgba(90,120,60,0.18);
          border-radius: 12px;
          padding: 14px 16px;
          margin-bottom: 14px;">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size: 18px; font-weight: 700; color: #1f2a17;">{title}</div>
              <div style="font-size: 13px; color: rgba(31,42,23,0.75);">{subtitle}</div>
            </div>
            <div style="font-size: 12px; color: rgba(31,42,23,0.65);">{user_email}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
