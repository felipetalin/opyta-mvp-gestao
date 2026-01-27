# app/ui/brand.py
import base64
from pathlib import Path
import streamlit as st


def _img_to_base64(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return base64.b64encode(p.read_bytes()).decode("utf-8")


def apply_brand():
    """
    Aplica CSS global + logo no sidebar.
    Espera a logo em: app/assets/logo.png
    """
    logo_b64 = _img_to_base64("app/assets/logo.png")

    css = """
    <style>
      .opyta-app { padding-top: 0.25rem; }
      .opyta-topbar {
        display:flex; align-items:center; justify-content:space-between;
        padding: 0.6rem 0.8rem;
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 14px;
        background: #ffffff;
        box-shadow: 0 1px 10px rgba(0,0,0,0.04);
        margin-bottom: 0.9rem;
      }
      .opyta-topbar .left { display:flex; flex-direction:column; gap:0.1rem; }
      .opyta-title { font-size: 1.15rem; font-weight: 700; margin: 0; }
      .opyta-subtitle { font-size: 0.85rem; opacity: 0.7; margin: 0; }
      .opyta-user { font-size: 0.85rem; opacity: 0.75; }
      /* melhora espaçamento padrão */
      section.main > div { padding-top: 1rem; }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

    if logo_b64:
        st.sidebar.markdown(
            f"""
            <div style="display:flex;align-items:center;gap:10px;margin:6px 0 14px 0;">
              <img src="data:image/png;base64,{logo_b64}" style="height:36px;border-radius:8px;" />
              <div style="font-weight:700;font-size:1.0rem;">Opyta</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def apply_app_chrome():
    """
    Placeholder para futuras melhorias (menu, espaçamentos, etc).
    Mantive separado pra você evoluir sem mexer nas pages.
    """
    st.markdown('<div class="opyta-app"></div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", user_email: str = ""):
    subtitle_html = f'<p class="opyta-subtitle">{subtitle}</p>' if subtitle else ""
    user_html = f'<div class="opyta-user">{user_email}</div>' if user_email else ""

    st.markdown(
        f"""
        <div class="opyta-topbar">
          <div class="left">
            <p class="opyta-title">{title}</p>
            {subtitle_html}
          </div>
          {user_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
