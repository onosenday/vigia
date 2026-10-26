#!/bin/sh
# Lanza el servidor estático y el bucle de recolección.
set -eu
mkdir -p /www
[ -f /www/updates.json ] || echo '{}' > /www/updates.json

# Servidor HTTP estático (httpd de busybox-extras) sirviendo /www en :PORT
busybox-extras httpd -f -p "${PORT:-8099}" -h /www &

# Bucle de sondeo cada INTERVAL segundos
while :; do
  /usr/local/bin/collect.sh || true
  sleep "${INTERVAL:-3600}"
done
