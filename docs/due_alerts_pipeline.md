# Pipeline de alertas de vencimento

## Objetivo

Enviar avisos por e-mail para responsaveis por itens com prazo vencido ou proximo
do vencimento, reaproveitando o Supabase e a automacao via GitHub Actions.

## Fontes monitoradas

- `gantt`: tarefas de `v_portfolio_tasks`, usando `end_date`.
- `laboratorio`: amostras de `v_lab_samples`, usando `expected_release_date`.
- `produtos`: entregas de `v_deliverables`, usando `client_due_date` quando existir;
  caso contrario, usa o fallback ja tratado na aba Produtos (`enterprise`/`end_date`).
- `reembolsos`: despesas de `v_reimbursements`, usando `due_date`.

## Regras iniciais

- Janelas: vencido, vence hoje, vence em 1, 3 ou 7 dias.
- Atrasados entram por ate 30 dias de atraso por padrao.
- Itens concluidos/pagos/cancelados/glosados nao entram no aviso.
- Os avisos sao agrupados em um e-mail por destinatario.
- Para a fase atual, os avisos sao centralizados em destinatarios fixos:
  `yurisimoes@opyta.com.br` e `felipetalin@opyta.com.br`.
- O envio real registra cada item em `due_notification_log` para evitar duplicidade.

## Arquivos

- Script: `scripts/notifications/send_due_alerts.py`
- Workflow: `.github/workflows/due-alerts.yml`
- Migration: `migrations/2026_07_01_due_notifications.sql`

## Registro em 2026-07-01

- A integracao existente do Gantt e um sync com Google Calendar, nao um envio de
  e-mail transacional. Ela continua sendo util para agenda, mas nao substitui o
  pipeline de avisos.
- A decisao tomada foi criar um job separado de notificacoes, mantendo o Gantt,
  Laboratorio, Produtos e Reembolsos como fontes independentes.
- O provedor escolhido para a primeira versao de envio real foi Gmail API com
  service account/delegacao, usando o escopo `https://www.googleapis.com/auth/gmail.send`.
- O workflow `Due Alerts` foi publicado em modo seguro: a agenda diaria roda em
  dry-run ate a virada final da chave.
- Dry-run local em `2026-07-01`: o job encontrou 27 vencimentos dentro das regras,
  mas todos ficaram sem destinatario porque `people.email` ainda estava vazio.
- Teste controlado com `NOTIFICATION_FALLBACK_RECIPIENT` e fonte `reembolsos`
  montou corretamente um e-mail com 3 avisos: 2 atrasados e 1 vencendo em 1 dia.
- A tabela `due_notification_log` ainda precisa ser criada no Supabase antes do
  envio real; em dry-run a ausencia dessa tabela gera apenas aviso tecnico.

## Registro em 2026-07-02

- Dry-run completo com data de referencia `2026-07-02`: o job encontrou 27
  vencimentos dentro das regras.
- Nenhum aviso ficou apto a envio direto porque os 7 colaboradores ativos ainda
  estavam sem `people.email`.
- A tabela `due_notification_log` ainda nao estava aplicada no Supabase; a API
  retornou `PGRST205` para `public.due_notification_log`.
- Teste com `NOTIFICATION_FALLBACK_RECIPIENT=felipetalin@opyta.com.br` montou
  corretamente um unico e-mail com 27 avisos, sem envio real.
- Smoke test real via Gmail API para `felipetalin@opyta.com.br` falhou antes do
  envio com `unauthorized_client`, indicando que a service account ainda nao foi
  autorizada no Google Workspace para o escopo `gmail.send`.
- Ao instalar `requirements-sync.txt` localmente, o resolvedor puxou `protobuf 7`,
  que conflita com Streamlit. O ambiente local foi corrigido para `protobuf<7`, e
  o arquivo de dependencias passou a fixar `protobuf>=5.29.6,<7`.
