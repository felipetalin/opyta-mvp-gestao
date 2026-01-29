# app/pages/1_Portfolio_Gantt.py

import re
from contextlib import contextmanager
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# ==========================================================
# Branding / Layout (com fallback seguro)
# ==========================================================
try:
    from ui.brand import apply_brand, apply_app_chrome, page_header  # padrão novo
except Exception:
    from ui.brand import apply_brand  # type: ignore

    def apply_app_chrome():  # type: ignore
        return

    def page_header(title, subtitle, user_email=""):  # type: ignore
        st.title(title)
        if subtitle:
            st.caption(subtitle)
        if user_email:
            st.caption(f"Logado como: {user_email}")


# filter_bar_start pode estar em ui.layout; se não existir, faz fallback simples
try:
    from ui.layout import filter_bar_start  # type: ignore
except Exception:

    @contextmanager
    def filter_bar_start():  # type: ignore
        with st.container():
            yield


# ==========================================================
# Boot (ordem correta)
# ==========================================================
st.set_page_config(page_title="Portfólio (Gantt)", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

page_header("Portfólio (Gantt)", "Filtros + cronograma", st.session_state.get("user_email", ""))


# ==========================================================
# Helpers
# ==========================================================
def month_range(d: date):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    last = nxt - timedelta(days=1)
    return first, last


def add_months(d: date, delta_months: int) -> date:
    # move meses preservando o dia (com clamp)
    y = d.year + (d.month - 1 + delta_months) // 12
    m = (d.month - 1 + delta_months) % 12 + 1
    day = min(d.day, [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def pt_weekday_letter(d: date) -> str:
    letters = ["S", "T", "Q", "Q", "S", "S", "D"]  # Mon..Sun
    return letters[d.weekday()]


def _api_error_message(e: Exception) -> str:
    try:
        if getattr(e, "args", None) and len(e.args) > 0 and isinstance(e.args[0], dict):
            d = e.args[0]
            msg = d.get("message") or str(d)
            details = d.get("details")
            hint = d.get("hint")
            out = msg
            if hint:
                out += f"\nHint: {hint}"
            if details:
                out += f"\nDetalhes: {details}"
            return out
        return str(e)
    except Exception:
        return str(e)


# ==========================================================
# Carregar dados da VIEW
# ==========================================================
@st.cache_data(ttl=30)
def fetch_portfolio_view():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


df = fetch_portfolio_view()

if df.empty:
    st.warning("Nenhuma tarefa encontrada na view v_portfolio_tasks.")
    st.stop()

# ==========================================================
# Normalização / Fallbacks
# ==========================================================
df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")

# Se end_date estiver vazio, assume start_date (tarefa 1 dia)
df["end_date"] = df["end_date"].fillna(df["start_date"])

df = df.dropna(subset=["start_date", "end_date"]).copy()
if df.empty:
    st.warning("Existem registros, mas sem start_date/end_date válidos.")
    st.stop()

if "project_code" not in df.columns:
    df["project_code"] = ""
if "title" not in df.columns:
    df["title"] = ""
if "tipo_atividade" not in df.columns:
    df["tipo_atividade"] = "CAMPO"

# assignee_names (padrão atual). Sem “a definir”.
if "assignee_names" not in df.columns:
    if "assignee_name" in df.columns:
        df["assignee_names"] = df["assignee_name"].fillna("Profissional")
    else:
        df["assignee_names"] = "Profissional"
else:
    df["assignee_names"] = df["assignee_names"].fillna("Profissional")

# status (pra tooltip)
if "status" not in df.columns:
    df["status"] = ""

# Label do eixo Y: COD | Título
df["label"] = (
    df["project_code"].astype(str).fillna("").str.strip()
    + " | "
    + df["title"].astype(str).fillna("").str.strip()
).str.strip(" |")

# ==========================================================
# Filtros + atalhos de mês
# ==========================================================
today = date.today()
d0, d1 = month_range(today)

projects = ["Todos"] + sorted([p for p in df["project_code"].dropna().unique().tolist() if str(p).strip()])
types_all = sorted([t for t in df["tipo_atividade"].dropna().unique().tolist() if str(t).strip()])

# Pessoas: assignee_names vem "A + B + C"
people_set = set()
for s in df["assignee_names"].dropna().astype(str).tolist():
    parts = [p.strip() for p in s.split("+")]
    for p in parts:
        if p:
            people_set.add(p)
people_all = sorted(people_set)

default_types = [t for t in ["CAMPO", "RELATORIO", "ADMINISTRATIVO"] if t in types_all] or types_all
default_people = people_all

# meses disponíveis no dataset (pelo start_date)
df_months = pd.to_datetime(df["start_date"], errors="coerce").dropna()
months_unique = (
    df_months.dt.to_period("M").astype(str).dropna().unique().tolist()
    if not df_months.empty
    else []
)
months_unique = sorted(months_unique)

month_options = ["(Manual)"] + ["Mês atual", "Mês anterior", "Próximo mês"] + months_unique

with filter_bar_start():
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.3, 1.6, 1.3, 1.0])

    with c1:
        sel_project = st.selectbox("Projeto", projects, index=0)

    with c2:
        sel_types = st.multiselect("Tipo Atividade", types_all, default=default_types)

    with c3:
        sel_people = st.multiselect("Profissionais", people_all, default=default_people)

    with c4:
        sel_month = st.selectbox("Atalho (mês)", month_options, index=1)  # default: Mês atual

    with c5:
        show_status_in_bar = st.toggle("Status na barra", value=False, help="Mostra um sufixo no texto da barra. Tooltip já inclui status.")

# período (manual) sempre existe, mas o atalho pode sobrescrever
period = st.date_input("Período", value=(d0, d1), format="DD/MM/YYYY")

if isinstance(period, tuple) and len(period) == 2:
    p_start, p_end = period
else:
    p_start, p_end = d0, d1

# aplica atalho de mês (sem te obrigar a usar o date_input)
if sel_month and sel_month != "(Manual)":
    if sel_month == "Mês atual":
        p_start, p_end = month_range(today)
    elif sel_month == "Mês anterior":
        p_start, p_end = month_range(add_months(today, -1))
    elif sel_month == "Próximo mês":
        p_start, p_end = month_range(add_months(today, 1))
    else:
        # formato "YYYY-MM"
        try:
            y, m = sel_month.split("-")
            p_start = date(int(y), int(m), 1)
            p_start, p_end = month_range(p_start)
        except Exception:
            pass

p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

# ==========================================================
# Aplicar filtros
# ==========================================================
f = df.copy()

if sel_project != "Todos":
    f = f[f["project_code"] == sel_project]

if sel_types:
    f = f[f["tipo_atividade"].isin(sel_types)]
else:
    f = f.iloc[0:0]

# filtro por pessoas (regex com re.escape)
if sel_people:
    patt = "|".join(re.escape(p.strip()) for p in sel_people if p and p.strip())
    if patt:
        f = f[f["assignee_names"].astype(str).str.contains(patt, regex=True, na=False)]
else:
    f = f.iloc[0:0]

# interseção com janela
f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)].copy()

