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

**Na Etapa 1:** `users`, `user_identities`, `user_sessions`, `oauth_states`, `app_settings`,
`accounts`, `categories`, `transactions`.

**Nas próximas etapas, por migração:**

| Etapa | Tabelas |
|---|---|
| 2 | `recurrences` |
| 3 | `credit_cards`, `invoices`, `card_purchases`, `installments` |
| 4 | `debts`, `debt_payments` |
| 5 | `budgets`, `notifications`, `financial_events` |
| 6 | `wishlist_items`, `savings_goals`, `goal_contributions` |

## Regras do saldo

- **Saldo atual:** abertura das contas + entradas confirmadas − saídas confirmadas, até hoje.
- **Disponível para gastar:** saldo atual − despesas pendentes do mês − mínimo de segurança, nunca
  abaixo de zero. Receita futura nunca entra nesta conta.
- **Renda comprometida:** despesas do mês ÷ renda do mês. Aqui o previsto entra, apenas como medida.

## Identidade visual

- **Tipografia:** Fraunces nos títulos e no valor principal; Geist na interface e nos números.
- **Cores:** definidas como tokens em `frontend/src/styles.css`. Verde escuro como identidade,
  off-white e grafite como base, vermelho discreto apenas para alertas.
- **Tela inicial:** um único bloco em destaque responde "quanto posso gastar"; o restante apoia.
- **Gráficos:** as cores foram validadas para daltonismo nos dois temas, e os valores também
  existem em tabela para leitores de tela.
