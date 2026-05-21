-- =====================================================================
-- Acompanhamento de Produtos / Entregas
-- Reaproveita tasks (tipo_atividade='RELATORIO') sem duplicar cadastro.
-- =====================================================================

-- 1) Acompanhamento 1:1 com a tarefa
create table if not exists public.task_delivery_tracking (
  task_id          uuid primary key references public.tasks(id) on delete cascade,
  delivery_status  text not null default 'NAO_INICIADO'
                   check (delivery_status in
                     ('NAO_INICIADO','EM_ELABORACAO','EM_REVISAO','ENTREGUE','FATURADO')),
  needs_revision   boolean not null default false,
  sent_to_client   boolean not null default false,
  delivery_date    date,
  invoice_date     date,
  discipline       text,
  enterprise       text,
  notes            text,
  updated_at       timestamptz not null default now(),
  updated_by       uuid
);

-- 2) Histórico / timeline
create table if not exists public.task_delivery_events (
  id           uuid primary key default gen_random_uuid(),
  task_id      uuid not null references public.tasks(id) on delete cascade,
  event_type   text not null check (event_type in
                 ('STATUS_CHANGE','REVISION_FLAG','SENT_TO_CLIENT',
                  'DELIVERED','INVOICED','NOTE','CREATED')),
  from_value   text,
  to_value     text,
  notes        text,
  changed_by   uuid,
  changed_at   timestamptz not null default now()
);

create index if not exists ix_tde_task_changed
  on public.task_delivery_events (task_id, changed_at desc);

-- 3) Trigger: registra eventos automaticamente
create or replace function public.fn_log_delivery_event() returns trigger
language plpgsql as $$
begin
  if tg_op = 'INSERT' then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'CREATED', new.delivery_status, new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.delivery_status is distinct from old.delivery_status then
    insert into public.task_delivery_events(task_id, event_type, from_value, to_value, changed_by)
    values (new.task_id, 'STATUS_CHANGE', old.delivery_status, new.delivery_status, new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.needs_revision and not coalesce(old.needs_revision,false) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'REVISION_FLAG', 'true', new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.sent_to_client and not coalesce(old.sent_to_client,false) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'SENT_TO_CLIENT', 'true', new.updated_by);
  end if;

  if new.delivery_date is not null
     and (tg_op = 'INSERT' or new.delivery_date is distinct from old.delivery_date) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'DELIVERED', new.delivery_date::text, new.updated_by);
  end if;

  if new.invoice_date is not null
     and (tg_op = 'INSERT' or new.invoice_date is distinct from old.invoice_date) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'INVOICED', new.invoice_date::text, new.updated_by);
  end if;

  return new;
end $$;

drop trigger if exists trg_delivery_event on public.task_delivery_tracking;
create trigger trg_delivery_event
after insert or update on public.task_delivery_tracking
for each row execute function public.fn_log_delivery_event();

-- 4) updated_at automático
create or replace function public.fn_touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at := now(); return new; end $$;

drop trigger if exists trg_touch_tracking on public.task_delivery_tracking;
create trigger trg_touch_tracking
before update on public.task_delivery_tracking
for each row execute function public.fn_touch_updated_at();

-- 5) View consolidada para o Streamlit
-- Hoje considera apenas tipo_atividade='RELATORIO'. Para incluir outros,
-- ajustar o WHERE.
create or replace view public.v_deliverables as
select
  t.id                                          as task_id,
  t.project_id,
  p.project_code,
  p.name                                        as project_name,
  t.title                                       as product_name,
  t.tipo_atividade,
  t.start_date,
  t.end_date,
  t.status                                      as task_status,
  coalesce(d.delivery_status,'NAO_INICIADO')    as delivery_status,
  coalesce(d.needs_revision, false)             as needs_revision,
  coalesce(d.sent_to_client, false)             as sent_to_client,
  d.delivery_date,
  d.invoice_date,
  d.discipline,
  d.enterprise,
  d.notes                                       as tracking_notes,
  d.updated_at                                  as tracking_updated_at
from public.tasks t
join public.projects p on p.id = t.project_id
left join public.task_delivery_tracking d on d.task_id = t.id
where t.tipo_atividade = 'RELATORIO';

-- 6) RLS — mesma política das demais tabelas (ajustar conforme padrão do projeto)
alter table public.task_delivery_tracking enable row level security;
alter table public.task_delivery_events   enable row level security;

drop policy if exists p_tdt_read  on public.task_delivery_tracking;
drop policy if exists p_tdt_write on public.task_delivery_tracking;
create policy p_tdt_read  on public.task_delivery_tracking
  for select to authenticated using (true);
create policy p_tdt_write on public.task_delivery_tracking
  for all to authenticated using (true) with check (true);

drop policy if exists p_tde_read on public.task_delivery_events;
create policy p_tde_read on public.task_delivery_events
  for select to authenticated using (true);
-- escrita só pela trigger (security definer não necessário pois roda como dono)

-- 7) Grants para a view
grant select on public.v_deliverables to authenticated;
