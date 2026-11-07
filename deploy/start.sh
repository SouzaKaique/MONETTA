#!/bin/sh
# Aplica as migrações pendentes e inicia o servidor.
set -eu
flask db upgrade
exec python serve.py
