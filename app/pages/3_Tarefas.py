import streamlit as st
import pandas as pd
from datetime import date
from dotenv import load_dotenv

# Ajuste conforme seu projeto:
# - se você já tem um get_supabase() no services/supabase_client.py, use ele.
try:
    from services.supabase_client import get_supabase  # type: ignore
except Exception:
    get_supabase = None

try:
    from supabase import create_client
except Exception:
    create_client = None  # noqa


st.set_page_config(page_title="Tarefas", layout="wide")

load_dotenv()


# ----------------------------
# Supabase client
# ----------------------------
def _fallback_supabase():
    import os
    if create_client is None:
        raise RuntimeError("Pacote supabase não instalado. Verifique requirements.txt")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY (env/secrets).")
    return create_client(url, key)


def sb():
    if get_supabase:
        return get_supabase()
    return _fallback_supabase()


# ----------------------------
# Helpers
# ----------------------------
CONF_VALUES = ["ESTIMADO", "CONFIRMADO"]
TIPO_VALUES = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
STATUS_VALUES = ["ESTIMADO", "PLANEJADA", "CONFIRMADA", "CANCELADA"]


def _to_date(v):
    """Converte string/None para date (ou None)."""
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_people():
    res = sb().table("people").select("id,name,active,is_placeholder,role").order("name").execute()
    rows = res.data or []
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def fetch_projects():
    res = sb().table("projects").select("id,project_code,name,client,status").order("project_code").execute()
    rows = res.data or []
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def fetch_tasks():
    # Pega tudo do tasks + join “manual” em pandas (pra manter simples e estável)
    res = sb().table("tasks").select(
        "id,project_id,title,tipo_atividade,assignee_id,status,start_date,end_date,date_confidence,notes,updated_at"
    ).execute()
    rows = res.data or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.rename(columns={"id": "task_id"})
    df["start_date"] = df["start_date"].apply(_to_date)
    df["end_date"] = df["end_date"].apply(_to_date)
    df["date_confidence"] = df["date_confidence"].fillna("ESTIMADO").astype(str).str.upper().str.strip()
    return df


def get_placeholder_person_id(df_people: pd.DataFrame) -> str:
    # Preferência: is_placeholder True
    if not df_people.empty:
        ph = df_people[df_people["is_placeholder"] == True]  # noqa: E712
        if not ph.empty:
            # se tiver “Gestão de Projetos”, usa ele
            gp = ph[ph["name"].str.upper().str.contains("GEST", na=False)]
            if not gp.empty:
                return gp.iloc[0]["id"]
            return ph.iloc[0]["id"]

        # fallback: primeiro ativo
        act = df_people[df_people["active"] == True]  # noqa: E712
        if not act.empty:
            return act.iloc[0]["id"]

    raise RuntimeError("Não encontrei nenhum registro válido em people.")


def upsert_task_update(task_id: str, payload: dict):
    # Remove campos vazios perigosos
    payload = {k: v for k, v in payload.items() if k is not None}
    sb().table("tasks").update(payload).eq("id", task_id).execute()


# ----------------------------
# UI
# ----------------------------
st.title("Tarefas")

df_people = fetch_people()
df_projects = fetch_projects()
df_tasks = fetch_tasks()

if df_people.empty:
    st.error("Tabela people está vazia. Crie as pessoas (incluindo placeholders) antes.")
    st.stop()

placeholder_id = get_placeholder_person_id(df_people)

# Mapa pessoa
people_id_to_name = dict(zip(df_people["id"], df_people["name"]))
people_name_to_id = dict(zip(df_people["name"], df_people["id"]))

# Opções de responsáveis
people_options = df_people["name"].tolist()

# Projetos: exibir como "CODE - Nome"
proj_label = {}
if not df_projects.empty:
    for _, r in df_projects.iterrows():
        code = (r.get("project_code") or "").strip()
        name = (r.get("name") or "").strip()
        proj_label[r["id"]] = f"{code} - {name}" if code else name
project_options = ["(Todos)"] + [proj_label[k] for k in proj_label.keys()]
project_label_to_id = {v: k for k, v in proj_label.items()}

# ----------------------------
# Bloco: Criar nova tarefa
# ----------------------------
st.subheader("Nova tarefa")

col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

with col1:
    proj_sel = st.selectbox("Projeto", project_options, index=0 if project_options else 0)
with col2:
    tipo_new = st.selectbox("Tipo de atividade", TIPO_VALUES, index=0)
with col3:
    conf_new = st.selectbox("Confiança da data", CONF_VALUES, index=0)
