# app/pages/1_Portfolio_Gantt.py

import re
from datetime import date, timedelta

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

page_header(
    "Portfólio (Gantt)",
    "Filtros + cronograma",
    st.session_state.get("user_email", ""),
)


# ==========================================================
# Helpers
# ==========================================================
def month_range(d: date):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    return first, nxt - timedelta(days=1)


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
    return ["S", "T", "Q", "Q", "S", "S", "D"][d.weekday()]


def safe_text(x, default=""):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return default
    s = str(x).strip()
    if s in ("None", "nan", "NaT"):
        return default
    return s


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
df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"])

# Fallbacks
df["project_code"] = df.get("project_code", "").fillna("")
df["title"] = df.get("title", "").fillna("")
df["tipo_atividade"] = df.get("tipo_atividade", "CAMPO").fillna("CAMPO")
df["assignee_names"] = df.get("assignee_names", "Profissional").fillna("Profissional")
df["date_confidence"] = df.get("date_confidence", "PLANEJADO").fillna("PLANEJADO")

# Label eixo Y
df["label"] = (
    df["project_code"].str.strip()
    + " | "
    + df["title"].str.strip()
).str.strip(" |")


# ==========================================================
# Filtros
# ==========================================================
today = date.today()
d0, d1 = month_range(today)

projects = ["Todos"] + sorted([p for p in df["project_code"].unique() if p])
types_all = sorted([t for t in df["tipo_atividade"].unique() if t])

people_set = set()
for s in df["assignee_names"]:
    for p in str(s).split("+"):
        if p.strip():
            people_set.add(p.strip())
people_all = sorted(people_set)

default_types = [t for t in ["CAMPO", "RELATORIO", "ADMINISTRATIVO"] if t in types_all] or types_all

# Períodos
cur = shift_month_first(today, 0)
next1 = shift_month_first(today, 1)
next2 = shift_month_first(today, 2)

cur_s, cur_e = month_range(cur)
_, next1_e = month_range(next1)
_, next2_e = month_range(next2)

period_presets = [
    ("(manual)", None, None),
    (f"Mês atual ({month_label(cur)})", cur_s, cur_e),
    (f"2 meses ({month_label(cur)} + {month_label(next1)})", cur_s, next1_e),
    (f"3 meses ({month_label(cur)} + {month_label(next2)})", cur_s, next2_e),
]

labels = [p[0] for p in period_presets]

with filter_bar_start():
    c1, c2, c3, c4 = st.columns([1.2, 1.8, 2.4, 1.6])

    with c1:
        sel_project = st.selectbox("Projeto", projects)

    with c2:
        sel_types = st.multiselect("Tipo Atividade", types_all, default=default_types)

    with c3:
        sel_people = st.multiselect("Profissionais", people_all, default=people_all)

    with c4:
        sel_period = st.selectbox("Atalho (período)", labels, index=1)


chosen = [p for p in period_presets if p[0] == sel_period][0]
if chosen[0] != "(manual)":
    p_start, p_end = chosen[1], chosen[2]
else:
    p_start, p_end = st.date_input("Período", value=(d0, d1), format="DD/MM/YYYY")

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

if sel_people:
    patt = "|".join(re.escape(p) for p in sel_people)
    f = f[f["assignee_names"].str.contains(patt, regex=True)]

f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)]

if f.empty:
    st.info("Nenhuma tarefa para os filtros selecionados.")
    st.stop()

f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values()
    .index
    .tolist()
)

# ==========================================================
# Texto da barra (STATUS FINAL)
# ==========================================================
status_icon = {
    "CONFIRMADO": "✅",
    "PLANEJADO": "🕓",
    "AGUARDANDO_CONFIRMACAO": "⏳",
    "CANCELADO": "❌",
}

f["bar_text"] = f.apply(
    lambda r: f"{status_icon.get(r['date_confidence'], '')} {r['date_confidence']} – {r['assignee_names']}".strip(),
    axis=1,
)


# ==========================================================
# Gantt
# ==========================================================
color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2F6DAE",
}

fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="bar_text",
)

fig.update_yaxes(
    categoryorder="array",
    categoryarray=order,
    autorange="reversed",
    title="Projeto / Tarefa",
)

fig.update_traces(
    textposition="inside",
    insidetextanchor="middle",
    cliponaxis=False,
)

days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
fig.update_xaxes(
    tickmode="array",
    tickvals=days,
    ticktext=[f"{pt_weekday_letter(d.date())} {d.day:02d}/{d.month:02d}" for d in days],
    tickangle=-90,
)

# Hoje
today_dt = pd.to_datetime(today)
fig.add_vline(x=today_dt, line_color="red", line_width=2)

fig.update_layout(
    legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    height=max(420, 80 + f["label"].nunique() * 55),
    margin=dict(l=10, r=10, t=60, b=40),
)

st.plotly_chart(fig, use_container_width=True)









