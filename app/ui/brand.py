# app/ui/brand.py
from pathlib import Path
import streamlit as st


def apply_brand(page_title: str = "Opyta"):
    """
    Aplica:
      - CSS da marca
      - Logo no sidebar
      - Título padronizado (se você quiser)
    """
    base_dir = Path(__file__).resolve().parents[1]  # .../app
    css_path = base_dir / "assets" / "brand.css"
    logo_path = base_dir / "assets" / "logo.png"

    # CSS
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

    # Logo (sidebar)
    if logo_path.exists():
        st.sidebar.image(str(logo_path), use_container_width=True)

    # Opcional: espaçamento no sidebar
    st.sidebar.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # (Não força título aqui; você continua usando st.title na página)
    # st.sidebar.markdown(f"**{page_title}**")
