import os
import sys
import re
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from supabase import create_client


# ===============================
# CONFIG
# ===============================
NS = {"p": "http://schemas.microsoft.com/project"}

STATUS_DEFAULT = "PLANEJADA"

# >>> IMPORTANTE:
# Seu banco NÃO aceita "FIRME" em date_confidence.
# Padrão recomendado: PLANEJADO (e você muda depois no app para CONFIRMADO/CANCELADO quando aplicável)
DATE_CONFIDENCE_DEFAULT = "PLANEJADO"

PLACEHOLDER_NAME = "Gestão de Projetos"

# Tipos aceitos (ajuste aqui se seu banco tiver check/enum diferente)
ALLOWED_TIPOS = {"CAMPO", "RELATORIO", "ADMINISTRATIVO"}

# Date confidence aceitos (ajuste se o seu CHECK tiver outros valores)
ALLOWED_DATE_CONF = {"PLANEJADO", "CONFIRMADO", "CANCELADO"}


# ===============================
# HELPERS
# ===============================
def clean(s):
    return (s or "").strip()


def parse_iso_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def dt_to_date_str(dt):
    if not dt:
        return None
    return dt.date().isoformat()


def normalize_tipo(group, task):
    """
    Regras simples:
    - Se o grupo (summary) tiver CAMPO -> CAMPO
    - Se tiver ADMIN -> ADMINISTRATIVO
    - Se tiver RELAT -> RELATORIO
    - fallback: RELATORIO
    """
    g = (group or "").upper()
    t = (task or "").upper()

    if "ADMIN" in g or "ADMIN" in t:
        return "ADMINISTRATIVO"

    if "CAMPO" in g or "CAMPO" in t:
        return "CAMPO"

    if "RELAT" in g or "RELAT" in t:
        return "RELATORIO"

    return "RELATORIO"


def normalize_date_confidence(x: str | None) -> str:
    """
    Normaliza QUALQUER coisa para algo que o CHECK do banco aceite.
    """
    v = (str(x or "").strip().upper())

    # valores legados / variações
    if v in ("FIRME", "CONFIRMADA", "CONFIRMADO"):
        return "CONFIRMADO"
    if v in ("PLANEJADA", "PLANEJADO", "PLANEJAMENTO", "ESTIMADO", "ESTIMADA", "A DEFINIR", "A_DEFINIR"):
        return "PLANEJADO"
    if v in ("CANCELADA", "CANCELADO", "CANCELAMENTO"):
        return "CANCELADO"

    # default seguro
    return DATE_CONFIDENCE_DEFAULT


def parse_project_code_and_name(title):
    title = clean(title)
    m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*-\s*(.+)$", title)
    if m:
        return m.group(1), m.group(2)
    parts = title.split()
    return (parts[0] if parts else "SEM_CODIGO"), title


# ===============================
# SUPABASE
# ===============================
def supabase_connect():
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não definidos no .env")

    return create_client(url, key)


# ===============================
# XML PARSER
# ===============================
def load_msproject_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    title = root.findtext("p:Title", "", NS)
    start = parse_iso_dt(root.findtext("p:StartDate", None, NS))
    end = parse_iso_dt(root.findtext("p:FinishDate", None, NS))

    tasks_el = root.find("p:Tasks", NS)
    resources_el = root.find("p:Resources", NS)
    assignments_el = root.find("p:Assignments", NS)

    # resources
    resources = {}
    if resources_el is not None:
        for r in resources_el.findall("p:Resource", NS):
            uid = r.findtext("p:UID", None, NS)
            name = clean(r.findtext("p:Name", None, NS))
            if uid and name:
                resources[uid] = name

    # assignments
    task_to_res = {}
    if assignments_el is not None:
        for a in assignments_el.findall("p:Assignment", NS):
            task_uid = a.findtext("p:TaskUID", None, NS)
            res_uid = a.findtext("p:ResourceUID", None, NS)
            if task_uid and res_uid and task_uid not in task_to_res:
                task_to_res[task_uid] = res_uid

    tasks = []
    current_group = None

    if tasks_el is not None:
        for t in tasks_el.findall("p:Task", NS):
            uid = t.findtext("p:UID", None, NS)
            name = clean(t.findtext("p:Name", "", NS))
            outline = t.findtext("p:OutlineLevel", None, NS)
            summary = t.findtext("p:Summary", "0", NS)

            start_t = parse_iso_dt(t.findtext("p:Start", None, NS))
            end_t = parse_iso_dt(t.findtext("p:Finish", None, NS))

            # grupos (summary nível 1)
            if summary == "1" and outline == "1":
                current_group = name
                continue

            if not uid or not name:
                continue

            # precisa de data para entrar no gantt
            if not start_t:
                continue

            res_uid = task_to_res.get(uid)
            assignee = resources.get(res_uid) if res_uid else None

            tipo = normalize_tipo(current_group, name)
            if tipo not in ALLOWED_TIPOS:
                tipo = "RELATORIO"

            tasks.append(
                {
                    "title": name,
                    "tipo_atividade": tipo,
                    "start_date": dt_to_date_str(start_t),
                    "end_date": dt_to_date_str(end_t or start_t),
                    "assignee_name": assignee,
                }
            )

    code, pname = parse_project_code_and_name(title)

    return {
        "project_code": code,
        "project_name": pname,
        "start": dt_to_date_str(start),
        "end": dt_to_date_str(end),
        "tasks": tasks,
        "people": set([t["assignee_name"] for t in tasks if t.get("assignee_name")]),
    }


