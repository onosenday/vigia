#!/bin/sh
# Forced-command para Synology DSM.
#   dsm_version : versión DSM instalada (SIEMPRE), p.ej. "DSM 7.2.2-72806 Update 3"
#                 — se lee de /etc.defaults/VERSION (world-readable, sin sudo).
#   dsm_update  : 1 si synoupgrade --check ve una actualización, 0 si no.
# Requiere en el NAS:  updexp ALL=(root) NOPASSWD: /usr/syno/bin/synoupgrade
# Nota: --check detecta minor/patches, NO saltos de versión mayor (DSM 6->7).
set -u

# --- versión instalada (siempre disponible, sin sudo) ----------------------
VF=/etc.defaults/VERSION
kv() { sed -n "s/^$1=\"\(.*\)\"\$/\1/p" "$VF" 2>/dev/null | head -1; }
prod="$(kv productversion)"   # p.ej. 7.2.2
build="$(kv buildnumber)"     # p.ej. 72806
small="$(kv smallfixnumber)"  # p.ej. 3 (puede faltar o ser 0)
ver="DSM ${prod:-?}-${build:-?}"
[ -n "$small" ] && [ "$small" != "0" ] && ver="$ver Update $small"

# --- ¿hay actualización pendiente? -----------------------------------------
chk="$(sudo /usr/syno/bin/synoupgrade --check 2>/dev/null || sudo synoupgrade --check 2>/dev/null)"
if printf '%s\n' "$chk" | grep -qi 'available update:'; then avail=1; else avail=0; fi

ver="$(printf '%s' "$ver" | sed 's/\\/\\\\/g; s/"/\\"/g')"   # escapar para JSON
printf '{"dsm_update":%s,"dsm_version":"%s","checked":"%s"}\n' \
  "$avail" "$ver" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
