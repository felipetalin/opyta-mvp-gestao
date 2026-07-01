-- =====================================================================
-- Reembolsos & Despesas Internas
-- Controle de despesas pagas por colaboradores em nome da empresa.
-- Idempotente.
-- =====================================================================

create or replace function public.fn_touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

create table if not exists public.reimbursement_categories (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  active      boolean not null default true,
  sort_order  int not null default 100,
  created_at  timestamptz not null default now()
);

insert into public.reimbursement_categories (name, sort_order)
values
  ('Alimentacao', 10),
  ('Hospedagem', 20),
  ('Transporte', 30),
  ('Combustivel', 40),
  ('Pedagio / estacionamento', 50),
  ('Material de campo', 60),
  ('Correios / cartorio', 70),
  ('Outros', 999)
on conflict (name) do nothing;

create table if not exists public.reimbursements (
  id                 uuid primary key default gen_random_uuid(),
  expense_date       date not null,
  collaborator_id    uuid not null references public.people(id) on delete restrict,
  project_id         uuid not null references public.projects(id) on delete restrict,
  category_id        uuid not null references public.reimbursement_categories(id) on delete restrict,
  description        text not null,
  amount             numeric(14,2) not null check (amount > 0),
  status             text not null default 'PENDENTE'
                     check (status in ('PENDENTE','APROVADO','PAGO','GLOSADO')),
  payment_date       date,
  observations       text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  created_by_email   text,
  updated_by_email   text,
  constraint ck_reimbursements_paid_has_payment_date
    check (status <> 'PAGO' or payment_date is not null)
);

create index if not exists ix_reimbursements_expense_date
  on public.reimbursements (expense_date);
create index if not exists ix_reimbursements_status
  on public.reimbursements (status);
create index if not exists ix_reimbursements_payment_date
  on public.reimbursements (payment_date);
create index if not exists ix_reimbursements_collaborator
  on public.reimbursements (collaborator_id);
create index if not exists ix_reimbursements_project
  on public.reimbursements (project_id);
create index if not exists ix_reimbursements_category
  on public.reimbursements (category_id);

drop trigger if exists trg_reimbursements_touch on public.reimbursements;
create trigger trg_reimbursements_touch
before update on public.reimbursements
for each row execute function public.fn_touch_updated_at();

create table if not exists public.reimbursement_events (
  id                uuid primary key default gen_random_uuid(),
  reimbursement_id  uuid not null references public.reimbursements(id) on delete cascade,
  event_type        text not null check (event_type in (
                      'CREATED',
                      'STATUS_CHANGE',
                      'PAYMENT_DATE_CHANGE',
                      'UPDATED',
                      'ATTACHMENT_ADDED',
                      'ATTACHMENT_REMOVED'
                    )),
  from_value        text,
  to_value          text,
  notes             text,
  changed_by_email  text,
  changed_at        timestamptz not null default now()
);

create index if not exists ix_reimbursement_events_row_changed
  on public.reimbursement_events (reimbursement_id, changed_at desc);

create table if not exists public.reimbursement_attachments (
  id                uuid primary key default gen_random_uuid(),
  reimbursement_id  uuid not null references public.reimbursements(id) on delete cascade,
  file_name         text not null,
  storage_bucket    text not null default 'reimbursement-receipts',
  storage_path      text not null,
  mime_type         text not null check (mime_type in ('application/pdf','image/jpeg','image/png')),
  file_size         bigint,
  uploaded_at       timestamptz not null default now(),
  uploaded_by_email text,
  unique (storage_bucket, storage_path)
);

create index if not exists ix_reimbursement_attachments_row
  on public.reimbursement_attachments (reimbursement_id, uploaded_at desc);

create or replace function public.fn_log_reimbursement_event() returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  changed_fields text[] := array[]::text[];
  actor text;
begin
  if tg_op = 'INSERT' then
    insert into public.reimbursement_events(
      reimbursement_id, event_type, to_value, changed_by_email
    )
    values (
      new.id, 'CREATED', new.status, coalesce(new.created_by_email, new.updated_by_email)
    );
    return new;
  end if;

  if tg_op = 'UPDATE' then
    actor := coalesce(new.updated_by_email, old.updated_by_email, new.created_by_email, old.created_by_email);

    if new.status is distinct from old.status then
      insert into public.reimbursement_events(
        reimbursement_id, event_type, from_value, to_value, changed_by_email
      )
      values (new.id, 'STATUS_CHANGE', old.status, new.status, actor);
    end if;

    if new.payment_date is distinct from old.payment_date then
      insert into public.reimbursement_events(
        reimbursement_id, event_type, from_value, to_value, changed_by_email
      )
      values (
        new.id,
        'PAYMENT_DATE_CHANGE',
        old.payment_date::text,
        new.payment_date::text,
        actor
      );
    end if;

    if new.expense_date is distinct from old.expense_date then
      changed_fields := array_append(changed_fields, 'Data da despesa');
    end if;
    if new.collaborator_id is distinct from old.collaborator_id then
      changed_fields := array_append(changed_fields, 'Colaborador');
    end if;
    if new.project_id is distinct from old.project_id then
      changed_fields := array_append(changed_fields, 'Projeto');
    end if;
    if new.category_id is distinct from old.category_id then
      changed_fields := array_append(changed_fields, 'Categoria');
    end if;
    if new.description is distinct from old.description then
      changed_fields := array_append(changed_fields, 'Descricao');
    end if;
    if new.amount is distinct from old.amount then
      changed_fields := array_append(changed_fields, 'Valor');
    end if;
    if new.observations is distinct from old.observations then
      changed_fields := array_append(changed_fields, 'Observacoes');
    end if;

    if array_length(changed_fields, 1) > 0 then
      insert into public.reimbursement_events(
        reimbursement_id, event_type, notes, changed_by_email
      )
      values (new.id, 'UPDATED', array_to_string(changed_fields, ', '), actor);
    end if;

    return new;
  end if;

  return new;