with col4:
    status_new = st.selectbox("Status", STATUS_VALUES, index=1)  # default PLANEJADA

title_new = st.text_input("Título da tarefa")

c5, c6, c7, c8 = st.columns([2, 2, 2, 4])
with c5:
    assignee_new_name = st.selectbox("Responsável", people_options, index=0)
with c6:
    start_new = st.date_input("Início", value=date.today())
with c7:
    end_new = st.date_input("Fim", value=date.today())
with c8:
    notes_new = st.text_area("Observações", height=68)

btn_new = st.button("➕ Criar tarefa", type="primary")

if btn_new:
    if proj_sel == "(Todos)" or proj_sel not in project_label_to_id:
        st.error("Selecione um projeto para criar a tarefa.")
    elif not title_new.strip():
        st.error("Informe o título da tarefa.")
    else:
        project_id = project_label_to_id[proj_sel]
        assignee_id = people_name_to_id.get(assignee_new_name, placeholder_id)

        payload = {
            "project_id": project_id,
            "title": title_new.strip(),
            "tipo_atividade": tipo_new,
            "assignee_id": assignee_id,  # NOT NULL
            "status": status_new,
            "start_date": start_new.isoformat(),
            "end_date": end_new.isoformat(),
            "date_confidence": conf_new,
            "notes": (notes_new.strip() or None),
        }

        try:
            sb().table("tasks").insert(payload).execute()
            st.success("Tarefa criada!")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Falha ao criar tarefa: {e}")

st.divider()

# ----------------------------
# Filtros (lista)
# ----------------------------
st.subheader("Lista de tarefas")

f1, f2, f3, f4 = st.columns([3, 2, 2, 2])

with f1:
    proj_filter = st.selectbox("Filtro: Projeto", project_options, index=0)
with f2:
    prof_filter = st.selectbox("Filtro: Profissional", ["(Todos)"] + people_options, index=0)
with f3:
    tipo_filter = st.selectbox("Filtro: Atividade", ["(Todos)"] + TIPO_VALUES, index=0)
with f4:
    conf_filter = st.selectbox("Filtro: Confiança da data", ["(Todos)"] + CONF_VALUES, index=0)

df = df_tasks.copy()
if df.empty:
    st.info("Ainda não há tarefas cadastradas.")
    st.stop()

# Join para mostrar nomes/labels
df["assignee_name"] = df["assignee_id"].map(people_id_to_name).fillna("Gestão de Projetos")
df["project_label"] = df["project_id"].map(proj_label).fillna("(sem projeto)")

# Aplicar filtros
if proj_filter != "(Todos)":
    pid = project_label_to_id.get(proj_filter)
    if pid:
        df = df[df["project_id"] == pid]

if prof_filter != "(Todos)":
    df = df[df["assignee_name"] == prof_filter]

if tipo_filter != "(Todos)":
    df = df[df["tipo_atividade"].fillna("").str.upper() == tipo_filter]

if conf_filter != "(Todos)":
    df = df[df["date_confidence"].fillna("").str.upper() == conf_filter]

# Ordenação cronológica (crítica)
df = df.sort_values(["start_date", "end_date", "project_label", "title"], ascending=[True, True, True, True])

