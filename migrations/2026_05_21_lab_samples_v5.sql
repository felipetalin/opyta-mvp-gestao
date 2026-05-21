-- =====================================================================
-- Laboratório v5 — índice em expected_release_date.
-- Idempotente.
-- =====================================================================

create index if not exists ix_lab_samples_expected_release_date
  on public.lab_samples (expected_release_date);

create index if not exists ix_lab_samples_status
  on public.lab_samples (status);
