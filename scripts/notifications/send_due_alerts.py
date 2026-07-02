from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Iterable

from dotenv import load_dotenv
from supabase import create_client


SOURCE_LABELS = {
    "gantt": "Gantt",
    "laboratorio": "Laboratorio",
    "produtos": "Produtos",
    "reembolsos": "Reembolsos",
}

TERMINAL_TASK_STATUSES = {
    "CANCELADA",
    "CANCELADO",
    "CANCELLED",
    "CONCLUIDA",
    "CONCLUIDO",
    "FINALIZADA",
    "FINALIZADO",
}
TERMINAL_LAB_STATUSES = {"CONCLUIDO", "LAUDO_RECEBIDO"}
TERMINAL_PRODUCT_STATUSES = {"ENTREGUE", "FATURADO", "CONCLUIDO"}
TERMINAL_REIMBURSEMENT_STATUSES = {"PAGO", "GLOSADO"}


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    email: str
    active: bool = True


@dataclass(frozen=True)
class NotificationCandidate:
    source: str
    source_id: str
    title: str
    project_code: str
    project_name: str
    responsible_name: str
    recipient_email: str
    due_date: date
    alert_type: str
    days_until_due: int
    detail: str = ""
    run_date: date | None = None

    @property
    def notification_key(self) -> str:
        day_token = self.due_date.isoformat()
        if self.alert_type == "OVERDUE":
            # Overdue items can be sent once per day until resolved.
            day_token = (self.run_date or date.today()).isoformat()
        return (
            f"{self.source}:{self.source_id}:{self.recipient_email}:"
            f"{self.alert_type}:{self.days_until_due}:{day_token}"
        )


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if text in {"", "None", "nan", "NaT"}:
        return default
    return text


def norm(value: Any) -> str:
    return clean_text(value).upper().strip()


def to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = clean_text(value)
    if not text:
        return None
    try:
        if "/" in text:
            return datetime.strptime(text[:10], "%d/%m/%Y").date()
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    return int(value)


def parse_csv(value: str | None, default: Iterable[str]) -> list[str]:
    if not value:
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_email_list(value: str | None) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for raw in parse_csv(value, []):
        email = raw.strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        emails.append(email)
        seen.add(email)
    return emails


def parse_windows(value: str | None) -> set[int]:
    raw = parse_csv(value, ["0", "1", "3", "7"])
    return {int(part) for part in raw if part.strip()}


def alert_for_due(due_date: date, today: date, windows: set[int]) -> tuple[str, int] | None:
    days = (due_date - today).days
    if days < 0:
        return "OVERDUE", days
    if days in windows:
        if days == 0:
            return "TODAY", days
        return "DAYS_BEFORE", days
    return None


