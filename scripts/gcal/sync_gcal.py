from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import create_client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# ENV / SETTINGS
# ============================================================
load_dotenv()


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v and v.strip() else default


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def to_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        # esperado: 'YYYY-MM-DD'
        return date.fromisoformat(v[:10])
    return None


@dataclass(frozen=True)
class Settings:
    # Supabase
    supabase_url: str = os.environ["SUPABASE_URL"]
    supabase_service_role_key: str = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    # Google (Domain Wide Delegation)
    google_sa_json: str = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    google_scopes: list[str] = field(
        default_factory=lambda: os.getenv(
            "GOOGLE_SCOPES",
            "https://www.googleapis.com/auth/calendar",
        ).split(",")
    )
    # Usuário “executor” (quem tem acesso às agendas corporativas)
    delegated_user_email: str = os.getenv("FALLBACK_OWNER_EMAIL", "").strip()

    # Sync
    sync_lookback_days: int = _env_int("SYNC_LOOKBACK_DAYS", 365)
    force_push_all: bool = _env_bool("FORCE_PUSH_ALL", False)

    # Opcional: cor por pessoa (por ID ou por nome)
    # Ex:
    # GCAL_COLOR_MAP=Felipe Normando:11,Yuri Martins:5
    gcal_color_map_raw: str = os.getenv("GCAL_COLOR_MAP", "").strip()


settings = Settings()


# ============================================================
# GOOGLE CALENDAR SERVICE (delegation)
# ============================================================
class CalendarService:
    def __init__(self, sa_json_path: str, scopes: list[str], delegated_user_email: str):
        if not delegated_user_email:
            raise RuntimeError("FALLBACK_OWNER_EMAIL (delegated user) não definido no .env")
        base = service_account.Credentials.from_service_account_file(sa_json_path, scopes=scopes)
        delegated = base.with_subject(delegated_user_email)
        self.svc = build("calendar", "v3", credentials=delegated, cache_discovery=False)


