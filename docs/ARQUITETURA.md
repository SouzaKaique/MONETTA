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

**Etapa 4:** `debts`, `debt_payments`.

**Etapa 5:** `budgets`, `recovery_plans`, `notifications`. Os eventos do calendário são calculados
a partir dos módulos, por isso não existe tabela `financial_events`: uma cópia poderia divergir.

**Etapa 6:** `wishlist_items`, `savings_goals`, `goal_contributions`, `wishlist_images`.

**Etapa 7:** `api_tokens`.

## Regras do saldo

- **Saldo atual:** abertura das contas ativas + entradas confirmadas − saídas confirmadas, até hoje.
  Movimentos anteriores à data de abertura ficam de fora, porque o saldo de abertura já os contém.
- **Disponível para gastar:** com salário cadastrado, é o mesmo valor do simulador até o próximo
  salário. Sem salário: saldo atual − pendências do mês, inclusive atrasadas − faturas − dívidas
  combinadas − reserva − mínimo de segurança. Nunca fica abaixo de zero nem conta receita futura.
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

## Dívidas

- **Pagamento:** reduz o saldo devedor e, se houver conta, o dinheiro em conta. Não é despesa.
  Pagamentos antigos podem ficar sem conta: atualizam a dívida sem mexer no saldo de hoje.
- **Valor combinado:** o que falta pagar no mês reduz o disponível para gastar. Conta como
  1 pagamento mensal, 2 quinzenais ou 4 semanais, limitado ao saldo da dívida.
- **Renda comprometida e dinheiro livre:** incluem pagamentos de dívidas, além das despesas.
- **Situação:** calculada pelo saldo: pendente, em pagamento ou quitada.
- **Juros:** o saldo real só muda com pagamentos. Juros aparecem como estimativa no simulador.
- **Estratégias:** bola de neve (menor saldo), avalanche (maior juro; sem juros, por último),
  vencimento, importância e ordem manual.
- **Simulador:** primeiro pagamento no mês seguinte. A cada mês aplica os juros e paga na ordem
  escolhida; o que sobra ao quitar uma dívida passa para a próxima. O extra entra no 1º mês.
- **Limite recomendado:** renda prevista − despesas do mês − mínimo de segurança. Acima disso,
  o cenário aparece como não recomendado, mas continua disponível.

## Planejamento

- **Até o próximo salário:** saldo confirmado − pendências antes do salário, inclusive atrasadas −
  restante das faturas que vencem antes dele − dívidas do mês − reserva − mínimo de segurança.
  O limite diário divide esse valor pelos dias restantes. O que vence no dia do salário fica fora.
- **Orçamento:** o limite vale a partir de um mês; meses anteriores não mudam. Zero remove o limite.
- **Distribuição da renda:** essenciais e variáveis (lançamentos), cartões (parcelas), dívidas
  (pagas e combinadas), reserva e dinheiro livre. Cada valor aparece em um único grupo.
- **Reserva mensal:** intenção de guardar. Reduz o disponível, mas não é despesa. O que for guardado
  na wishlist no mês abate da reserva, para não descontar duas vezes.
- **Calendário:** reúne lançamentos, fechamentos, vencimentos, dívidas e a meta do Modo Recuperação.

## Modo Recuperação

- Orienta, sem bloquear nenhuma decisão.
- Enquanto ativo, o mês reserva o maior valor entre o combinado e o valor mensal definido, e vale
  a maior reserva mínima entre o perfil e o modo.
- A dívida inicial é gravada na primeira ativação. Desativar e reativar preserva dados e histórico.
- Dívidas prioritárias vêm antes das demais; dentro de cada grupo vale a estratégia.
- Compra não planejada: simulada como se o valor saísse do que iria para as dívidas.

## Alertas e notificações

- Dashboard e notificações usam a mesma origem. O dashboard mostra a situação atual; a notificação
  guarda o histórico e cada chave é gerada uma única vez.
- As preferências definem limites e silenciam grupos de avisos.

## Wishlist

- **Valor guardado:** não é despesa nem movimenta conta. O dinheiro continua no banco, e o saldo
  calculado segue igual ao real; o valor apenas sai do disponível enquanto a meta estiver aberta.
- **Comprei:** cria a despesa uma única vez, à vista ou em parcelas, e libera o guardado.
- **Desisti:** libera o guardado e preserva o histórico.
- **Desfazer compra:** remove a despesa criada e volta a separar o guardado. É recusado se houver
  pagamento em fatura da compra, para não apagar dinheiro que já saiu da conta.