def brl(value: Any) -> str:
    try:
        amount = float(value or 0)
    except Exception:
        amount = 0.0
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def chunked(items: list[Any], size: int = 100) -> Iterable[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def safe_data(response: Any) -> list[dict[str, Any]]:
    return list(getattr(response, "data", None) or [])


def load_people(sb) -> tuple[dict[str, Person], dict[str, Person]]:
    rows = safe_data(sb.table("people").select("id,name,email,active").execute())
    by_id: dict[str, Person] = {}
    by_name: dict[str, Person] = {}
    for row in rows:
        person = Person(
            id=clean_text(row.get("id")),
            name=clean_text(row.get("name")),
            email=clean_text(row.get("email")).lower(),
            active=bool(row.get("active", True)),
        )
        if person.id:
            by_id[person.id] = person
        if person.name:
            by_name[person.name.strip().lower()] = person
    return by_id, by_name


def load_projects(sb) -> dict[str, dict[str, str]]:
    rows = safe_data(sb.table("projects").select("id,project_code,name").execute())
    return {
        clean_text(row.get("id")): {
            "project_code": clean_text(row.get("project_code")),
            "project_name": clean_text(row.get("name")),
        }
        for row in rows
        if clean_text(row.get("id"))
    }


def person_for_name(people_by_name: dict[str, Person], names: str) -> Person | None:
    first = clean_text(names).split("+")[0].strip()
    if not first:
        return None
    return people_by_name.get(first.lower())


def add_candidate(
    candidates: list[NotificationCandidate],
    missing_recipients: list[dict[str, str]],
    *,
    source: str,
    source_id: str,
    title: str,
    project_code: str,
    project_name: str,
    responsible: Person | None,
    fallback_recipient: str,
    forced_recipients: list[str],
    due_date: date | None,
    today: date,
    windows: set[int],
    detail: str = "",
) -> None:
    if not source_id or due_date is None:
        return
    alert = alert_for_due(due_date, today, windows)
    if alert is None:
        return
    alert_type, days_until_due = alert

    responsible_name = responsible.name if responsible else ""
    recipients = forced_recipients or [((responsible.email if responsible else "") or fallback_recipient)]
    recipients = [email.strip().lower() for email in recipients if email and email.strip()]
    if not recipients:
        missing_recipients.append(
            {
                "source": source,
                "source_id": source_id,
                "title": title,
                "responsible": responsible_name or "(sem responsavel)",
                "due_date": due_date.isoformat(),
            }
        )
        return

    for recipient in recipients:
        candidates.append(
            NotificationCandidate(
                source=source,
                source_id=source_id,
                title=title,
                project_code=project_code,
                project_name=project_name,
                responsible_name=responsible_name,
                recipient_email=recipient,
                due_date=due_date,
                alert_type=alert_type,
                days_until_due=days_until_due,
                detail=detail,
                run_date=today,
            )
        )


def collect_gantt(sb, people_by_id, projects, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients):
    rows = safe_data(
        sb.table("v_portfolio_tasks")
        .select("task_id,project_id,project_code,project_name,title,status,date_confidence,end_date,assignee_name")
        .gte("end_date", overdue_min.isoformat())
        .lte("end_date", max_due.isoformat())
        .execute()
    )
    candidates: list[NotificationCandidate] = []
    missing: list[dict[str, str]] = []
    for row in rows:
        status = norm(row.get("status"))
        confidence = norm(row.get("date_confidence"))
        if status in TERMINAL_TASK_STATUSES or confidence in TERMINAL_TASK_STATUSES:
            continue
        project = projects.get(clean_text(row.get("project_id")), {})
        responsible = person_for_name({p.name.lower(): p for p in people_by_id.values()}, clean_text(row.get("assignee_name")))
        add_candidate(
            candidates,
            missing,
            source="gantt",
            source_id=clean_text(row.get("task_id")),
            title=clean_text(row.get("title"), "(Sem titulo)"),
            project_code=clean_text(row.get("project_code")) or project.get("project_code", ""),
            project_name=clean_text(row.get("project_name")) or project.get("project_name", ""),
            responsible=responsible,
            fallback_recipient=fallback_recipient,
            forced_recipients=forced_recipients,
            due_date=to_date(row.get("end_date")),
            today=today,
            windows=windows,
            detail="Prazo da tarefa no Gantt",
        )
    return candidates, missing


def collect_laboratorio(sb, people_by_id, projects, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients):
    rows = safe_data(
        sb.table("v_lab_samples")
        .select("sample_id,project_id,project_code,project_name,assignee_id,assignee_name,status,expected_release_date,sample_types_label,lab_name")
        .gte("expected_release_date", overdue_min.isoformat())
        .lte("expected_release_date", max_due.isoformat())
        .execute()
    )
    candidates: list[NotificationCandidate] = []
    missing: list[dict[str, str]] = []
    for row in rows:
        if norm(row.get("status")) in TERMINAL_LAB_STATUSES:
            continue
        project = projects.get(clean_text(row.get("project_id")), {})
        responsible = people_by_id.get(clean_text(row.get("assignee_id")))
        sample_types = clean_text(row.get("sample_types_label")) or clean_text(row.get("sample_types"))
        lab_name = clean_text(row.get("lab_name"))
        detail = " | ".join(part for part in [sample_types, lab_name] if part)
        add_candidate(
            candidates,
            missing,
            source="laboratorio",
            source_id=clean_text(row.get("sample_id")),
            title="Amostra de laboratorio",
            project_code=clean_text(row.get("project_code")) or project.get("project_code", ""),
            project_name=clean_text(row.get("project_name")) or project.get("project_name", ""),
            responsible=responsible,
            fallback_recipient=fallback_recipient,
            forced_recipients=forced_recipients,
            due_date=to_date(row.get("expected_release_date")),
            today=today,
            windows=windows,
            detail=detail,
        )
    return candidates, missing


def collect_produtos(sb, people_by_name, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients):
    select_with_client_due = (
        "task_id,project_code,project_name,product_name,assignee_names,"
        "delivery_status,delivery_date,client_due_date,enterprise,end_date"
    )
    select_without_client_due = (
        "task_id,project_code,project_name,product_name,assignee_names,"
        "delivery_status,delivery_date,enterprise,end_date"
    )
    try:
        rows = safe_data(sb.table("v_deliverables").select(select_with_client_due).execute())
    except Exception:
        rows = safe_data(sb.table("v_deliverables").select(select_without_client_due).execute())

    candidates: list[NotificationCandidate] = []
    missing: list[dict[str, str]] = []
    for row in rows:
        if norm(row.get("delivery_status")) in TERMINAL_PRODUCT_STATUSES:
            continue
        if to_date(row.get("delivery_date")) is not None:
            continue
        due = to_date(row.get("client_due_date")) or to_date(row.get("enterprise")) or to_date(row.get("end_date"))
        if due is None or due < overdue_min or due > max_due:
            continue
        responsible = person_for_name(people_by_name, clean_text(row.get("assignee_names")))
        add_candidate(
            candidates,
            missing,
            source="produtos",
            source_id=clean_text(row.get("task_id")),
            title=clean_text(row.get("product_name"), "(Produto sem nome)"),
            project_code=clean_text(row.get("project_code")),
            project_name=clean_text(row.get("project_name")),
            responsible=responsible,
            fallback_recipient=fallback_recipient,
            forced_recipients=forced_recipients,
            due_date=due,
            today=today,
            windows=windows,
            detail="Prazo de entrega ao cliente",
        )
    return candidates, missing


def collect_reembolsos(sb, people_by_id, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients):
    rows = safe_data(
        sb.table("v_reimbursements")
        .select("id,due_date,collaborator_id,collaborator_name,project_code,project_name,category_name,description,amount,status")
        .gte("due_date", overdue_min.isoformat())
        .lte("due_date", max_due.isoformat())
        .execute()
    )
    candidates: list[NotificationCandidate] = []
    missing: list[dict[str, str]] = []
    for row in rows:
        if norm(row.get("status")) in TERMINAL_REIMBURSEMENT_STATUSES:
            continue
        responsible = people_by_id.get(clean_text(row.get("collaborator_id")))
        detail = " | ".join(
            part
            for part in [
                clean_text(row.get("category_name")),
                clean_text(row.get("description")),
                brl(row.get("amount")),
            ]
            if part
        )
        add_candidate(
            candidates,
            missing,
            source="reembolsos",
            source_id=clean_text(row.get("id")),
            title="Reembolso / despesa interna",
            project_code=clean_text(row.get("project_code")),
            project_name=clean_text(row.get("project_name")),
            responsible=responsible,
            fallback_recipient=fallback_recipient,
            forced_recipients=forced_recipients,
            due_date=to_date(row.get("due_date")),
            today=today,
            windows=windows,
            detail=detail,
        )
    return candidates, missing


def fetch_existing_keys(sb, keys: list[str], dry_run: bool) -> set[str]:
    if not keys:
        return set()
    found: set[str] = set()
    try:
        for group in chunked(keys, 100):
            rows = safe_data(
                sb.table("due_notification_log")
                .select("notification_key")
                .eq("status", "SENT")
                .in_("notification_key", group)
                .execute()
            )
            found.update(clean_text(row.get("notification_key")) for row in rows)
    except Exception as exc:
        if dry_run:
            print(f"WARN: due_notification_log indisponivel no dry-run: {exc}", file=sys.stderr)
            return set()
        raise RuntimeError(
            "Tabela due_notification_log indisponivel. Aplique a migration "
            "migrations/2026_07_01_due_notifications.sql antes do envio real."
        ) from exc
    return found


def insert_logs(sb, candidates: list[NotificationCandidate], subject: str, provider_message_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "notification_key": candidate.notification_key,
            "source": candidate.source.upper(),
            "source_id": candidate.source_id,
            "recipient_email": candidate.recipient_email,
            "due_date": candidate.due_date.isoformat(),
            "alert_type": candidate.alert_type,
            "days_until_due": candidate.days_until_due,
            "subject": subject,
            "status": "SENT",
            "provider_message_id": provider_message_id,
            "sent_at": now,
        }
        for candidate in candidates
    ]
    for group in chunked(rows, 100):
        sb.table("due_notification_log").insert(group).execute()


