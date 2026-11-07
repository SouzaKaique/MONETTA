#!/bin/sh
# Cria o .env.production com senhas aleatórias. Rode uma vez, na pasta do projeto.
set -eu

if [ -f .env.production ]; then
  echo "O arquivo .env.production já existe. Nada foi alterado."
  exit 1
fi

printf "Endereço do site (exemplo: financas.seudominio.com.br): "
read -r domain
domain=$(printf '%s' "$domain" | sed -e 's#^https\?://##' -e 's#/*$##')
if [ -z "$domain" ]; then
  echo "Informe um endereço."
  exit 1
fi

printf "Entrada: 1 para servidor com portas abertas, 2 para túnel da Cloudflare [1]: "
read -r mode
profile=caddy
tunnel=""
if [ "${mode:-1}" = "2" ]; then
  profile=tunnel
  printf "Token do túnel: "
  read -r tunnel
fi

umask 077
cat > .env.production <<EOF
DOMAIN=$domain
COMPOSE_PROFILES=$profile
DB_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
TUNNEL_TOKEN=$tunnel

# 0: só a primeira conta pode se cadastrar. 1: qualquer pessoa pode criar conta.
REGISTRATION_OPEN=0

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY_PATH=
EOF

mkdir -p backups secrets
echo "Pronto. Agora rode: docker compose --env-file .env.production up -d --build"
