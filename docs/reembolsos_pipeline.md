# Reembolsos e Despesas Internas - aprendizado e pipeline

Este documento registra o aprendizado da implantacao da aba `Reembolsos`
para orientar ajustes futuros sem depender do historico da conversa.

## Objetivo da aba

A aba controla despesas pagas por colaboradores em nome da empresa,
com foco em:

- acompanhar valores pendentes de reembolso;
- registrar pagamentos;
- visualizar pendencias por colaborador e projeto;
- manter comprovantes vinculados ao lancamento;
- manter historico de alteracoes;
- permitir edicao direta em tabela, seguindo a logica operacional das abas
  `Laboratorio` e `Produtos`.

## Arquivos principais

- `app/pages/7_Reembolsos.py`
  - Pagina Streamlit da funcionalidade.
  - Contem filtros, indicadores, cadastro, exportacao, tabela editavel,
    comprovantes e historico.

- `migrations/2026_07_01_reimbursements.sql`
  - Migration base.
  - Cria categorias, lancamentos, anexos, eventos, view e bucket de storage.

- `migrations/2026_07_01_reimbursements_v2_due_date.sql`
  - Migration complementar.
  - Adiciona `due_date`, atualiza historico e recria a view.

- `app/services/supabase_client.py`
  - Cliente Supabase.
  - Aprendizado importante: precisa tolerar ausencia de `st.secrets` local
    e cair para `.env`.

- `app/services/finance_guard.py`
  - Controle de acesso compartilhado com o Financeiro.
  - Tambem precisa tolerar ausencia de `st.secrets` local.

## Modelo de dados

### `reimbursement_categories`

Tabela de categorias do modulo.

Campos principais:

- `id`
- `name`
- `active`
- `sort_order`
- `created_at`

Categorias base criadas pela migration:

- `Alimentacao`
- `Hospedagem`
- `Transporte`
- `Combustivel`
- `Pedagio / estacionamento`
- `Material de campo`
- `Correios / cartorio`
- `Outros`

Categorias criadas durante testes:

- `Materiais de Campo`
- `ASO`
- `PCMSO`
- `Taxas e Licencas`
- `SSO`
- `ADM`

Observacao: houve problema de encoding no terminal Windows ao inserir
acentos. Quando precisar gravar texto acentuado via script, preferir
unicode escape ou validar depois no banco.

### `reimbursements`

Tabela principal.

Campos principais:

- `expense_date`: data da despesa.
- `due_date`: prazo de pagamento/reembolso.
- `collaborator_id`: referencia para `people`.
- `project_id`: referencia para `projects`.
- `category_id`: referencia para `reimbursement_categories`.
- `description`
- `amount`
- `status`
- `payment_date`
- `observations`
- `created_at`
- `updated_at`
- `created_by_email`
- `updated_by_email`

Status validos no banco:

- `PENDENTE`
- `APROVADO`
- `PAGO`
- `GLOSADO`

Regra atual:

- `PAGO` exige `payment_date`.
- `payment_date` e mantida como `NULL` se o status nao for `PAGO`.
- `due_date` e usado para calcular atraso na interface.

### `reimbursement_events`

Historico automatico por trigger.

Eventos:

- `CREATED`
- `STATUS_CHANGE`
- `DUE_DATE_CHANGE`
- `PAYMENT_DATE_CHANGE`
- `UPDATED`
- `ATTACHMENT_ADDED`
- `ATTACHMENT_REMOVED`

Aprendizado: quando novos eventos forem adicionados, lembrar de alterar o
`check constraint` de `event_type`.

### `reimbursement_attachments`

Metadados dos comprovantes.

Campos principais:

- `reimbursement_id`
- `file_name`
- `storage_bucket`
- `storage_path`
- `mime_type`
- `file_size`
- `uploaded_at`
- `uploaded_by_email`

Arquivos aceitos:

- PDF
- JPG/JPEG
- PNG

Bucket:

- `reimbursement-receipts`