# ============================================================
# REPO (SUPABASE)
# ============================================================
class Repo:
    def __init__(self, sb):
        self.sb = sb
        self._people_name_cache: dict[str, str] = {}
        self._project_name_cache: dict[str, str] = {}
        self._calendar_by_person_cache: dict[str, str] = {}
        self._color_map: dict[str, str] = self._parse_color_map(settings.gcal_color_map_raw)

    @staticmethod
    def _parse_color_map(raw: str) -> dict[str, str]:
        """
        "Felipe Normando:11,Yuri Martins:5" -> {"Felipe Normando":"11",...}
        Também aceita person_id como chave.
        """
        out: dict[str, str] = {}
        if not raw:
            return out
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for p in parts:
            if ":" not in p:
                continue
            k, v = p.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k and v:
                out[k] = v
        return out

    # ---------- helpers safe execute ----------
    @staticmethod
    def _data(res) -> Any:
        # postgrest-py às vezes retorna None em 204; guardamos.
        if res is None:
            return None
        return getattr(res, "data", None)

    # ---------- people ----------
    def get_person_name(self, person_id: str) -> str:
        if person_id in self._people_name_cache:
            return self._people_name_cache[person_id]
        res = (
            self.sb.table("people")
            .select("name")
            .eq("id", person_id)
            .maybe_single()
            .execute()
        )
        data = self._data(res) or {}
        name = (data.get("name") or "").strip() or "(Sem responsável)"
        self._people_name_cache[person_id] = name
        return name

    # ---------- projects ----------
    def get_project_name(self, project_id: str) -> str:
        if project_id in self._project_name_cache:
            return self._project_name_cache[project_id]
        res = (
            self.sb.table("projects")
            .select("name")
            .eq("id", project_id)
            .maybe_single()
            .execute()
        )
        data = self._data(res) or {}
        name = (data.get("name") or "").strip() or "(Sem projeto)"
        self._project_name_cache[project_id] = name
        return name

    # ---------- calendar mapping ----------
    def load_calendar_by_person(self) -> dict[str, str]:
        if self._calendar_by_person_cache:
            return self._calendar_by_person_cache

        res = (
            self.sb.table("gcal_calendar_by_person")
            .select("person_id,calendar_id,active")
            .eq("active", True)
            .execute()
        )
        rows = self._data(res) or []
        m: dict[str, str] = {}
        for r in rows:
            pid = str(r.get("person_id") or "")
            cid = str(r.get("calendar_id") or "")
            if pid and cid:
                m[pid] = cid
        self._calendar_by_person_cache = m
        return m

    def get_calendar_for_person(self, person_id: str) -> Optional[str]:
        m = self.load_calendar_by_person()
        return m.get(person_id)

    # ---------- tasks ----------
    def list_tasks_changed_since(self, since_iso: str) -> list[dict[str, Any]]:
        # Campos mínimos
        res = (
            self.sb.table("tasks")
            .select("id,project_id,title,notes,assignee_id,status,start_date,end_date,updated_at")
            .gte("updated_at", since_iso)
            .execute()
        )
        return self._data(res) or []

    def list_tasks_in_window(self, window_days: int) -> list[dict[str, Any]]:
        # força uma janela por data (reduz volume e evita “tudo desde sempre”)
        start_min = (date.today() - timedelta(days=window_days)).isoformat()
        res = (
            self.sb.table("tasks")
            .select("id,project_id,title,notes,assignee_id,status,start_date,end_date,updated_at")
            .gte("end_date", start_min)  # pega o que ainda “encosta” na janela
            .execute()
        )
        return self._data(res) or []

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        res = self.sb.table("tasks").select("*").eq("id", task_id).maybe_single().execute()
        return self._data(res)

    def update_task(self, task_id: str, patch: dict[str, Any]) -> None:
        self.sb.table("tasks").update(patch).eq("id", task_id).execute()

    # ---------- task_calendar_links (map) ----------
    def get_link(self, task_id: str) -> Optional[dict[str, Any]]:
        res = (
            self.sb.table("task_calendar_links")
            .select("task_id,calendar_id,google_event_id,last_sync_hash,last_synced_at")
            .eq("task_id", task_id)
            .maybe_single()
            .execute()
        )
        return self._data(res)

    def upsert_link(self, payload: dict[str, Any]) -> None:
        # Tabela não tem PK explícita aqui, mas normalmente task_id é “unique”.
        # upsert funciona se existir constraint; se não existir, ainda funciona como insert em muitos setups.
        self.sb.table("task_calendar_links").upsert(payload).execute()

    def delete_link(self, task_id: str) -> None:
        self.sb.table("task_calendar_links").delete().eq("task_id", task_id).execute()

    # ---------- sync state ----------
    def get_sync_state(self, calendar_id: str) -> Optional[dict[str, Any]]:
        res = (
            self.sb.table("gcal_sync_state")
            .select("*")
            .eq("calendar_id", calendar_id)
            .maybe_single()
            .execute()
        )
        return self._data(res)

    def upsert_sync_state(self, calendar_id: str, sync_token: Optional[str]) -> None:
        payload = {
            "owner_email": settings.delegated_user_email,  # mantém compatibilidade
            "calendar_id": calendar_id,
            "sync_token": sync_token,
            "last_full_sync_at": iso(utcnow()),
            "updated_at": iso(utcnow()),
        }
        self.sb.table("gcal_sync_state").upsert(payload).execute()

    # ---------- colors ----------
    def get_event_color_id(self, assignee_id: str, assignee_name: str) -> Optional[str]:
        # prioridade: person_id, depois nome
        if assignee_id in self._color_map:
            return self._color_map[assignee_id]
        if assignee_name in self._color_map:
            return self._color_map[assignee_name]
        return None


