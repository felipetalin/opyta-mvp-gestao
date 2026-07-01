-- =====================================================================
-- Reembolsos v2 - prazo de pagamento e situacao operacional.
-- Idempotente.
-- =====================================================================

alter table public.reimbursements
  add column if not exists due_date date;

update public.reimbursements
set due_date = expense_date
where due_date is null;

create index if not exists ix_reimbursements_due_date
  on public.reimbursements (due_date);

alter table public.reimbursement_events
  drop constraint if exists reimbursement_events_event_type_check;

alter table public.reimbursement_events
  add constraint reimbursement_events_event_type_check
  check (event_type in (
    'CREATED',
    'STATUS_CHANGE',
    'DUE_DATE_CHANGE',
    'PAYMENT_DATE_CHANGE',
    'UPDATED',
    'ATTACHMENT_ADDED',
    'ATTACHMENT_REMOVED'
  ));

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

    if new.due_date is distinct from old.due_date then
      insert into public.reimbursement_events(
        reimbursement_id, event_type, from_value, to_value, changed_by_email
      )
      values (
        new.id,
        'DUE_DATE_CHANGE',
        old.due_date::text,
        new.due_date::text,
        actor
      );
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

create or replace view public.v_reimbursements as
select
  r.id,
  r.expense_date,
  r.due_date,
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

grant select on public.v_reimbursements to authenticated;

notify pgrst, 'reload schema';