# ----------------------------
# Caixinha de edição oculta (padrão Projetos)
# ----------------------------
with st.expander("✏️ Editar tarefa existente (abrir somente quando necessário)", expanded=False):
    q = st.text_input("Buscar tarefa (por título)", "")
    dfx = df.copy()
    if q.strip():
        dfx = dfx[dfx["title"].str.contains(q, case=False, na=False)]

    # Limita opções para ficar leve
    dfx = dfx.head(80)

    options = dfx[["task_id", "project_label", "title"]].values.tolist()
    if not options:
        st.info("Nenhuma tarefa encontrada com esse filtro.")
    else:
        sel = st.selectbox(
            "Selecione a tarefa",
            options,
            format_func=lambda x: f"{x[1]} | {x[2]}",
        )
        task_id = sel[0]
        row = df[df["task_id"] == task_id].iloc[0]

        cA, cB, cC, cD = st.columns([3, 2, 2, 2])
        with cA:
            title_e = st.text_input("Título", value=row["title"])
        with cB:
            tipo_e = st.selectbox(
                "Tipo de atividade",
                TIPO_VALUES,
                index=TIPO_VALUES.index((row["tipo_atividade"] or "RELATORIO").upper())
                if (row["tipo_atividade"] or "").upper() in TIPO_VALUES else 1
            )
        with cC:
            status_e = st.selectbox(
                "Status",
                STATUS_VALUES,
                index=STATUS_VALUES.index((row["status"] or "PLANEJADA").upper())
                if (row["status"] or "").upper() in STATUS_VALUES else 1
            )
        with cD:
            conf_e = st.selectbox(
                "Confiança da data",
                CONF_VALUES,
                index=1 if str(row["date_confidence"]).upper() == "CONFIRMADO" else 0
            )

        cE, cF, cG = st.columns([2, 2, 2])
        with cE:
            assignee_e_name = st.selectbox(
                "Responsável",
                people_options,
                index=people_options.index(row["assignee_name"]) if row["assignee_name"] in people_options else 0
            )
        with cF:
            start_e = st.date_input("Início", value=row["start_date"] or date.today())
        with cG:
            end_e = st.date_input("Fim", value=row["end_date"] or (row["start_date"] or date.today()))

        notes_e = st.text_area("Observações", value=row.get("notes") or "", height=90)

        if st.button("💾 Salvar edição", type="primary"):
            assignee_e_id = people_name_to_id.get(assignee_e_name, placeholder_id)

            payload = {
                "title": title_e.strip(),
                "tipo_atividade": tipo_e,
                "assignee_id": assignee_e_id,
                "status": status_e,
                "date_confidence": conf_e,
                "start_date": start_e.isoformat(),
                "end_date": end_e.isoformat(),
                "notes": notes_e.strip() or None,
            }

            try:
                upsert_task_update(task_id, payload)
                st.success("Tarefa atualizada!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Falha ao atualizar tarefa: {e}")

st.divider()

# ----------------------------
# Tabela principal (edição inline)
# ----------------------------
st.caption("Edição inline para ajustes rápidos (responsável, datas, status, confiança, tipo).")

df_ui = df[[
    "task_id",
    "project_label",
    "title",
    "tipo_atividade",
    "assignee_name",
    "status",
    "date_confidence",
    "start_date",
    "end_date",
    "notes",
]].copy()

# Data editor
edited = st.data_editor(
    df_ui,
    use_container_width=True,
    hide_index=True,
    disabled=["task_id", "project_label"],  # IDs não editáveis
    column_config={
        "project_label": st.column_config.TextColumn("Projeto", width="medium"),
        "title": st.column_config.TextColumn("Tarefa", width="large"),
        "tipo_atividade": st.column_config.SelectboxColumn("Atividade", options=TIPO_VALUES, width="small"),
        "assignee_name": st.column_config.SelectboxColumn("Responsável", options=people_options, width="small"),
        "status": st.column_config.SelectboxColumn("Status", options=STATUS_VALUES, width="small"),
        "date_confidence": st.column_config.SelectboxColumn("Confiança", options=CONF_VALUES, width="small"),
        "start_date": st.column_config.DateColumn("Início", width="small"),
        "end_date": st.column_config.DateColumn("Fim", width="small"),
        "notes": st.column_config.TextColumn("Obs.", width="large"),
    },
)

save_inline = st.button("💾 Salvar alterações da tabela", type="primary")

if save_inline:
    # comparar com original e salvar só o que mudou
    base = df_ui.set_index("task_id")
    new = edited.set_index("task_id")

    changed_ids = []
    for tid in new.index:
        if tid not in base.index:
            continue
        if not new.loc[tid].equals(base.loc[tid]):
            changed_ids.append(tid)

    if not changed_ids:
        st.info("Nenhuma alteração detectada.")
    else:
        ok = 0
        fail = 0
        for tid in changed_ids:
            r = new.loc[tid]

            assignee_id = people_name_to_id.get(r["assignee_name"], placeholder_id)

            payload = {
                "title": str(r["title"]).strip(),
                "tipo_atividade": str(r["tipo_atividade"]).upper(),
                "assignee_id": assignee_id,
                "status": str(r["status"]).upper(),
                "date_confidence": str(r["date_confidence"]).upper(),
                "start_date": (_to_date(r["start_date"]) or date.today()).isoformat(),
                "end_date": (_to_date(r["end_date"]) or (_to_date(r["start_date"]) or date.today())).isoformat(),
                "notes": (str(r["notes"]).strip() if pd.notna(r["notes"]) else None) or None,
            }

            try:
                upsert_task_update(tid, payload)
                ok += 1
            except Exception as e:
                fail += 1
                st.error(f"Falha ao salvar tarefa {tid}: {e}")

        st.success(f"Salvo: {ok} | Falhas: {fail}")
        st.cache_data.clear()
        st.rerun()