# ============================================================
# EVENT BODY / HASH
# ============================================================
def compute_task_hash(task: dict[str, Any], project_name: str, assignee_name: str) -> str:
    # só o que altera o evento
    payload = "|".join(
        [
            str(task.get("id") or ""),
            str(task.get("status") or ""),
            project_name,
            str(task.get("title") or ""),
            assignee_name,
            str(task.get("notes") or ""),
            str(task.get("start_date") or ""),
            str(task.get("end_date") or ""),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def task_to_event_body(task: dict[str, Any], project_name: str, assignee_name: str, color_id: Optional[str]) -> dict[str, Any]:
    start_d = to_date(task.get("start_date"))
    end_d = to_date(task.get("end_date"))

    if not start_d or not end_d:
        # não deveria acontecer no seu schema (NOT NULL), mas por segurança:
        raise ValueError(f"Tarefa sem datas válidas: id={task.get('id')} start={task.get('start_date')} end={task.get('end_date')}")

    # all-day: end é exclusivo
    end_exclusive = end_d + timedelta(days=1)

    title = task.get("title") or "(Sem título)"
    summary = f"[{project_name}] {title} — {assignee_name}"

    body: dict[str, Any] = {
        "summary": summary,
        "description": (task.get("notes") or "").strip(),
        "start": {"date": start_d.isoformat()},
        "end": {"date": end_exclusive.isoformat()},
        "extendedProperties": {
            "private": {
                "opyta_task_id": str(task["id"]),
                "opyta_project_id": str(task.get("project_id") or ""),
                "opyta_assignee_id": str(task.get("assignee_id") or ""),
            }
        },
    }
    if color_id:
        body["colorId"] = color_id
    return body


def event_to_task_patch(ev: dict[str, Any]) -> dict[str, Any]:
    """
    Só atualiza datas/título/notes (não mexe em assignee).
    """
    start_date_str = (ev.get("start") or {}).get("date")
    end_date_str = (ev.get("end") or {}).get("date")

    patch: dict[str, Any] = {
        "notes": ev.get("description") or "",
        "updated_at": iso(utcnow()),
    }

    # ATENÇÃO: summary contém "[Projeto] ... — Responsável" (texto “de exibição”)
    # Para não bagunçar o seu título real da task, NÃO sobrescrevemos task.title com summary.
    # Se quiser sobrescrever, dá pra extrair, mas não recomendo.
    # patch["title"] = ...

    if start_date_str:
        patch["start_date"] = start_date_str

    if end_date_str:
        # end exclusivo -> volta 1 dia
        end_d = date.fromisoformat(end_date_str) - timedelta(days=1)
        patch["end_date"] = end_d.isoformat()

    return patch


# ============================================================
# SYNC: PUSH (Supabase -> Calendar)
# ============================================================
def push_tasks(repo: Repo, service, stats: dict[str, int]) -> None:
    if settings.force_push_all:
        tasks = repo.list_tasks_in_window(settings.sync_lookback_days)
    else:
        since = utcnow() - timedelta(days=settings.sync_lookback_days)
        tasks = repo.list_tasks_changed_since(iso(since))

    stats["push_tasks_seen"] += len(tasks)

    cal_map = repo.load_calendar_by_person()

    for t in tasks:
        task_id = str(t["id"])
        assignee_id = str(t["assignee_id"])
        project_id = str(t["project_id"])

        calendar_id = cal_map.get(assignee_id)
        if not calendar_id:
            stats["push_skipped_no_calendar"] += 1
            continue

        project_name = repo.get_project_name(project_id)
        assignee_name = repo.get_person_name(assignee_id)
        color_id = repo.get_event_color_id(assignee_id, assignee_name)

        # cancelamento → remove evento/link
        status_upper = str(t.get("status") or "").upper()
        is_cancelled = status_upper in {"CANCELADA", "CANCELADO", "CANCELLED"}

        link = repo.get_link(task_id)
        last_hash = (link or {}).get("last_sync_hash")

        task_hash = compute_task_hash(t, project_name, assignee_name)

        if (not is_cancelled) and (last_hash == task_hash):
            stats["push_skipped_not_changed"] += 1
            continue

        if is_cancelled:
            if link and link.get("google_event_id") and link.get("calendar_id"):
                try:
                    service.events().delete(
                        calendarId=link["calendar_id"],
                        eventId=link["google_event_id"],
                    ).execute()
                except HttpError:
                    pass
            repo.delete_link(task_id)
            stats["push_deleted_events"] += 1
            continue

        body = task_to_event_body(t, project_name, assignee_name, color_id)

        # Se já existe link, mas mudou o calendário (troca de responsável),
        # apagamos do calendário anterior (best effort) e recriamos no novo.
        if link and link.get("google_event_id") and link.get("calendar_id") and link["calendar_id"] != calendar_id:
            try:
                service.events().delete(calendarId=link["calendar_id"], eventId=link["google_event_id"]).execute()
            except HttpError:
                pass
            link = None

        if not link or not link.get("google_event_id"):
            # cria
            created = service.events().insert(calendarId=calendar_id, body=body).execute()
            repo.upsert_link(
                {
                    "task_id": task_id,
                    "calendar_id": calendar_id,
                    "google_event_id": created["id"],
                    "last_sync_hash": task_hash,
                    "last_synced_at": iso(utcnow()),
                }
            )
            stats["push_events_created"] += 1
            continue

        # atualiza (PATCH). Se 404, recria e atualiza o link.
        try:
            updated = service.events().patch(
                calendarId=calendar_id,
                eventId=link["google_event_id"],
                body=body,
            ).execute()
            repo.upsert_link(
                {
                    "task_id": task_id,
                    "calendar_id": calendar_id,
                    "google_event_id": updated["id"],
                    "last_sync_hash": task_hash,
                    "last_synced_at": iso(utcnow()),
                }
            )
            stats["push_events_updated"] += 1
        except HttpError as err:
            if err.resp is not None and err.resp.status == 404:
                created = service.events().insert(calendarId=calendar_id, body=body).execute()
                repo.upsert_link(
                    {
                        "task_id": task_id,
                        "calendar_id": calendar_id,
                        "google_event_id": created["id"],
                        "last_sync_hash": task_hash,
                        "last_synced_at": iso(utcnow()),
                    }
                )
                stats["push_recreated_after_404"] += 1
            else:
                raise


# ============================================================
# SYNC: PULL (Calendar -> Supabase)
# ============================================================
def pull_calendar(repo: Repo, service, calendar_id: str, stats: dict[str, int]) -> None:
    state = repo.get_sync_state(calendar_id)
    sync_token = state.get("sync_token") if state else None

    page_token: Optional[str] = None
    next_sync_token: Optional[str] = None
    time_min = iso(utcnow() - timedelta(days=settings.sync_lookback_days))

    while True:
        try:
            if sync_token:
                req = service.events().list(
                    calendarId=calendar_id,
                    syncToken=sync_token,
                    pageToken=page_token,
                    showDeleted=True,
                    maxResults=2500,
                    singleEvents=True,
                )
            else:
                req = service.events().list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    pageToken=page_token,
                    showDeleted=True,
                    maxResults=2500,
                    singleEvents=True,
                    orderBy="updated",
                )

            resp = req.execute()

        except HttpError as err:
            # syncToken expirou -> 410
            if err.resp is not None and err.resp.status == 410:
                stats["sync_token_reset"] += 1
                sync_token = None
                page_token = None
                continue
            raise

        items = resp.get("items", []) or []
        stats["pull_events_seen"] += len(items)

        for ev in items:
            apply_event(repo, service, calendar_id, ev, stats)

        page_token = resp.get("nextPageToken")
        if not page_token:
            next_sync_token = resp.get("nextSyncToken")
            break

    repo.upsert_sync_state(calendar_id, next_sync_token)


def apply_event(repo: Repo, service, calendar_id: str, ev: dict[str, Any], stats: dict[str, int]) -> None:
    event_id = ev.get("id")
    if not event_id:
        return

    ext = (ev.get("extendedProperties") or {}).get("private") or {}
    task_id = ext.get("opyta_task_id")

    # Se não for evento criado pelo Opyta, ignora
    if not task_id:
        stats["ignored_events_no_task_id"] += 1
        return

    if ev.get("status") == "cancelled":
        stats["deleted_events_seen"] += 1
        # opcional: marcar tarefa como cancelada
        repo.update_task(task_id, {"status": "CANCELADA", "updated_at": iso(utcnow())})
        # remove link se era esse
        link = repo.get_link(task_id)
        if link and link.get("google_event_id") == event_id:
            repo.delete_link(task_id)
        return

    task = repo.get_task(task_id)
    if not task:
        stats["ignored_events_task_missing"] += 1
        return

    # Atualiza apenas datas/notes (não mexe no title real)
    patch = event_to_task_patch(ev)
    repo.update_task(task_id, patch)
    stats["pull_tasks_updated"] += 1

    # Atualiza link para refletir o último evento
    repo.upsert_link(
        {
            "task_id": str(task_id),
            "calendar_id": calendar_id,
            "google_event_id": event_id,
            "last_sync_hash": (repo.get_link(str(task_id)) or {}).get("last_sync_hash"),
            "last_synced_at": iso(utcnow()),
        }
    )


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_role_key)
    repo = Repo(sb)

    gcal = CalendarService(settings.google_sa_json, settings.google_scopes, settings.delegated_user_email)
    service = gcal.svc

    stats: dict[str, int] = {
        "push_tasks_seen": 0,
        "push_events_created": 0,
        "push_events_updated": 0,
        "push_deleted_events": 0,
        "push_skipped_not_changed": 0,
        "push_skipped_no_calendar": 0,
        "push_recreated_after_404": 0,
        "pull_events_seen": 0,
        "pull_tasks_updated": 0,
        "ignored_events_no_task_id": 0,
        "ignored_events_task_missing": 0,
        "deleted_events_seen": 0,
        "sync_token_reset": 0,
    }

    # 1) PUSH: tasks -> calendars por pessoa
    push_tasks(repo, service, stats)

    # 2) PULL: calendários ativos -> tasks
    cal_map = repo.load_calendar_by_person()
    calendar_ids = sorted(set(cal_map.values()))
    for cal_id in calendar_ids:
        pull_calendar(repo, service, cal_id, stats)

    print("SYNC OK:", stats)


if __name__ == "__main__":
    main()