O bucket e privado. A pagina gera signed URL temporaria para visualizacao.

### `v_reimbursements`

View consolidada usada pela pagina.

Ela resolve nomes de:

- colaborador;
- projeto;
- categoria;
- quantidade de comprovantes.

Aprendizado importante: para adicionar coluna no meio de uma view no
Postgres, nao usar somente `CREATE OR REPLACE VIEW`. Isso pode gerar erro
do tipo:

```text
cannot change name of view column "collaborator_id" to "due_date"
```

Nesses casos, usar:

```sql
drop view if exists public.v_reimbursements;
create view public.v_reimbursements as ...
```

## Logica visual e operacional

### Status manual

O campo `Status` e editavel e representa o estado administrativo.

Labels na UI:

- amarelo `Pendente`
- azul `Aprovado`
- verde `Pago`
- preto/cinza `Glosado`

No banco permanecem os valores sem icones:

- `PENDENTE`
- `APROVADO`
- `PAGO`
- `GLOSADO`

### Situacao calculada

O campo `Situacao` nao deve ser editado manualmente.

Ele e calculado na UI com a funcao `situation_for`.

Regra:

- Se `status == PAGO`: situacao = `Pago`.
- Se `status == GLOSADO`: situacao = `Glosado`.
- Se `due_date < hoje` e status nao for terminal: situacao = `Atrasado`.
- Se `status == APROVADO`: situacao = `Aprovado`.
- Caso contrario: situacao = `Pendente`.

Isso segue a ideia da aba `Laboratorio`, onde atraso e derivado de prazo, e
nao um status manual.

## Filtros

O filtro de periodo usa `expense_date`.

Aprendizado importante: o filtro inicial nao deve abrir apenas no dia atual
ou mes atual, porque dados de teste e passivos historicos podem ficar
invisiveis.

Regra atual:

- `De`: menor `expense_date` existente.
- `Ate`: maior `expense_date` existente.

Existe botao `Mostrar todos`, que reseta o periodo para esse intervalo.

Quando mudar defaults de widgets Streamlit, pode ser necessario mudar a
`key` do widget, pois o `session_state` preserva valores antigos.
Foi por isso que as chaves viraram:

- `reimb_filter_from_v2`
- `reimb_filter_to_v2`

## Indicadores atuais

Dashboards foram removidos temporariamente por decisao de produto.

Indicadores mantidos:

- total pendente de reembolso;
- total pago;
- quantidade de despesas pendentes;
- quantidade de despesas atrasadas.

O `ticket medio` foi removido.

Os indicadores usam icones nos labels da UI.

## Resumos tabulares

A pagina mantem tabelas simples de apoio:

- valor em aberto por colaborador;
- valor em aberto por projeto.

`Valor em aberto` considera:

- `PENDENTE`
- `APROVADO`

O indicador `Total pendente de reembolso`, por enquanto, considera somente
`PENDENTE`, conforme regra inicial definida pelo usuario.

## Exportacao

A exportacao inclui:

- Data da despesa
- Colaborador
- Projeto
- Nome do projeto
- Categoria
- Descricao
- Valor
- Status
- Situacao
- Prazo de pagamento
- Data do pagamento
- Observacoes
- Comprovantes
- Criado por
- Atualizado por

Dependencia para Excel:

- `xlsxwriter`

## Historico e comprovantes

Na parte inferior da pagina:

- selecionar lancamento;
- anexar comprovantes;
- visualizar comprovantes;
- excluir comprovantes;
- visualizar historico de alteracoes.

Historico e populado por triggers no banco.

## Acesso e seguranca

A aba usa o mesmo controle do Financeiro:

- `require_finance_access`
- `can_finance_write`

Usuarios sem permissao de escrita conseguem consultar, mas nao cadastrar,
editar ou excluir.

## Pipeline de deploy

Fluxo atual:

1. Alterar codigo/migrations localmente.
2. Rodar validacoes locais.
3. Commitar.
4. `git push origin main`.
5. Streamlit Cloud atualiza a aplicacao publicada.

