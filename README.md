# MONETTA

Gerenciador financeiro pessoal: quanto você tem, quanto já está comprometido e quanto pode gastar.

Arquitetura, modelo de dados e identidade visual: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Usar no dia a dia

Dê dois cliques em **`MONETTA.cmd`**, na pasta do projeto. Ele liga o banco, prepara o app e abre
**http://monetta.localhost** no navegador. Deixe a janela aberta enquanto usa e feche para encerrar.

- O endereço funciona só neste computador.
- No Chrome ou no Edge, dá para instalar o MONETTA como aplicativo pelo ícone na barra de endereço.
- Depois de mudar o código, o atalho recompila sozinho. Para forçar: `MONETTA.cmd -Recompilar`.

Requisitos: os mesmos de **Rodar localmente**, com a primeira vez já feita, e a porta 80 livre.

## Rodar localmente

Requisitos: Node 24, Python 3.14 e PostgreSQL 17 instalado.

Primeira vez (cria o banco privado na porta 5433 e o `.env`):

```powershell
.\scripts\db.ps1 init
cd backend; .\.venv\Scripts\python -m flask --app wsgi.py db upgrade
```

No dia a dia, em três terminais:

```powershell
.\scripts\db.ps1 start
```

```powershell
cd backend; .\.venv\Scripts\python -m flask --app wsgi.py run --port 5000 --debug
```

```powershell
cd frontend; npm start
```

Abra http://localhost:4200.

## Publicar

O guia completo está em [docs/PUBLICACAO.md](docs/PUBLICACAO.md). O app instalável, o service
worker e o atalho do iPhone exigem HTTPS.

## Instalar no celular

Abra o endereço publicado. No iPhone, use o Safari: **Compartilhar → Adicionar à Tela de Início**.
No Android, use **Instalar app** no Chrome.

## Atalho do iPhone

Veja [docs/ATALHO-IPHONE.md](docs/ATALHO-IPHONE.md).

## Backup

- **Pelo app:** **Configurações → Backup** baixa um arquivo com seus dados.
- **Banco completo, em desenvolvimento:** rode o script abaixo. Publicado, o backup é diário e automático.

```powershell
.\scripts\backup.ps1
```

## Testes

```powershell
cd backend; .\.venv\Scripts\python -m pytest
```

```powershell
cd frontend; npx ng test --watch=false
```

## Configurar login com Google

É gratuito e não pede cartão. Basta uma conta Google.

1. Abra o [Google Cloud Console](https://console.cloud.google.com/) e crie um projeto (ex.: `MONETTA`).
2. Em **APIs e serviços > Tela de consentimento OAuth** (ou **Google Auth Platform**), escolha
   **Externo**, preencha o nome do app e o seu e-mail. Em **Público-alvo**, adicione como
   **usuários de teste** os e-mails que vão entrar no MONETTA (até 100; não precisa publicar o app).
3. Em **Credenciais > Criar credenciais > ID do cliente OAuth**, tipo **Aplicativo da Web**.
   Em **URIs de redirecionamento autorizados**, adicione exatamente:
   - `http://localhost/api/auth/google/callback` (uso com o `MONETTA.cmd`)
   - `http://localhost:4200/api/auth/google/callback` (só se você desenvolve com `ng serve`)
4. Copie o **ID do cliente** e a **chave secreta** para `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` no `.env`.
5. Feche a janela do MONETTA e abra de novo. O botão do Google é ativado sozinho.

O Google não aceita `monetta.localhost` como retorno, por isso o retorno chega em `localhost`
e o servidor repassa para `monetta.localhost` (variável `OAUTH_REDIRECT_BASE`, que o `MONETTA.cmd` já define).

Quem já tem conta com senha pode ligar o Google em **Perfil > Formas de entrar > Vincular**,
mesmo que o e-mail do Google seja outro. Depois disso, entra pelos dois jeitos.

## Recuperar a senha

Na tela de login, **Esqueci minha senha** gera um link que vale por 30 minutos e só pode ser usado uma vez.
Ao criar a nova senha, todas as sessões abertas são encerradas.

- **Sem configurar nada**, o link aparece na janela do `MONETTA.cmd` (a janela preta). Copie e abra no navegador.
- **Para receber por e-mail** com uma conta Gmail: ative a verificação em duas etapas, crie uma
  [senha de app](https://myaccount.google.com/apppasswords) e preencha no `.env`:
  `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=seu@gmail.com`, `SMTP_PASSWORD=` (a senha de app)
  e `SMTP_FROM=MONETTA <seu@gmail.com>`.

Se esquecer a senha e não tiver acesso ao e-mail, no próprio computador:
`cd backend` e `.venv\Scripts\python -m flask --app wsgi.py reset-password seu@email.com`.

## Configurar login com Apple

A Apple exige uma conta paga do Apple Developer Program e um domínio com HTTPS:
ela não aceita `localhost` como endereço de retorno.

1. No portal da Apple, crie um **App ID** com *Sign in with Apple* e um **Services ID**.
2. No Services ID, registre o domínio e o retorno `https://SEU-DOMINIO/api/auth/apple/callback`.
3. Crie uma **Key** com *Sign in with Apple* e baixe o arquivo `.p8`. Guarde-o fora do projeto.
4. Preencha no `.env`: `APPLE_CLIENT_ID` (Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`,
   `APPLE_PRIVATE_KEY_PATH` e `PUBLIC_URL=https://SEU-DOMINIO`.

## Dados e segurança

`.env` e `.pgdata/` guardam segredos e dados financeiros e não devem ser versionados nem compartilhados.