- A regra de destinatario foi alterada para atendimento centralizado: todos os
  avisos vao somente para `yurisimoes@opyta.com.br` e
  `felipetalin@opyta.com.br`, via `NOTIFICATION_FORCE_RECIPIENTS`.
- Dry-run com destinatarios fixos em `2026-07-02`: 27 itens unicos de vencimento,
  54 entregas candidatas, 2 destinatarios e 0 destinatarios faltantes.
- O sync local tambem precisou atualizar `supabase` para `>=2.27,<3`, pois a
  versao `2.6.0` nao aceita as chaves novas `sb_secret_...`/`sb_publishable_...`.
  Foi necessario fixar `websockets>=13,<16` para compatibilidade com o cliente
  moderno do Supabase.

## Registro em 2026-07-02 - tentativa de seguir para envio real

- A verificacao no Supabase ainda retornou `PGRST205` para
  `public.due_notification_log`, confirmando que a migration
  `migrations/2026_07_01_due_notifications.sql` ainda nao foi aplicada.
- Nao ha `supabase` CLI, `gh` CLI, `psql`, `DATABASE_URL`, `POSTGRES_URL` ou RPC
  `exec_sql` disponivel neste ambiente; portanto, a aplicacao da migration ainda
  precisa ser feita pelo SQL Editor do Supabase.
- Smoke test real de Gmail para `felipetalin@opyta.com.br` ainda falhou antes do
  envio com `unauthorized_client`.
- Service account testada:
  - `client_email`: `opyta-gcal-bot@api-calendar-486417.iam.gserviceaccount.com`
  - `client_id`: `113323402794566274776`
- Escopo que precisa ser liberado no Admin do Google Workspace:
  - `https://www.googleapis.com/auth/gmail.send`
- Enquanto esses dois pontos externos nao forem concluidos, manter o envio real
  bloqueado. Dry-run permanece funcional e validado com os dois destinatarios
  fixos.

## Checklist para ativar

1. Aplicar `migrations/2026_07_01_due_notifications.sql` no SQL Editor do Supabase.
2. Confirmar que `NOTIFICATION_FORCE_RECIPIENTS` contem apenas:
   - `yurisimoes@opyta.com.br`
   - `felipetalin@opyta.com.br`
3. Garantir que o GitHub tenha os secrets:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
4. No Admin do Google Workspace, autorizar a service account para o escopo:
   - `https://www.googleapis.com/auth/gmail.send`
5. Rodar o workflow `Due Alerts` manualmente com `dry_run=true`.
6. Rodar manualmente com `dry_run=false` para validar envio real.
7. Depois de validado, alterar o workflow para agenda real sem dry-run.

## Execucao local

Dry-run:

```bash
python scripts/notifications/send_due_alerts.py --dry-run
```

Forcar data de referencia:

```bash
python scripts/notifications/send_due_alerts.py --dry-run --today 2026-07-01
```

Envio real exige:

```bash
set NOTIFICATION_DRY_RUN=0
set NOTIFICATION_FROM_EMAIL=felipetalin@opyta.com.br
set FALLBACK_OWNER_EMAIL=felipetalin@opyta.com.br
set GOOGLE_SERVICE_ACCOUNT_JSON=secrets_gcal/service-account-gcal.json
set GOOGLE_SCOPES=https://www.googleapis.com/auth/gmail.send
python scripts/notifications/send_due_alerts.py
```

## Observacoes

- Enquanto `people.email` estiver vazio, os itens aparecem no contador
  `missing_recipient_count` e nao sao enviados, exceto quando
  `NOTIFICATION_FORCE_RECIPIENTS` estiver definido.
- Para teste controlado sem preencher todos os e-mails, e possivel definir
  `NOTIFICATION_FALLBACK_RECIPIENT`, mas isso deve ser temporario. Para a regra
  atual, preferir `NOTIFICATION_FORCE_RECIPIENTS`.
- A agenda do workflow esta em 08:00 BRT em dias uteis, mas fica em dry-run ate a
  virada final da chave.
