# MONETTA

Gerenciador financeiro pessoal: quanto você tem, quanto já está comprometido e quanto pode gastar.

Arquitetura, modelo de dados e identidade visual: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

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

1. No [Google Cloud Console](https://console.cloud.google.com/apis/credentials), crie um **ID do cliente OAuth** do tipo **Aplicativo da Web**.
2. Em **URIs de redirecionamento autorizados**, adicione `http://localhost:4200/api/auth/google/callback`.
3. Copie o ID e o segredo para `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` no `.env`.
4. Reinicie o backend. O botão é ativado sozinho.

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
