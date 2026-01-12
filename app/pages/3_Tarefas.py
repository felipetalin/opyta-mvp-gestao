import os, sys
from datetime import date
import streamlit as st
from streamlit import column_config as cc
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from services.auth import require_login, inject_session  # noqa: E402

load_dotenv()
st.set_page_config(page_title="Tarefas", layout="wide")
st.title("Tarefas do Projeto")

require_login()
sb = inject_session()

@st.cache_data(ttl=30)
def load_projects():
    res = sb.table("projects").select("id,project_code,name").order("project_code").execute()
    return pd.DataFrame(res.data or [])

@st.cache_data(ttl=30)
def load_people():
    res = sb.table("people").select("id,name,active,is_placeholder").order("name").execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty:
        df = df[df["active"] == True]  # noqa: E712
    return df

@st.cache_data(ttl=30)
def load_tasks(project_id: str):
    res = (
        sb.table("tasks")
        .select("*")
        .eq("project_id", project_id)
        .order("start_date", desc=False)
        .order("end_date", desc=False)
        .order("created_at", desc=False)
        .execute()
    )
    return pd.DataFrame(res.data or [])

proj_df = load_projects()
if proj_df.empty:
    st.warning("Sem projetos. Cadastre um projeto primeiro.")
    st.stop()

people_df = load_people()

# ----- selecionar projeto
proj_df["label"] = proj_df["project_code"].astype(str) + " | " + proj_df["name"].astype(str)
proj_label = st.selectbox("Projeto", proj_df["label"].tolist(), index=0)
proj_row = proj_df[proj_df["label"] == proj_label].iloc[0]
project_id = str(proj_row["id"])
project_code = proj_row["project_code"]

st.caption(f"Projeto selecionado: **{project_code}**")

# ----- responsaveis (para cadastro e edição)
people_options = ["(A Definir / Gestao de Projetos)"]
people_map = {}
id_to_name = {}
if not people_df.empty:
    for _, r in people_df.iterrows():
        people_options.append(r["name"])
        people_map[r["name"]] = str(r["id"])
        id_to_name[str(r["id"])] = r["name"]

# =========================
# 1) NOVA TAREFA (EM CIMA)
# =========================
st.subheader("Nova tarefa")

