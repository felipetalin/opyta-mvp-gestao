# app/pages/1_Portfolio_Gantt.py

import re
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

from ui.brand import apply_brand, apply_app_chrome, page_header
from ui.layout import filter_bar_start


# ==========================================================
# Boot
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
def month_range(d):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    last = nxt - timedelta(days=1)
    return first, last


def shift_month_first(d, delta):
    y = d.year
    m = d.month + delta
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return date(y, m, 1)


def month_label(d):
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month-1]}/{d.year}"


def pt_weekday_letter(d):
    letters = ["S", "T", "Q", "Q", "S", "S", "D"]
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


def make_period_presets(today_):
    cur_first = shift_month_first(today_, 0)
    prev_first = shift_month_first(today_, -1)
    next_first = shift_month_first(today_, 1)
    next2_first = shift_month_first(today_, 2)

    cur_start, cur_end = month_range(cur_first)
    prev_start, _ = month_range(prev_first)
    _, next_end = month_range(next_first)
    _, next2_end = month_range(next2_first)

    return [
        ("(manual)", None, None),
        (f"Mês atual ({month_label(cur_first)})", cur_start, cur_end),
        (f"2 meses ({month_label(cur_first)} + {month_label(next_first)})", cur_start, next_end),
        (f"3 meses ({month_label(cur_first)} + {month_label(next2_first)})", cur_start, next2_end),
        (f"Mês anterior + atual ({month_label(prev_first)} + {month_label(cur_first)})", prev_start, cur_end),
    ]


def _api_error_message(e):
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


def _ss_setdefault(k, v):
    if k not in st.session_state:
        st.session_state[k] = v


def iso_or_none(d):
    if not d:
        return None
    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def parse_date_any(x, fallback):
    if x is None:
        return fallback
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, str) and x.strip():
        try:
            return datetime.fromisoformat(x.strip()).date()
        except Exception:
            pass
        try:
            return pd.to_datetime(x, errors="coerce").date()
        except Exception:
            pass
    return fallback


# ==========================================================
# Session defaults
# ==========================================================
today = date.today()
d0, d1 = month_range(today)
period_presets = make_period_presets(today)
period_labels = [p[0] for p in period_presets]

_ss_setdefault("pf_project", "Todos")
_ss_setdefault("pf_types", ["CAMPO", "RELATORIO", "ADMINISTRATIVO"])
_ss_setdefault("pf_people", [])
_ss_setdefault("pf_period_preset", period_labels[1] if len(period_labels) > 1 else "(manual)")
_ss_setdefault("pf_manual_start", d0)
_ss_setdefault("pf_manual_end", d1)
_ss_setdefault("pf_show_status", False)
_ss_setdefault("pf_show_cancelled", True)

# payload pendente (para aplicar ANTES dos widgets)
_ss_setdefault("pf_pending_preset_payload", None)


# ==========================================================
# DB helpers (projects + presets)
# ==========================================================
@st.cache_data(ttl=60)
def load_projects_codes():
    res = sb.table("projects").select("project_code").order("project_code").execute()
    rows = res.data or []
    codes = [safe_text(r.get("project_code")) for r in rows]
    codes = [c for c in codes if c]
    return ["Todos"] + sorted(set(codes))