if f.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

# clamp visual
f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

# Ordem cronológica (eixo Y)
order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values(ascending=True)
    .index
    .tolist()
)

# Texto dentro da barra
if show_status_in_bar and "status" in f.columns:
    f["bar_text"] = f["assignee_names"].astype(str) + "  ·  " + f["status"].astype(str)
else:
    f["bar_text"] = f["assignee_names"].astype(str)

# ==========================================================
# Cores (ADMINISTRATIVO bem diferente de CAMPO)
# ==========================================================
color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#1565C0",  # azul (diferencia claramente do verde de campo)
}

# ==========================================================
# Gantt
# ==========================================================
fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="bar_text",
    hover_data={
        "project_code": True,
        "title": True,
        "assignee_names": True,
        "tipo_atividade": True,
        "status": True,  # sugestão de “visualizar status” sem poluir
        "start_date": True,
        "end_date": True,
        "label": False,
        "plot_start": False,
        "plot_end": False,
    },
)

fig.update_yaxes(
    categoryorder="array",
    categoryarray=order,
    title_text="Projeto / Tarefa",
    autorange="reversed",
)

fig.update_traces(
    textposition="inside",
    insidetextanchor="middle",
    cliponaxis=False,
)

fig.update_xaxes(range=[p_start_dt, p_end_dt])

# ticks diários (STQQSSD + dd/mm)
days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
tickvals = [pd.to_datetime(d) for d in days]
ticktext = [f"{pt_weekday_letter(d.date())} {d.day:02d}/{d.month:02d}" for d in days]

fig.update_xaxes(
    tickmode="array",
    tickvals=tickvals,
    ticktext=ticktext,
    tickangle=-90,
    showgrid=True,
    gridcolor="rgba(0,0,0,0.06)",
    title_text="",
)

# fim de semana sombreado
shapes = []
for d in days:
    if d.weekday() >= 5:
        x0 = pd.to_datetime(d.date())
        x1 = x0 + pd.Timedelta(days=1)
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=x0,
                x1=x1,
                y0=0,
                y1=1,
                fillcolor="rgba(102,187,106,0.10)",
                line=dict(width=0),
                layer="below",
            )
        )

# Linha do dia atual (hoje)
today_dt = pd.to_datetime(today)
shapes.append(
    dict(
        type="line",
        xref="x",
        yref="paper",
        x0=today_dt,
        x1=today_dt,
        y0=0,
        y1=1,
        line=dict(color="rgba(220,0,0,0.75)", width=2),
        layer="above",
    )
)

fig.update_layout(shapes=shapes)

fig.update_layout(
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, title_text=""),
    margin=dict(l=10, r=10, t=60, b=40),
)

row_count = f["label"].nunique()
fig.update_layout(height=max(420, 80 + row_count * 55))

st.plotly_chart(fig, use_container_width=True)

with st.expander("Dados (opcional)"):
    st.dataframe(
        f.sort_values(["plot_start", "plot_end"], na_position="last"),
        use_container_width=True,
        hide_index=True,
    )