- **Previsão:** usa o valor mensal definido ou, sem ele, a média guardada nos últimos 90 dias.
- **Posso comprar?:** cada critério vira um item explicado, e o resultado é o pior deles. Considera
  saldo, atrasos, comprometimento, limite do cartão, parcelas, dívidas, reserva e orçamento.
  O guardado para o item conta a favor dele. Usar mais da metade do disponível pede atenção.
- **Modo Recuperação:** pagar com dinheiro não guardado vira "melhor adiar", e o valor já guardado
  pede atenção. A wishlist perde o orçamento planejado no mês. Nada é bloqueado.
- **Imagens:** envio de PNG, JPEG ou WEBP de até 2 MB, validado pelo conteúdo e servido só ao dono;
  ou endereço HTTPS externo. Links aceitam apenas HTTP e HTTPS.

## Relatórios, exportação e backup

- **Relatórios:** por mês, trimestre ou ano. Usam a mesma série mensal do dashboard, então os dois
  nunca divergem. Pagar uma fatura não altera nenhum total do relatório.
- **Economia:** receitas confirmadas − despesas − pagamentos de dívidas, sobre as receitas.
- **CSV:** separado por ponto e vírgula, com BOM e vírgula decimal, para o Excel em português.
  Textos que começam com `=`, `+`, `-` ou `@` recebem um apóstrofo para não virarem fórmula.
- **Backup do usuário:** JSON com todos os dados financeiros, sem senha, sessões nem tokens.
- **Restauração:** só em conta vazia. Aceita apenas colunas conhecidas, gera novos identificadores
  e recusa referências que não estejam no próprio arquivo. Tudo ou nada, em uma transação.
- **Backup do banco:** `scripts/backup.ps1` faz o `pg_dump` e mantém os 14 mais recentes.

## Integrações

- Token com 256 bits, mostrado uma vez e salvo só como hash. Revogável e com escopo restrito: ele
  não autentica nenhuma rota além de `/api/integrations/`.
- Limite de 30 requisições por minuto por token, e até 10 tokens ativos por usuário.
- Repetição bloqueada pela chave de idempotência, gerada pelo cliente ou pelo conteúdo do envio.

## PWA

- O service worker guarda só os arquivos do aplicativo. `dataGroups` fica vazio: dados financeiros
  nunca vão para o cache do aparelho, e o app não mostra informações sem conexão.
- `/api/` fica fora das navegações do service worker. Sem isso, ele responderia com o app às
  rotas de login social e aos downloads.

## Segurança

- **Política de conteúdo:** sem scripts inline ou de terceiros. Por isso o tema inicial fica em
  `theme-init.js` e o `inlineCritical` do Angular está desligado: ele usa `onload` no HTML.
- **Cabeçalhos:** `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` e HSTS em HTTPS.
- **Limites:** login 20 e cadastro 10 por minuto por endereço, além do bloqueio por conta.
  Ficam em memória, então valem para um processo e zeram ao reiniciar.
- **CSRF e CORS:** header exigido nas escritas da sessão; a API não libera outras origens. A rota
  de integrações dispensa o header porque não usa cookie.

## Publicação

- **Pacote:** Docker Compose com app, PostgreSQL, backup diário e uma entrada à escolha:
  Caddy, com certificado automático, ou túnel da Cloudflare.
- **Redes:** o banco fica em uma rede sem saída para a internet. Só a entrada publica portas.
- **Imagem:** sem segredos, sem testes, com usuário sem privilégios e disco somente leitura.
- **IP real:** `TRUSTED_PROXY` autoriza o servidor a ler `X-Forwarded-For`. Sem ele, o cabeçalho é
  ignorado, porque qualquer cliente poderia falsificá-lo para escapar dos limites.
- **Início seguro:** com `APP_ENV=production`, o servidor recusa subir sem HTTPS ou com segredo fraco.
- **Cadastro:** com `REGISTRATION_OPEN=0`, só a primeira conta é aceita, inclusive por login social.
- **Versões:** `requirements.lock` e `package-lock.json` fixam as dependências da imagem.

## Identidade visual

- **Tipografia:** Fraunces nos títulos e no valor principal; Geist na interface e nos números.
- **Cores:** definidas como tokens em `frontend/src/styles.css`. Verde escuro como identidade,
  off-white e grafite como base, vermelho discreto apenas para alertas.
- **Tela inicial:** um único bloco em destaque responde "quanto posso gastar"; o restante apoia.
- **Gráficos:** as cores foram validadas para daltonismo nos dois temas, e os valores também
  existem em tabela para leitores de tela.