@st.cache_data(ttl=30)
def load_presets():
    res = (
        sb.table("user_filter_presets")
        .select("name,payload,updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    rows = res.data or []
    preset_map = {}
    for r in rows:
        n = r.get("name")
        if n:
            preset_map[n] = r.get("payload") or {}
    names = list(preset_map.keys())
    return names, preset_map


def save_preset(name, payload):
    sb.table("user_filter_presets").upsert(
        {"name": name, "payload": payload},
        on_conflict="owner_id,name",
    ).execute()


def delete_preset(name):
    sb.table("user_filter_presets").delete().eq("name", name).execute()


# ==========================================================
# APLICA PRESET PENDENTE (antes de desenhar widgets)
# ==========================================================
if st.session_state.get("pf_pending_preset_payload"):
    payload = st.session_state["pf_pending_preset_payload"] or {}
    st.session_state["pf_pending_preset_payload"] = None  # consome

    allowed_keys = {
        "pf_project",
        "pf_types",
        "pf_people",
        "pf_period_preset",
        "pf_manual_start",
        "pf_manual_end",
        "pf_show_status",
        "pf_show_cancelled",
    }

    # aplica valores "seguros"
    for k, v in payload.items():
        if k not in allowed_keys:
            continue
        if k in ("pf_manual_start", "pf_manual_end"):
            continue  # trata abaixo
        st.session_state[k] = v

    st.session_state["pf_manual_start"] = parse_date_any(payload.get("pf_manual_start"), st.session_state["pf_manual_start"])
    st.session_state["pf_manual_end"] = parse_date_any(payload.get("pf_manual_end"), st.session_state["pf_manual_end"])

    # garante rerun limpo já com session_state aplicado
    st.rerun()


PORTFOLIO_COLS = "task_id,project_id,project_code,title,tipo_atividade,start_date,end_date,status,assignee_names"


@st.cache_data(ttl=30)
def fetch_portfolio(project_code, p_start_iso, p_end_iso, tipo_list, show_cancelled):
    q = sb.table("v_portfolio_tasks").select(PORTFOLIO_COLS)

    if project_code and project_code != "Todos":
        q = q.eq("project_code", project_code)

    q = q.lte("start_date", p_end_iso).gte("end_date", p_start_iso)

    if tipo_list:
        q = q.in_("tipo_atividade", list(tipo_list))

    if not show_cancelled:
        q = q.neq("status", "CANCELADA")

    res = q.execute()
    return pd.DataFrame(res.data or [])


# ==========================================================
# UI: filtros + presets
# ==========================================================
project_options = load_projects_codes()
preset_names, preset_map = load_presets()

if st.session_state["pf_project"] not in project_options:
    st.session_state["pf_project"] = "Todos"

types_all = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]

with filter_bar_start():
    top1, top2 = st.columns([2.3, 1.7])

    with top1:
        c_p, c_t = st.columns([1.1, 1.6])
        with c_p:
            st.selectbox("Projeto", project_options, key="pf_project")
        with c_t:
            st.multiselect("Tipo Atividade", types_all, key="pf_types")

        c_per1, c_per2, c_per3 = st.columns([1.7, 1.2, 1.2])
        with c_per1:
            st.selectbox("Atalho (período)", period_labels, key="pf_period_preset")
        with c_per2:
            st.toggle("Status na barra", key="pf_show_status")
        with c_per3:
            st.toggle("Mostrar canceladas", key="pf_show_cancelled")

    with top2:
        st.caption("Presets")
        preset_sel = st.selectbox("Carregar preset", ["—"] + preset_names, index=0, key="pf_preset_sel")
        b1, b2, b3 = st.columns([1, 1, 1])
        with b1:
            do_load = st.button("Carregar", use_container_width=True)
        with b2:
            do_delete = st.button("Excluir", use_container_width=True)
        with b3:
            do_save = st.button("Salvar", type="primary", use_container_width=True)

        st.text_input("Nome do preset", value="", placeholder="Ex: 2 meses + Todos + Campo", key="pf_preset_name")

# carregar preset -> salva payload pendente e rerun
if do_load and preset_sel != "—":
    st.session_state["pf_pending_preset_payload"] = preset_map.get(preset_sel) or {}
    st.rerun()

# excluir preset
if do_delete:
    if preset_sel == "—":
        st.warning("Selecione um preset para excluir.")
    else:
        try:
            delete_preset(preset_sel)
            load_presets.clear()
            st.success("Preset excluído.")
            st.rerun()
        except Exception as e:
            st.error("Erro ao excluir preset:")
            st.code(_api_error_message(e))

# período
chosen = [p for p in period_presets if p[0] == st.session_state["pf_period_preset"]][0]
if chosen[0] != "(manual)":
    p_start, p_end = chosen[1], chosen[2]
    st.caption(f"Período: **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**")
else:
    period = st.date_input(
        "Período (manual)",
        value=(st.session_state["pf_manual_start"], st.session_state["pf_manual_end"]),
        format="DD/MM/YYYY",
    )
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = d0, d1
    st.session_state["pf_manual_start"] = p_start
    st.session_state["pf_manual_end"] = p_end

# salvar preset (datas ISO)
if do_save:
    name = (st.session_state.get("pf_preset_name") or "").strip()
    if not name:
        st.warning("Informe um nome para o preset.")
    else:
        payload = {
            "pf_project": st.session_state["pf_project"],
            "pf_types": st.session_state["pf_types"],
            "pf_people": st.session_state["pf_people"],
            "pf_period_preset": st.session_state["pf_period_preset"],
            "pf_manual_start": iso_or_none(st.session_state["pf_manual_start"]),
            "pf_manual_end": iso_or_none(st.session_state["pf_manual_end"]),
            "pf_show_status": bool(st.session_state["pf_show_status"]),
            "pf_show_cancelled": bool(st.session_state["pf_show_cancelled"]),
        }
        try:
            save_preset(name, payload)
            load_presets.clear()
            st.success("Preset salvo.")
            st.rerun()
        except Exception as e:
            st.error("Erro ao salvar preset:")
            st.code(_api_error_message(e))


# ==========================================================
# Fetch otimizado + filtro pessoas
# ==========================================================
p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

sel_project = st.session_state["pf_project"]
sel_types = st.session_state["pf_types"] or []
show_cancelled = bool(st.session_state["pf_show_cancelled"])
show_status = bool(st.session_state["pf_show_status"])

df = fetch_portfolio(
    None if sel_project == "Todos" else sel_project,
    p_start.isoformat(),
    p_end.isoformat(),
    sel_types,
    show_cancelled,
)

if df.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

df["start_date"] = to_dt(df.get("start_date"))
df["end_date"] = to_dt(df.get("end_date"))
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"]).copy()
if df.empty:
    st.info("Registros sem datas válidas após normalização.")
    st.stop()

for col, default in [
    ("project_code", ""),
    ("title", ""),
    ("tipo_atividade", "CAMPO"),
    ("assignee_names", "Profissional"),
    ("status", ""),
]:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

df["status_norm"] = df["status"].apply(normalize_status)

df["label"] = (
    df["project_code"].astype(str).fillna("").str.strip()
    + " | "
    + df["title"].astype(str).fillna("").str.strip()
).str.strip(" |")

people_set = set()
for s in df["assignee_names"].astype(str).tolist():
    for p in split_people(s):
        people_set.add(p)
people_all = sorted(people_set)

people_opts = sorted(set(people_all) | set(st.session_state.get("pf_people") or []))
sel_people = st.multiselect(
    "Profissionais (refinar)",
    people_opts,
    default=st.session_state.get("pf_people") or [],
    key="pf_people",
)

f = df.copy()
if sel_people:
    patt = "|".join(re.escape(p.strip()) for p in sel_people if p and p.strip())
    if patt:
        f = f[f["assignee_names"].astype(str).str.contains(patt, regex=True, na=False)]

f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)].copy()
if f.empty:
    st.info("Sem tarefas após filtro de profissionais.")
    st.stop()

f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values(ascending=True)
    .index
    .tolist()
)

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
    f["bar_text"] = f.apply(
        lambda r: (("✖ " if safe_text(r.get("status_norm")) == "CANCELADA" else "") + safe_text(r.get("assignee_names"))).strip(),
        axis=1,
    )

f["tipo_plot"] = f["tipo_atividade"].astype(str)
f.loc[f["status_norm"] == "CANCELADA", "tipo_plot"] = "CANCELADA"

color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2F6DAE",
    "CANCELADA": "#9E9E9E",
}

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