with st.form("task_form", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns([2.6, 1.3, 1.3, 1.3])
    with c1:
        title = st.text_input("Título", placeholder="Campanha 03 - Jan/26")
    with c2:
        tipo = st.selectbox("Tipo Atividade", ["CAMPO","RELATORIO"])
    with c3:
        status = st.selectbox("Status", ["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"], index=0)
    with c4:
        priority = st.selectbox("Prioridade", ["BAIXA","MEDIA","ALTA"], index=1)

    c5, c6, c7, c8 = st.columns([2.0, 1.4, 1.3, 1.3])
    with c5:
        assignee_label = st.selectbox("Responsável", people_options, index=0)
    with c6:
        date_conf = st.selectbox("Confiança da data", ["FIRME","ESTIMADA"], index=0)
    with c7:
        start_date = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")
    with c8:
        end_date = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")

    progress_pct = st.slider("Progresso (%)", 0, 100, 0, 5)
    notes = st.text_area("Observação", height=80)

    submitted = st.form_submit_button("Salvar tarefa")

if submitted:
    if not (title or "").strip():
        st.error("Título é obrigatório.")
        st.stop()
    if end_date and start_date and end_date < start_date:
        st.error("Fim não pode ser menor que Início.")
        st.stop()

    assignee_id = None
    if assignee_label in people_map:
        assignee_id = people_map[assignee_label]

    payload = {
        "project_id": project_id,
        "title": title.strip(),
        "tipo_atividade": tipo,
        "assignee_id": assignee_id,  # pode ser None
        "status": status,
        "start_date": str(start_date) if start_date else None,
        "end_date": str(end_date) if end_date else None,
        "date_confidence": date_conf,
        "priority": priority,
        "progress_pct": int(progress_pct),
        "notes": (notes or "").strip() or None,
    }

    sb.table("tasks").insert(payload).execute()
    st.success("Tarefa criada. Já deve aparecer no Portfólio (Gantt).")
    st.cache_data.clear()
    st.rerun()

st.divider()

# =========================
# 2) LISTA + FILTROS
# =========================
from streamlit import column_config as cc
import pandas as pd
import streamlit as st

st.subheader("Lista de tarefas")

tasks_df = load_tasks(project_id)
if tasks_df.empty:
    st.info("Sem tarefas ainda nesse projeto.")
    st.stop()

view = tasks_df.copy()
view["responsavel"] = view["assignee_id"].astype(str).map(id_to_name).fillna("Gestao de Projetos / A Definir")
view["start_dt"] = pd.to_datetime(view["start_date"], errors="coerce")
view["end_dt"] = pd.to_datetime(view["end_date"], errors="coerce")

# filtros
fc1, fc2, fc3 = st.columns([1.4, 1.8, 1.8])
with fc1:
    f_tipo = st.multiselect("Filtrar Tipo", ["CAMPO","RELATORIO"], default=["CAMPO","RELATORIO"])
with fc2:
    f_resp = st.multiselect(
        "Filtrar Responsável",
        sorted(view["responsavel"].unique().tolist()),
        default=sorted(view["responsavel"].unique().tolist()),
    )
with fc3:
    f_status = st.multiselect(
        "Filtrar Status",
        ["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"],
        default=["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"],
    )

filtered = view[
    view["tipo_atividade"].isin(f_tipo)
    & view["responsavel"].isin(f_resp)
    & view["status"].isin(f_status)
].sort_values(["start_dt","end_dt","created_at"], ascending=[True, True, True])

# dataframe do editor: SEM prioridade e SEM %concluída
editor_df = filtered.copy()
editor_df["start_date"] = pd.to_datetime(editor_df["start_date"], errors="coerce").dt.date
editor_df["end_date"] = pd.to_datetime(editor_df["end_date"], errors="coerce").dt.date

show_cols = [
    "id",
    "title",
    "tipo_atividade",
    "responsavel",
    "start_date",
    "end_date",
    "date_confidence",
    "status",
    "notes",
]
show_cols = [c for c in show_cols if c in editor_df.columns]
editor_df = editor_df[show_cols].copy()

st.caption("Edição inline: **Responsável, Início, Fim e Status**. Depois clique em **Salvar alterações**.")

edited_df = st.data_editor(
    editor_df,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "id": cc.TextColumn("id", disabled=True),
        "title": cc.TextColumn("Tarefa", disabled=True),
        "tipo_atividade": cc.TextColumn("Tipo", disabled=True),
        "notes": cc.TextColumn("Obs.", disabled=True),
        "date_confidence": cc.TextColumn("Confiança", disabled=True),

        # EDITÁVEIS:
        "responsavel": cc.SelectboxColumn(
            "Responsável",
            options=sorted(list(set(people_options))),  # inclui o placeholder
            required=True,
        ),
        "start_date": cc.DateColumn("Início", format="DD/MM/YYYY", required=True),
        "end_date": cc.DateColumn("Fim", format="DD/MM/YYYY", required=True),
        "status": cc.SelectboxColumn(
            "Status",
            options=["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"],
            required=True,
        ),
    },
    disabled=["id", "title", "tipo_atividade", "notes", "date_confidence"],
    key="tasks_editor_inline",
)

save_inline = st.button("Salvar alterações", type="primary")

if save_inline:
    # original vs novo somente nos campos editáveis
    orig = editor_df.set_index("id")[["responsavel","start_date","end_date","status"]].copy()
    new = edited_df.set_index("id")[["responsavel","start_date","end_date","status"]].copy()

    diffs = []
    errors = []

    for tid in new.index:
        o = orig.loc[tid]
        n = new.loc[tid]

        changed = (
            str(o["responsavel"]) != str(n["responsavel"])
            or o["start_date"] != n["start_date"]
            or o["end_date"] != n["end_date"]
            or str(o["status"]) != str(n["status"])
        )
        if not changed:
            continue

        # validação: fim >= início
        if n["start_date"] and n["end_date"] and n["end_date"] < n["start_date"]:
            errors.append(f"Tarefa '{tid}': Fim menor que Início.")
            continue

        diffs.append((tid, n["responsavel"], n["start_date"], n["end_date"], n["status"]))

    if errors:
        st.error("Erros de validação:\n- " + "\n- ".join(errors))
        st.stop()

    if not diffs:
        st.info("Nenhuma alteração para salvar.")
    else:
        # aplica updates 1 a 1
        for tid, resp_label, sdt, edt, status in diffs:
            # converte responsável (nome -> assignee_id)
            assignee_id = None
            if resp_label and resp_label in people_map:
                assignee_id = people_map[resp_label]  # uuid

            upd = {
                "assignee_id": assignee_id,  # None = placeholder
                "start_date": str(sdt) if sdt else None,
                "end_date": str(edt) if edt else None,
                "status": str(status),
            }
            sb.table("tasks").update(upd).eq("id", str(tid)).execute()

        st.success(f"Salvo: {len(diffs)} tarefa(s) atualizada(s).")
        st.cache_data.clear()
        st.rerun()

