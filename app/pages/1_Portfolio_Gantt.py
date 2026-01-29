# app/pages/1_Portfolio_Gantt.py

import re
from datetime import date, timedelta, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding / Chrome
from ui.brand import apply_brand, apply_app_chrome, page_header
from ui.layout import filter_bar_start


# ==========================================================
# Boot (ordem obrigatória)
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


def shift_month_first(d: date, delta: int) -> date:
    y = d.year
    m = d.month + delta
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return date(y, m, 1)


def month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month-1]}/{d.year}"


def pt_weekday_letter(d: date) -> str:
    letters = ["S", "T", "Q", "Q", "S", "S", "D"]  # Mon..Sun
    return letters[d.weekday()]


def to_dt(x):
    return pd.to_datetime(x, errors="coerce")


def safe_text(x, default=""):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return default
    s = str(x).strip()
    if s in ("None", "nan", "NaT"):
        return default
    return s


def normalize_status(x):
    return safe_text(x).upper().strip()


def split_people(assignee_names):
    out = []
    for p in str(assignee_names or "").split("+"):
        t = p.strip()
        if t:
            out.append(t)
    return out


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
        return "Erro desconhecido."


# ==========================================================
# Load (view)
# ==========================================================
@st.cache_data(ttl=30)
def fetch_portfolio_view():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


df = fetch_portfolio_view()

if df.empty:
    st.warning("Nenhuma tarefa encontrada na view v_portfolio_tasks.")
    st.stop()

# Datas
df["start_date"] = to_dt(df.get("start_date"))
df["end_date"] = to_dt(df.get("end_date"))

# Se end_date vazio, assume start_date
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"]).copy()
if df.empty:
    st.warning("Existem registros, mas sem start_date/end_date válidos.")
    st.stop()

# Fallbacks esperados
if "project_code" not in df.columns:
    df["project_code"] = ""
if "title" not in df.columns:
    df["title"] = ""
if "tipo_atividade" not in df.columns:
    df["tipo_atividade"] = "CAMPO"

# assignee_names (padrão novo). Se vier assignee_name antigo, converte.
if "assignee_names" not in df.columns:
    if "assignee_name" in df.columns:
        df["assignee_names"] = df["assignee_name"].fillna("Profissional")
    else:
        df["assignee_names"] = "Profissional"
df["assignee_names"] = df["assignee_names"].fillna("Profissional")

# status (pode existir ou não)
if "status" not in df.columns:
    df["status"] = ""
df["status"] = df["status"].fillna("")
df["status_norm"] = df["status"].apply(normalize_status)

# Label no eixo Y
df["label"] = (
    df["project_code"].astype(str).fillna("").str.strip()
    + " | "
    + df["title"].astype(str).fillna("").str.strip()
).str.strip(" |")


# ==========================================================
# Filtros
# ==========================================================
today = date.today()
d0, d1 = month_range(today)

projects = ["Todos"] + sorted([p for p in df["project_code"].dropna().unique().tolist() if safe_text(p)])
types_all = sorted([t for t in df["tipo_atividade"].dropna().unique().tolist() if safe_text(t)])

# Pessoas: assignee_names vem "A + B + C"
people_set = set()
for s in df["assignee_names"].dropna().astype(str).tolist():
    for p in split_people(s):
        people_set.add(p)
people_all = sorted(people_set)

default_types = [t for t in ["CAMPO", "RELATORIO", "ADMINISTRATIVO"] if t in types_all] or types_all

# Atalhos de período
cur_first = shift_month_first(today, 0)
prev_first = shift_month_first(today, -1)
next_first = shift_month_first(today, 1)
next2_first = shift_month_first(today, 2)

cur_start, cur_end = month_range(cur_first)
prev_start, _ = month_range(prev_first)
_, next_end = month_range(next_first)
_, next2_end = month_range(next2_first)

