# Publicar o MONETTA

O pacote sobe quatro partes: o aplicativo, o banco de dados, o backup diário e a entrada com HTTPS.
Tudo roda em Docker, então o processo é o mesmo em qualquer máquina Linux.

## Escolha o caminho

| | Servidor na nuvem | Seu computador com túnel |
|---|---|---|
| **Fica no ar** | O tempo todo | Só com o computador ligado |
| **Você precisa de** | Servidor Linux e domínio | Docker, conta na Cloudflare e domínio nela |
| **Portas abertas** | 80 e 443 | Nenhuma |
| **Dados ficam** | No servidor contratado | No seu computador |
| **Indicado para** | Uso diário pelo celular | Testar antes de contratar um servidor |

Para o registro rápido pelo iPhone funcionar a qualquer hora, prefira o servidor na nuvem.

## Caminho 1: servidor na nuvem

Use um servidor Linux com pelo menos 2 GB de memória, porque compilar o app consome bastante.

### 1. Aponte o domínio

No painel do domínio, crie um registro **A** do seu endereço, como `financas.seudominio.com.br`,
para o IP do servidor. Espere ele propagar antes de continuar: sem isso, o certificado não é emitido.

### 2. Prepare o servidor

Conectado ao servidor, instale o Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Libere somente as portas 22, 80 e 443 no firewall. O banco de dados não usa nenhuma porta pública.

### 3. Suba o MONETTA

```bash
git clone https://github.com/SouzaKaique/MONETTA.git
```

```bash
cd MONETTA
```

```bash
sh deploy/setup.sh
```

```bash
docker compose --env-file .env.production up -d --build
```

O certificado HTTPS é obtido sozinho no primeiro acesso.

### 4. Crie sua conta

Abra o endereço e crie a conta **logo em seguida**. Com `REGISTRATION_OPEN=0`, a primeira conta é
aceita e o cadastro fecha para todas as outras. Para permitir novas contas, troque para `1` no
`.env.production` e rode de novo o comando `up` do passo anterior.

## Caminho 2: seu computador com túnel

1. Tenha um domínio gerenciado pela Cloudflare.
2. No painel **Zero Trust**, abra **Networks → Tunnels** e crie um túnel do tipo **Cloudflared**.
3. Copie o token mostrado na tela.
4. Em **Public Hostname**, informe seu endereço e aponte o serviço para `http://app:5000`.
5. Na pasta do projeto, rode `sh deploy/setup.sh` e escolha a opção **2**. No Windows, use o Git Bash.
6. Suba com:

```bash
docker compose --env-file .env.production up -d --build
```

## Login com Google

1. No [Google Cloud Console](https://console.cloud.google.com/apis/credentials), crie um
   **ID do cliente OAuth** do tipo **Aplicativo da Web**.
2. Em **URIs de redirecionamento autorizados**, informe
   `https://SEU-ENDERECO/api/auth/google/callback`.
3. Preencha `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` no `.env.production`.
4. Rode de novo o comando `up`.

Teste o primeiro login você mesmo: este fluxo ainda não rodou contra o Google real.

## Login com Apple

Exige conta paga do Apple Developer Program.

1. Crie um **App ID** com *Sign in with Apple* e um **Services ID**.
2. No Services ID, registre seu domínio e o retorno `https://SEU-ENDERECO/api/auth/apple/callback`.
3. Crie uma **Key** com *Sign in with Apple* e baixe o arquivo `.p8`.
4. Salve-o na pasta `secrets/`, como `secrets/apple.p8`.
5. No `.env.production`, preencha `APPLE_CLIENT_ID` (o Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`
   e `APPLE_PRIVATE_KEY_PATH=/app/secrets/apple.p8`.
6. Rode de novo o comando `up`.

## No dia a dia

### Atualizar para uma nova versão

```bash
git pull
```

```bash
docker compose --env-file .env.production up -d --build
```

As migrações do banco são aplicadas sozinhas ao iniciar. Faça um backup antes de atualizar.

### Ver se está tudo bem

```bash
docker compose --env-file .env.production ps
```

```bash
docker compose --env-file .env.production logs --tail 50 app
```

### Esqueci a senha

Ainda não há recuperação por e-mail. Pelo servidor:

```bash
docker compose --env-file .env.production exec app flask reset-password seu@email.com
```

O comando também destrava a conta e encerra todas as sessões.

### Celular perdido

Em **Perfil**, use **Sair de todos os dispositivos**. Em **Configurações → Integrações**, revogue o
token do atalho.

## Backups

O serviço `backup` copia o banco uma vez por dia para a pasta `backups/` e guarda os 14 mais recentes.

**Copie esses arquivos para outro lugar com frequência.** Eles ficam no mesmo disco do banco: se o
servidor for perdido, os backups vão junto. Eles contêm seus dados sem criptografia.

Pelo seu computador, troque o endereço do servidor:

```bash
scp -r usuario@SEU-SERVIDOR:MONETTA/backups ./backups-monetta
```

### Restaurar

```bash
docker compose --env-file .env.production stop app
```

```bash
docker compose --env-file .env.production exec -T db pg_restore -U monetta -d monetta --clean --if-exists < backups/ARQUIVO.dump
```

```bash
docker compose --env-file .env.production start app
```

Isso substitui todos os dados pelos do backup.

## Antes de usar com dados reais

- [ ] O endereço abre com cadeado, e `http://` redireciona para `https://`.
- [ ] A primeira conta é a sua, e uma segunda tentativa de cadastro é recusada.
- [ ] `docker compose ps` mostra `app` como `healthy`.
- [ ] Existe um arquivo em `backups/`, e ele foi copiado para fora do servidor.
- [ ] Você testou uma restauração pelo menos uma vez.
- [ ] O `.env.production` tem cópia em um gerenciador de senhas. Sem ele, os backups continuam
      válidos, mas as configurações precisam ser refeitas.
