-- =====================================================================
-- Alertas de vencimento por e-mail
-- Log idempotente para evitar reenvio do mesmo aviso.
-- =====================================================================

create table if not exists public.due_notification_log (
  id                  uuid primary key default gen_random_uuid(),
  notification_key    text not null,
  source              text not null check (source in ('GANTT','LABORATORIO','PRODUTOS','REEMBOLSOS')),
  source_id           uuid not null,
  recipient_email     text not null,
  due_date            date,
  alert_type          text not null check (alert_type in ('OVERDUE','TODAY','DAYS_BEFORE')),
  days_until_due      integer,
  subject             text,
  status              text not null default 'SENT' check (status in ('SENT','ERROR')),
  provider_message_id text,
  error_message       text,
  sent_at             timestamptz not null default now(),
  created_at          timestamptz not null default now()
);

create index if not exists ix_due_notification_log_sent_at
  on public.due_notification_log (sent_at desc);

create index if not exists ix_due_notification_log_recipient
  on public.due_notification_log (recipient_email, sent_at desc);

create index if not exists ix_due_notification_log_source
  on public.due_notification_log (source, source_id, sent_at desc);

create unique index if not exists ux_due_notification_log_key_sent
  on public.due_notification_log (notification_key)
  where status = 'SENT';

alter table public.due_notification_log enable row level security;

drop policy if exists p_due_notification_log_read on public.due_notification_log;
create policy p_due_notification_log_read on public.due_notification_log
  for select to authenticated using (true);

drop policy if exists p_due_notification_log_insert on public.due_notification_log;
create policy p_due_notification_log_insert on public.due_notification_log
  for insert to authenticated with check (true);

grant select, insert on public.due_notification_log to authenticated;
