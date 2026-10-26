#!/bin/sh
# updates-exporter · recolector central.
# Sondea cada host por SSH; el host responde su JSON vía forced-command
# (la cadena que enviamos como "comando" se ignora: lo decide authorized_keys).
#
# Config por variables de entorno:
#   HOSTS_SPEC="label:ip:port:user[:segundos]  ..."
#       un token por host. El tipo (apt/syno) lo determina el script
#       forced-command instalado en el host, no este recolector. El 5.º campo
#       opcional es el intervalo mínimo de ese host: entre sondeos se reutiliza
#       su último JSON (p. ej. 6 h en un NAS cuyos discos hibernan).
#   KEY  (def. /keys/id_ed25519)  clave privada dedicada, montada solo-lectura
#   OUT  (def. /www/updates.json) fichero agregado que sirve el httpd
set -u
KEY="${KEY:-/keys/id_ed25519}"
OUT="${OUT:-/www/updates.json}"
CACHE="${CACHE:-/www/cache}"
mkdir -p "$CACHE"
SSHOPTS="-i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=5"

tmp="$(mktemp)"
{
  printf '{'
  printf '"_checked":"%s"' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for spec in $HOSTS_SPEC; do
    label="${spec%%:*}"; r="${spec#*:}"
    ip="${r%%:*}";       r="${r#*:}"
    port="${r%%:*}";     r="${r#*:}"
    user="${r%%:*}";     every=0
    [ "$user" != "$r" ] && every="${r#*:}"
    now="$(date +%s)"; last="$(cat "$CACHE/$label.ts" 2>/dev/null || echo 0)"
    if [ "$every" -gt 0 ] && [ $((now - last)) -lt "$every" ] && [ -s "$CACHE/$label.json" ]; then
      j="$(cat "$CACHE/$label.json")"    # aún dentro de su intervalo: último JSON bueno
    else
      # El forced-command del host ignora el argumento "x" y emite su JSON.
      j="$(ssh $SSHOPTS -p "$port" "$user@$ip" x 2>/dev/null)"
      case "$j" in
        '{'*'}') printf '%s' "$j" > "$CACHE/$label.json"; echo "$now" > "$CACHE/$label.ts" ;;
        *)       j='{"error":"unreachable"}' ;;   # sin caché: se reintenta en la próxima vuelta
      esac
    fi
    printf ',"%s":%s' "$label" "$j"
  done
  printf '}\n'
} > "$tmp"
mv "$tmp" "$OUT"