period_presets = [
    ("(manual)", None, None),
    (f"Mês atual ({month_label(cur_first)})", cur_start, cur_end),
    (f"2 meses ({month_label(cur_first)} + {month_label(next_first)})", cur_start, next_end),
    (f"3 meses ({month_label(cur_first)} + {month_label(next2_first)})", cur_start, next2_end),
    (f"Mês anterior + atual ({month_label(prev_first)} + {month_label(cur_first)})", prev_start, cur_end),
]
period_labels = [p[0] for p in period_presets]
default_period_idx = 1 if len(period_labels) > 1 else 0

with filter_bar_start():
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.7, 2.2, 1.6, 1.3])

    with c1:
        sel_project = st.selectbox("Projeto", projects, index=0)

    with c2:
        sel_types = st.multiselect("Tipo Atividade", types_all, default=default_types)

    with c3:
        sel_people = st.multiselect("Profissionais", people_all, default=people_all)

    with c4:
        sel_period = st.selectbox("Atalho (período)", period_labels, index=default_period_idx)

    with c5:
        show_status = st.toggle("Status na barra", value=False)
        show_cancelled = st.toggle("Mostrar canceladas", value=True)

# Período final (preset ou manual)
chosen = [p for p in period_presets if p[0] == sel_period][0]
if chosen[0] != "(manual)":
    p_start, p_end = chosen[1], chosen[2]
    st.caption(f"Período: **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**")
else:
    period = st.date_input("Período (manual)", value=(d0, d1), format="DD/MM/YYYY")
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = d0, d1

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

# filtro por pessoas (regex seguro)
if sel_people:
    patt = "|".join(re.escape(p.strip()) for p in sel_people if p and p.strip())
    if patt:
        f = f[f["assignee_names"].astype(str).str.contains(patt, regex=True, na=False)]
else:
    f = f.iloc[0:0]

# canceladas
if not show_cancelled and "status_norm" in f.columns:
    f = f[f["status_norm"] != "CANCELADA"]

# interseção com janela
f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)].copy()

if f.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

# clamp visual
f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

# ordem cronológica
order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values(ascending=True)
    .index
    .tolist()
)

# Texto dentro da barra
status_icon = {
    "CONCLUIDA": "✓",
    "EM_ANDAMENTO": "…",
    "AGUARDANDO_CONFIRMACAO": "⏳",
    "PLANEJADA": "",
    "CANCELADA": "✖",
}
if show_status:
    f["bar_text"] = f.apply(
        lambda r: (status_icon.get(safe_text(r.get("status_norm")), "") + " " + safe_text(r.get("assignee_names"))).strip(),
        axis=1,
    )
else:
    # só um hint leve para canceladas
    f["bar_text"] = f.apply(
        lambda r: (("✖ " if safe_text(r.get("status_norm")) == "CANCELADA" else "") + safe_text(r.get("assignee_names"))).strip(),
        axis=1,
    )

# Cor: admin diferente + cancelada cinza (se estiver visível)
f["tipo_plot"] = f["tipo_atividade"].astype(str)
if "status_norm" in f.columns:
    f.loc[f["status_norm"] == "CANCELADA", "tipo_plot"] = "CANCELADA"

color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2F6DAE",
    "CANCELADA": "#9E9E9E",
}

# ==========================================================
# Gantt
# ==========================================================
fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_plot",
    color_discrete_map=color_map,
    text="bar_text",
    hover_data={
        "project_code": True,
        "title": True,
        "assignee_names": True,
        "tipo_atividade": True,
        "status": True,
        "start_date": True,
        "end_date": True,
        "label": False,
        "plot_start": False,
        "plot_end": False,
        "tipo_plot": False,
        "status_norm": False,
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

# ticks diários
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

# Shapes: fim de semana + linha do hoje
shapes = []

# fim de semana sombreado
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

# linha do dia atual
today_dt = pd.to_datetime(date.today())
if p_start_dt <= today_dt <= p_end_dt:
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