def item_status_text(candidate: NotificationCandidate) -> str:
    if candidate.alert_type == "OVERDUE":
        return f"atrasado ha {abs(candidate.days_until_due)} dia(s)"
    if candidate.alert_type == "TODAY":
        return "vence hoje"
    return f"vence em {candidate.days_until_due} dia(s)"


def build_email(recipient: str, items: list[NotificationCandidate], today: date) -> tuple[str, str, str]:
    subject = f"Opyta | {len(items)} aviso(s) de vencimento"
    lines = [
        "Ola,",
        "",
        f"Estes sao os vencimentos monitorados em {today.strftime('%d/%m/%Y')}:",
        "",
    ]
    html_rows = []
    for item in sorted(items, key=lambda c: (c.due_date, c.source, c.project_code, c.title)):
        source = SOURCE_LABELS.get(item.source, item.source)
        due_br = item.due_date.strftime("%d/%m/%Y")
        status_text = item_status_text(item)
        project = item.project_code or item.project_name or "-"
        detail = f" | {item.detail}" if item.detail else ""
        lines.append(f"- [{source}] {project} - {item.title} - {due_br} ({status_text}){detail}")
        html_rows.append(
            "<tr>"
            f"<td>{html.escape(source)}</td>"
            f"<td>{html.escape(project)}</td>"
            f"<td>{html.escape(item.title)}</td>"
            f"<td>{html.escape(due_br)}</td>"
            f"<td>{html.escape(status_text)}</td>"
            f"<td>{html.escape(item.detail)}</td>"
            "</tr>"
        )
    lines.extend(["", "Mensagem automatica do Opyta."])
    text_body = "\n".join(lines)
    html_body = f"""
    <html>
      <body>
        <p>Ola,</p>
        <p>Estes sao os vencimentos monitorados em <strong>{today.strftime('%d/%m/%Y')}</strong>:</p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;">
          <thead>
            <tr>
              <th>Origem</th><th>Projeto</th><th>Item</th><th>Prazo</th><th>Situacao</th><th>Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {''.join(html_rows)}
          </tbody>
        </table>
        <p style="color:#666;">Mensagem automatica do Opyta.</p>
      </body>
    </html>
    """
    return subject, text_body, html_body