Validacoes usadas:

```powershell
python -m py_compile app\pages\7_Reembolsos.py
python -m pytest
git diff --check
```

Link de producao:

```text
https://opyta-mvp-gestao-n6e7czbicppuukztppinze.streamlit.app/
```

## Pipeline de banco

Hoje as migrations ainda sao aplicadas manualmente pelo SQL Editor do
Supabase.

Importante:

- `SUPABASE_SERVICE_ROLE_KEY` permite operar dados via API, mas nao aplicar
  DDL/migrations.
- Para automatizar migrations no futuro, sera necessario configurar
  `DATABASE_URL`, senha Postgres ou `SUPABASE_ACCESS_TOKEN` com Supabase CLI.

Depois de migration que altera schema/view, incluir:

```sql
notify pgrst, 'reload schema';
```

Isso reduz problemas de schema cache do PostgREST.

## Problemas encontrados e aprendizados

### 1. `st.secrets` sem `secrets.toml`

Erro observado:

```text
No secrets found. Valid paths for a secrets.toml file...
```

Correcao:

- `supabase_client.py` agora tenta `st.secrets`, mas se falhar usa `.env`.
- `finance_guard.py` tambem tolera ausencia de `st.secrets`.

### 2. Login recusado

Quando aparece:

```text
Invalid login credentials
```

Isso significa que o Supabase foi acessado, mas recusou email/senha no
projeto configurado.

Nao confundir com erro de `.env` ou `secrets`.

### 3. View alterada no meio

Erro observado na migration v2:

```text
cannot change name of view column "collaborator_id" to "due_date"
```

Correcao:

- dropar e recriar a view.

### 4. Filtros esconderam os dados

Os dados estavam cadastrados, mas a tela abriu com periodo restrito a
`01/07/2026`.

Correcao:

- default do periodo passou a usar min/max dos lancamentos existentes;
- adicionado botao `Mostrar todos`;
- alteradas keys dos date inputs para resetar estado antigo.

### 5. Encoding no PowerShell

Textos acentuados inseridos via comando podem virar `?`.

Exemplos corrigidos:

- `Taxas e Licencas` com cedilha;
- `Locacao de veiculos` com acentos.

Pratica recomendada:

- validar com `unicode_escape`;
- usar unicode escapes em scripts quando necessario.

### 6. Ambiente local

A pasta tem `.venv`, mas ela nao estava completa para rodar Streamlit no
momento da implantacao.

O app local foi rodado com Python global/Anaconda.

Para estabilizar no futuro:

- recriar `.venv` limpa;
- instalar `requirements.txt`;
- evitar depender do ambiente global.

## Dados de teste inseridos

Foram inseridos 11 lancamentos de teste no Supabase.

Total geral:

```text
R$ 5.102,78
```

Mapeamentos usados:

- `Felipe` -> `Felipe Normando`
- `Yuri` -> `Yuri Martins`
- `Ana Clara` -> `Ana Clara`
- `WSP - Kinross` -> `WSPKIN001`
- `ADM` -> `OPYADM`

Projetos usados:

- `ITAGUA001`
- `WSPKIN001`
- `OPYADM`
- `PROPBX01`
- `BRACAR0001`

## Decisoes de produto atuais

- Dashboards ficam fora por enquanto.
- Tabela editavel e prioridade.
- Situacao deve ser clara e automatica.
- Atrasado nao deve ser status manual; deve ser derivado do prazo.
- Comprovantes continuam vinculados por lancamento.
- Exportacao deve refletir o que esta filtrado na tela.

## Pontos futuros

Possiveis melhorias:

- fluxo formal de aprovacao;
- perfis separados para solicitante, aprovador e financeiro;
- integracao com lancamentos financeiros quando status virar `PAGO`;
- dashboards retomados depois;
- tela de auditoria mais detalhada;
- automatizar migrations no CI/CD;
- cadastro/normalizacao melhor de categorias;
- anexos obrigatorios para certos tipos de despesa.