# =========================
# 3) EDITAR / EXCLUIR (seleciona 1 tarefa)
# =========================
st.subheader("Editar tarefa")

# opções de seleção (bem claras)
filtered = filtered.copy()
filtered["pick"] = (
    filtered["title"].astype(str)
    + "  |  "
    + filtered["tipo_atividade"].astype(str)
    + "  |  "
    + filtered["start_date"].astype(str)
    + " → "
    + filtered["end_date"].astype(str)
)

pick_map = dict(zip(filtered["pick"].tolist(), filtered["id"].astype(str).tolist()))
pick_label = st.selectbox("Selecione a tarefa", filtered["pick"].tolist())
task_id = pick_map[pick_label]

# carrega a linha atual (do dataframe já filtrado)
row = filtered[filtered["id"].astype(str) == str(task_id)].iloc[0].to_dict()

# defaults do responsável para edição
current_assignee_id = str(row.get("assignee_id")) if row.get("assignee_id") else None
current_assignee_label = "(A Definir / Gestao de Projetos)"
if current_assignee_id and current_assignee_id in id_to_name:
    current_assignee_label = id_to_name[current_assignee_id]

# índice default no selectbox
assignee_idx = 0
if current_assignee_label in people_options:
    assignee_idx = people_options.index(current_assignee_label)

with st.form("edit_task_form"):
    e1, e2, e3, e4 = st.columns([2.6, 1.3, 1.3, 1.3])
    with e1:
        e_title = st.text_input("Título", value=row.get("title",""))
    with e2:
        e_tipo = st.selectbox("Tipo Atividade", ["CAMPO","RELATORIO"], index=["CAMPO","RELATORIO"].index(row.get("tipo_atividade","CAMPO")))
    with e3:
        e_status = st.selectbox("Status", ["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"],
                                index=["PLANEJADA","EM_ANDAMENTO","CONCLUIDA","CANCELADA"].index(row.get("status","PLANEJADA")))
    with e4:
        e_priority = st.selectbox("Prioridade", ["BAIXA","MEDIA","ALTA"],
                                  index=["BAIXA","MEDIA","ALTA"].index(row.get("priority","MEDIA")))

    e5, e6, e7, e8 = st.columns([2.0, 1.4, 1.3, 1.3])
    with e5:
        e_assignee_label = st.selectbox("Responsável", people_options, index=assignee_idx)
    with e6:
        e_date_conf = st.selectbox("Confiança da data", ["FIRME","ESTIMADA"], index=["FIRME","ESTIMADA"].index(row.get("date_confidence","FIRME")))
    with e7:
        e_start = st.date_input("Início", value=pd.to_datetime(row.get("start_date")) if row.get("start_date") else date.today(), format="DD/MM/YYYY")
    with e8:
        e_end = st.date_input("Fim", value=pd.to_datetime(row.get("end_date")) if row.get("end_date") else date.today(), format="DD/MM/YYYY")

    e_progress = st.slider("Progresso (%)", 0, 100, int(row.get("progress_pct") or 0), 5)
    e_notes = st.text_area("Observação", value=row.get("notes") or "", height=80)

    save_btn = st.form_submit_button("Salvar alterações")

if save_btn:
    if not (e_title or "").strip():
        st.error("Título é obrigatório.")
        st.stop()
    if e_end and e_start and e_end < e_start:
        st.error("Fim não pode ser menor que Início.")
        st.stop()

    e_assignee_id = None
    if e_assignee_label in people_map:
        e_assignee_id = people_map[e_assignee_label]

    upd = {
        "title": e_title.strip(),
        "tipo_atividade": e_tipo,
        "assignee_id": e_assignee_id,  # pode ser None
        "status": e_status,
        "start_date": str(e_start) if e_start else None,
        "end_date": str(e_end) if e_end else None,
        "date_confidence": e_date_conf,
        "priority": e_priority,
        "progress_pct": int(e_progress),
        "notes": (e_notes or "").strip() or None,
    }

    sb.table("tasks").update(upd).eq("id", str(task_id)).execute()
    st.success("Tarefa atualizada. O Gantt refletirá automaticamente.")
    st.cache_data.clear()
    st.rerun()

with st.expander("Excluir tarefa (cuidado)"):
    st.warning("Exclusão é permanente.")
    if st.button("Excluir esta tarefa"):
        sb.table("tasks").delete().eq("id", str(task_id)).execute()
        st.success("Tarefa excluída.")
        st.cache_data.clear()
        st.rerun()