# ===============================
# DB OPS
# ===============================
def upsert_people(sb, names):
    # inclui placeholder SEM duplicar
    names = sorted(set(clean(n) for n in names if clean(n)))
    if PLACEHOLDER_NAME not in names:
        names.append(PLACEHOLDER_NAME)

    res = sb.table("people").select("id,name").execute()
    existing = {r["name"]: r["id"] for r in (res.data or []) if r.get("name")}

    inserts = []
    for n in names:
        if n not in existing:
            is_ph = (n == PLACEHOLDER_NAME)
            role = "PLACEHOLDER" if is_ph else "BIOLOGO"
            inserts.append(
                {
                    "name": n,
                    "role": role,
                    "activity_type": None,
                    "is_placeholder": is_ph,
                    "active": True,
                }
            )

    if inserts:
        sb.table("people").insert(inserts).execute()

    res2 = sb.table("people").select("id,name").execute()
    return {r["name"]: r["id"] for r in (res2.data or []) if r.get("name")}


def upsert_project(sb, code, name, start, end):
    sb.table("projects").upsert(
        {
            "project_code": code,
            "name": name,
            "status": "ATIVO",
            "start_date": start,
            "end_date_planned": end,
        },
        on_conflict="project_code",
    ).execute()

    res = sb.table("projects").select("id").eq("project_code", code).limit(1).execute()
    return res.data[0]["id"]


# ===============================
# IMPORT
# ===============================
def import_file(sb, xml_path):
    data = load_msproject_xml(xml_path)
    print(f"\nIMPORTANDO {data['project_code']} ({len(data['tasks'])} tarefas)")

    people_map = upsert_people(sb, data["people"])
    project_id = upsert_project(sb, data["project_code"], data["project_name"], data["start"], data["end"])
    placeholder_id = people_map[PLACEHOLDER_NAME]

    res = sb.table("tasks").select("title").eq("project_id", project_id).execute()
    existing_titles = set(r["title"] for r in (res.data or []) if r.get("title"))

    inserts = []
    for t in data["tasks"]:
        if t["title"] in existing_titles:
            continue

        assignee_id = people_map.get(t.get("assignee_name"), placeholder_id)

        date_conf = normalize_date_confidence(DATE_CONFIDENCE_DEFAULT)
        if date_conf not in ALLOWED_DATE_CONF:
            date_conf = "PLANEJADO"

        payload = {
            "project_id": project_id,
            "title": t["title"],
            "tipo_atividade": t["tipo_atividade"],
            "assignee_id": assignee_id,
            "status": STATUS_DEFAULT,
            "start_date": t["start_date"],
            "end_date": t["end_date"],
            "date_confidence": date_conf,
        }

        inserts.append(payload)

    if inserts:
        sb.table("tasks").insert(inserts).execute()

    print(f"OK: {data['project_code']} | inseridas {len(inserts)} tarefas")


# ===============================
# MAIN
# ===============================
def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/import_msproject_xml_folder.py <pasta_xml>")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.exists():
        raise RuntimeError("Pasta não encontrada")

    sb = supabase_connect()

    files = sorted(folder.glob("*.xml"))
    ok = 0

    for f in files:
        import_file(sb, f)
        ok += 1

    print(f"\nFINALIZADO. Projetos importados: {ok}")


if __name__ == "__main__":
    main()
