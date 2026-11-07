#!/bin/sh
# Backup diário do banco. Mantém os 14 mais recentes em ./backups, no mesmo servidor:
# copie esses arquivos para outro lugar, porque um disco perdido leva os dois juntos.
set -u
umask 077
KEEP=14
INTERVAL=86400

while true; do
  file="/backups/monetta-$(date +%Y-%m-%d-%H%M).dump"
  # Grava em arquivo temporário: um backup interrompido nunca parece completo.
  if pg_dump -h db -U monetta -F c -f "$file.tmp" monetta; then
    mv "$file.tmp" "$file"
    ls -1t /backups/monetta-*.dump | tail -n +$((KEEP + 1)) | xargs -r rm -f
    echo "Backup salvo: $file"
  else
    rm -f "$file.tmp"
    echo "Falha no backup" >&2
  fi
  sleep "$INTERVAL"
done
