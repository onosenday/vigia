#!/bin/sh
# Forced-command para hosts Debian/OMV.
# Se instala en /usr/local/bin/ y se referencia desde authorized_keys.
# La entrada SSH se ignora: refresca índices con sudo y emite el conteo en JSON.
# Requiere en el host:  updexp ALL=(root) NOPASSWD: /usr/bin/apt-get update
set -u
sudo /usr/bin/apt-get update -qq >/dev/null 2>&1 || true
sim="$(apt-get -s -o Debug::NoLocking=true upgrade 2>/dev/null)"
total="$(printf '%s\n' "$sim"   | grep -c '^Inst')"
security="$(printf '%s\n' "$sim" | grep '^Inst' | grep -ciE 'security')"
printf '{"updates":%s,"security":%s,"checked":"%s"}\n' \
  "${total:-0}" "${security:-0}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