def build_gmail_service(service_account_json: str, delegated_user_email: str, scopes: list[str]):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(service_account_json, scopes=scopes)
    delegated = credentials.with_subject(delegated_user_email)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)


def send_gmail(service, from_email: str, to_email: str, subject: str, text_body: str, html_body: str, reply_to: str = "") -> str:
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    result = service.users().messages().send(userId=from_email, body={"raw": raw}).execute()
    return clean_text(result.get("id"))


def group_by_recipient(candidates: list[NotificationCandidate]) -> dict[str, list[NotificationCandidate]]:
    grouped: dict[str, list[NotificationCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.recipient_email].append(candidate)
    return dict(grouped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Opyta due-date alerts by email.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send email or write logs.")
    parser.add_argument("--today", help="Override today as YYYY-MM-DD, useful for tests.")
    return parser.parse_args()


def main() -> int:
    load_dotenv(".env")
    args = parse_args()

    dry_run = args.dry_run or env_bool("NOTIFICATION_DRY_RUN", True)
    today = date.fromisoformat(args.today) if args.today else date.today()
    windows = parse_windows(os.getenv("NOTIFICATION_WINDOWS_DAYS"))
    max_window = max(windows or {0})
    overdue_lookback = env_int("NOTIFICATION_OVERDUE_LOOKBACK_DAYS", 30)
    overdue_min = today - timedelta(days=overdue_lookback)
    max_due = today + timedelta(days=max_window)
    sources = {part.lower() for part in parse_csv(os.getenv("NOTIFICATION_SOURCES"), SOURCE_LABELS.keys())}
    fallback_recipient = clean_text(os.getenv("NOTIFICATION_FALLBACK_RECIPIENT")).lower()
    forced_recipients = parse_email_list(os.getenv("NOTIFICATION_FORCE_RECIPIENTS"))

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY sao obrigatorios.")

    sb = create_client(supabase_url, supabase_key)
    people_by_id, people_by_name = load_people(sb)
    projects = load_projects(sb)

    all_candidates: list[NotificationCandidate] = []
    all_missing: list[dict[str, str]] = []

    collectors = {
        "gantt": lambda: collect_gantt(sb, people_by_id, projects, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients),
        "laboratorio": lambda: collect_laboratorio(sb, people_by_id, projects, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients),
        "produtos": lambda: collect_produtos(sb, people_by_name, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients),
        "reembolsos": lambda: collect_reembolsos(sb, people_by_id, today, windows, overdue_min, max_due, fallback_recipient, forced_recipients),
    }

    for source, collector in collectors.items():
        if source not in sources:
            continue
        try:
            candidates, missing = collector()
            all_candidates.extend(candidates)
            all_missing.extend(missing)
        except Exception as exc:
            print(f"WARN: fonte {source} ignorada por erro: {exc}", file=sys.stderr)

    existing = fetch_existing_keys(sb, [c.notification_key for c in all_candidates], dry_run=dry_run)
    candidates = [candidate for candidate in all_candidates if candidate.notification_key not in existing]
    grouped = group_by_recipient(candidates)
    unique_due_items = {
        (candidate.source, candidate.source_id, candidate.alert_type, candidate.days_until_due, candidate.due_date.isoformat())
        for candidate in all_candidates
    }
    unique_due_items.update(
        (item.get("source", ""), item.get("source_id", ""), item.get("due_date", ""))
        for item in all_missing
    )

    stats = {
        "dry_run": dry_run,
        "today": today.isoformat(),
        "windows_days": sorted(windows),
        "overdue_lookback_days": overdue_lookback,
        "recipient_mode": "forced" if forced_recipients else "responsible",
        "forced_recipients": forced_recipients,
        "due_items_total": len(unique_due_items),
        "candidate_deliveries_total": len(all_candidates) + len(all_missing),
        "candidates_with_recipient": len(all_candidates),
        "already_sent": len(existing),
        "candidates_to_send": len(candidates),
        "recipient_count": len(grouped),
        "missing_recipient_count": len(all_missing),
        "missing_recipients_sample": all_missing[:10],
    }

    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if not grouped:
        return 0

    from_email = clean_text(os.getenv("NOTIFICATION_FROM_EMAIL") or os.getenv("FALLBACK_OWNER_EMAIL")).lower()
    reply_to = clean_text(os.getenv("NOTIFICATION_REPLY_TO")).lower()
    service = None
    if not dry_run:
        service_account_json = clean_text(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        delegated_user_email = clean_text(os.getenv("FALLBACK_OWNER_EMAIL") or from_email)
        scopes = parse_csv(os.getenv("GOOGLE_SCOPES"), ["https://www.googleapis.com/auth/gmail.send"])
        if not from_email:
            raise RuntimeError("NOTIFICATION_FROM_EMAIL ou FALLBACK_OWNER_EMAIL e obrigatorio para envio real.")
        if not service_account_json:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON e obrigatorio para envio real.")
        service = build_gmail_service(service_account_json, delegated_user_email, scopes)

    for recipient, items in grouped.items():
        subject, text_body, html_body = build_email(recipient, items, today)
        if dry_run:
            print(f"DRY-RUN: enviaria para {recipient}: {subject}")
            print(text_body)
            continue
        message_id = send_gmail(service, from_email, recipient, subject, text_body, html_body, reply_to)
        insert_logs(sb, items, subject, message_id)
        print(f"SENT: {recipient} items={len(items)} message_id={message_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
