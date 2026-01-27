# app/ui/layout.py
import streamlit as st

def apply_app_chrome():
    """Remove ruídos do Streamlit e padroniza espaçamentos."""
    st.markdown(
        """
        <style>
          /* some coisas do streamlit */
          #MainMenu {visibility: hidden;}
          footer {visibility: hidden;}
          header {visibility: hidden;}

          /* largura/padding mais “app” */
          .block-container {
            padding-top: 1.0rem;
            padding-bottom: 1.2rem;
          }

          /* títulos mais alinhados */
          h1, h2, h3 { letter-spacing: -0.3px; }

          /* containers (borda arredondada) */
          .stContainer {
            border-radius: 12px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str | None = None, user_email: str | None = None):
    """Header padrão em todas as páginas."""
    left, right = st.columns([4, 1])
    with left:
        st.title(title)
        if subtitle:
            st.caption(subtitle)
    with right:
        if user_email:
            st.caption(f"Logado como: **{user_email}**")


def filter_bar_start():
    """Começo de uma faixa de filtros bonita/padrão."""
    return st.container(border=True)