end $$;

drop trigger if exists trg_reimbursement_event on public.reimbursements;
create trigger trg_reimbursement_event
after insert or update on public.reimbursements
for each row execute function public.fn_log_reimbursement_event();

create or replace function public.fn_log_reimbursement_attachment_event() returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.reimbursement_events(
      reimbursement_id, event_type, to_value, changed_by_email
    )
    values (new.reimbursement_id, 'ATTACHMENT_ADDED', new.file_name, new.uploaded_by_email);
    return new;
  end if;

  if tg_op = 'DELETE' then
    insert into public.reimbursement_events(
      reimbursement_id, event_type, from_value, changed_by_email
    )
    values (old.reimbursement_id, 'ATTACHMENT_REMOVED', old.file_name, old.uploaded_by_email);
    return old;
  end if;

  return new;
end $$;

drop trigger if exists trg_reimbursement_attachment_event on public.reimbursement_attachments;
create trigger trg_reimbursement_attachment_event
after insert or delete on public.reimbursement_attachments
for each row execute function public.fn_log_reimbursement_attachment_event();

drop view if exists public.v_reimbursements;
create view public.v_reimbursements as
select
  r.id,
  r.expense_date,
  r.collaborator_id,
  ppl.name as collaborator_name,
  r.project_id,
  p.project_code,
  p.name as project_name,
  r.category_id,
  c.name as category_name,
  r.description,
  r.amount,
  r.status,
  r.payment_date,
  r.observations,
  r.created_at,
  r.updated_at,
  r.created_by_email,
  r.updated_by_email,
  coalesce(att.receipt_count, 0)::int as receipt_count
from public.reimbursements r
join public.people ppl on ppl.id = r.collaborator_id
join public.projects p on p.id = r.project_id
join public.reimbursement_categories c on c.id = r.category_id
left join (
  select reimbursement_id, count(*) as receipt_count
  from public.reimbursement_attachments
  group by reimbursement_id
) att on att.reimbursement_id = r.id;

-- RLS / grants
alter table public.reimbursement_categories enable row level security;
alter table public.reimbursements enable row level security;
alter table public.reimbursement_events enable row level security;
alter table public.reimbursement_attachments enable row level security;

drop policy if exists p_reimbursement_categories_read on public.reimbursement_categories;
drop policy if exists p_reimbursement_categories_write on public.reimbursement_categories;
create policy p_reimbursement_categories_read on public.reimbursement_categories
  for select to authenticated using (true);
create policy p_reimbursement_categories_write on public.reimbursement_categories
  for all to authenticated using (true) with check (true);

drop policy if exists p_reimbursements_read on public.reimbursements;
drop policy if exists p_reimbursements_write on public.reimbursements;
create policy p_reimbursements_read on public.reimbursements
  for select to authenticated using (true);
create policy p_reimbursements_write on public.reimbursements
  for all to authenticated using (true) with check (true);

drop policy if exists p_reimbursement_events_read on public.reimbursement_events;
drop policy if exists p_reimbursement_events_insert on public.reimbursement_events;
create policy p_reimbursement_events_read on public.reimbursement_events
  for select to authenticated using (true);
create policy p_reimbursement_events_insert on public.reimbursement_events
  for insert to authenticated with check (true);

drop policy if exists p_reimbursement_attachments_read on public.reimbursement_attachments;
drop policy if exists p_reimbursement_attachments_write on public.reimbursement_attachments;
create policy p_reimbursement_attachments_read on public.reimbursement_attachments
  for select to authenticated using (true);
create policy p_reimbursement_attachments_write on public.reimbursement_attachments
  for all to authenticated using (true) with check (true);

grant select, insert, update, delete on public.reimbursement_categories to authenticated;
grant select, insert, update, delete on public.reimbursements to authenticated;
grant select, insert, update, delete on public.reimbursement_events to authenticated;
grant select, insert, update, delete on public.reimbursement_attachments to authenticated;
grant select on public.v_reimbursements to authenticated;

-- Bucket privado de comprovantes (PDF/JPG/PNG).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'reimbursement-receipts',
  'reimbursement-receipts',
  false,
  10485760,
  array['application/pdf','image/jpeg','image/png']
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists p_reimbursement_receipts_read on storage.objects;
drop policy if exists p_reimbursement_receipts_insert on storage.objects;
drop policy if exists p_reimbursement_receipts_update on storage.objects;
drop policy if exists p_reimbursement_receipts_delete on storage.objects;

create policy p_reimbursement_receipts_read on storage.objects
  for select to authenticated
  using (bucket_id = 'reimbursement-receipts');

create policy p_reimbursement_receipts_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'reimbursement-receipts');

create policy p_reimbursement_receipts_update on storage.objects
  for update to authenticated
  using (bucket_id = 'reimbursement-receipts')
  with check (bucket_id = 'reimbursement-receipts');

create policy p_reimbursement_receipts_delete on storage.objects
  for delete to authenticated
  using (bucket_id = 'reimbursement-receipts');

-- Atualiza o schema cache do PostgREST apos criar tabelas/views/funcoes.
notify pgrst, 'reload schema';
