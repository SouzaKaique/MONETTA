# Arquitetura do MONETTA

## Visão geral

```
Navegador (Angular 21 + Bootstrap 5)
        │  /api, cookie HttpOnly, header X-Monetta-Client
        ▼
API Flask ──► services/ (regras e cálculos) ──► SQLAlchemy ──► PostgreSQL 17
        │
        └──► Google / Apple (OpenID Connect, somente no login)
```

Todo cálculo financeiro acontece no backend. O frontend apenas formata valores para exibição.

## Estrutura

```
backend/
  app/
    api/         rotas HTTP: validação de entrada e formato da resposta
    services/    regras de negócio: dashboard, segurança, login social
    models/      tabelas (user.py: identidade; finance.py: dados financeiros)
  migrations/    histórico do banco (Alembic)
  tests/
frontend/src/app/
  core/          sessão, tema, HTTP, formatação, navegação
  layout/        sidebar, barra inferior e avatar
  pages/         uma pasta por área
scripts/db.ps1   banco privado de desenvolvimento
```

Cada novo módulo segue o mesmo caminho: modelo, migração, serviço, testes, rota, página.

## Decisões

| Decisão | Motivo |
|---|---|
| Dados sempre filtrados por `user_id` | Cada conta enxerga apenas os próprios dados |
| Dinheiro em `NUMERIC(14,2)`, trafegado como string | Evita erro de arredondamento de ponto flutuante |
| `competence_date` e `paid_on` separados | Mantém competência e fluxo de caixa distintos |
| Indicador sem módulo pronto retorna `null` | Mostrar R$ 0,00 seria uma informação falsa |
| Sessão em cookie HttpOnly, com hash no banco | Sessão revogável e token inacessível por JavaScript |
| Senhas com Argon2 | Algoritmo atual recomendado para hash de senha |
| Header `X-Monetta-Client` em escritas | Proteção contra CSRF |
| Angular 21 | O Angular 22 exige Node 24.15+, e a máquina usa 24.12 |
| Python 3.14 em `backend/.venv` | Não interfere nas outras versões instaladas |
| PostgreSQL próprio na porta 5433 | Não altera o serviço já instalado; basta trocar `DATABASE_URL` para outro servidor |

## Autenticação

- **E-mail e senha:** mínimo de 10 caracteres; 5 erros seguidos bloqueiam a conta por 15 minutos.
- **Google e Apple:** o backend troca o código por um `id_token` e valida assinatura, emissor,
  audiência, validade e nonce. O `state` é de uso único e fica preso ao navegador de origem.
- **Mesma conta com provedores diferentes:** vincula pelo e-mail somente se ele já foi confirmado
  por um provedor. Uma conta criada com senha não é vinculada automaticamente, porque o cadastro
  por senha ainda não prova a posse do e-mail.

Ainda não existem confirmação de e-mail nem recuperação de senha, pois ambas precisam de um
serviço de envio de e-mail.

## Modelo de dados

**Etapa 1:** `users`, `user_identities`, `user_sessions`, `oauth_states`, `app_settings`,
`accounts`, `categories`, `transactions`.

**Etapa 2:** `recurrences`, `recurrence_amounts`, `recurrence_skips`, `transfers`.

**Etapa 3:** `credit_cards`, `invoices`, `card_purchases`, `installments`, `invoice_payments`.

**Nas próximas etapas, por migração:**

| Etapa | Tabelas |
|---|---|
| 4 | `debts`, `debt_payments` |
| 5 | `budgets`, `notifications`, `financial_events` |
| 6 | `wishlist_items`, `savings_goals`, `goal_contributions` |

## Regras do saldo

- **Saldo atual:** abertura das contas ativas + entradas confirmadas − saídas confirmadas, até hoje.
  Movimentos anteriores à data de abertura ficam de fora, porque o saldo de abertura já os contém.
- **Disponível para gastar:** saldo atual − despesas pendentes até o fim do mês, incluindo atrasadas
  − mínimo de segurança, nunca abaixo de zero. Receita futura nunca entra nesta conta.
- **Renda comprometida:** despesas do mês ÷ renda do mês. Aqui o previsto entra, apenas como medida.
- **Dinheiro livre:** renda prevista − despesas do mês, por competência. Não é saldo em conta.
- **Transferências:** mudam o saldo de cada conta, mas não o total, nem receitas ou despesas.
- **Saldo real:** informado pelo usuário só para comparar; nunca entra em cálculo.

## Recorrências

- **Geração:** antes de cada leitura, o backend cria as ocorrências que faltam. Sempre cobre o mês
  seguinte e vai até 24 meses à frente quando um mês futuro é consultado. Uma constraint impede
  ocorrências duplicadas em requisições simultâneas.
- **Reajuste:** cada valor tem um mês de início (`recurrence_amounts`). Só muda pendências desse mês
  em diante; lançamentos confirmados e valores editados à mão são preservados. Valor retroativo é
  recusado.
- **Excluir uma ocorrência:** fica registrado em `recurrence_skips`, para ela não reaparecer.
- **Pausar:** remove as pendências a partir de hoje. Ao reativar, os meses da pausa não são criados.
- **Excluir a regra:** remove as pendências e mantém o que já foi confirmado.

## Cartões

- **Despesa uma única vez:** cada parcela conta como despesa no mês de vencimento da sua fatura.
  Essa é a data de contabilização; a data da compra fica guardada à parte.
- **Pagamento de fatura:** reduz o saldo da conta e o que falta pagar. Nunca entra em despesas.
- **Disponível para gastar:** desconta o que falta pagar das faturas que vencem até o fim do mês.
  Parcelas futuras comprometem os meses delas, e não o mês atual.
- **Fatura:** identificada pelo mês de vencimento, com as datas gravadas. Mudar os dias do cartão
  só afeta faturas que ainda não fecharam.
- **Em qual fatura a compra cai:** compra até o dia do fechamento entra nela; depois, na seguinte.
  Como isso varia entre bancos, a compra aceita escolher a primeira fatura.
- **Limite usado:** todas as parcelas ainda não pagas, inclusive futuras.
- **Compras antigas:** parcelas informadas como já pagas ficam sem fatura, fora de despesas e limite.
- **Pagamento parcial:** o restante fica na própria fatura. Juros do rotativo não são calculados.
- **Idempotência:** compras, pagamentos e lançamentos aceitam `Idempotency-Key`. Em envios
  simultâneos, a constraint barra o segundo e a resposta é o registro já criado.

## Identidade visual

- **Tipografia:** Fraunces nos títulos e no valor principal; Geist na interface e nos números.
- **Cores:** definidas como tokens em `frontend/src/styles.css`. Verde escuro como identidade,
  off-white e grafite como base, vermelho discreto apenas para alertas.
- **Tela inicial:** um único bloco em destaque responde "quanto posso gastar"; o restante apoia.
- **Gráficos:** as cores foram validadas para daltonismo nos dois temas, e os valores também
  existem em tabela para leitores de tela.
