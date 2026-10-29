#!/bin/sh
# Forced-command para hosts Debian/OMV/Proxmox (formato v2, docs/actualizaciones.md).
# Se instala en /usr/local/bin/ y se referencia desde authorized_keys.
# La entrada SSH se ignora: refresca índices con sudo y emite en JSON el conteo de actualizaciones,
# la versión del sistema (os-release) y la de los productos que lleva encima (OMV, Proxmox VE).
# Requiere en el host:  updexp ALL=(root) NOPASSWD: /usr/bin/apt-get update
set -u
sudo /usr/bin/apt-get update -qq >/dev/null 2>&1 || true
sim="$(apt-get -s -o Debug::NoLocking=true upgrade 2>/dev/null)"
total="$(printf '%s\n' "$sim"   | grep -c '^Inst')"
security="$(printf '%s\n' "$sim" | grep '^Inst' | grep -ciE 'security')"

# os-release se lee, no se ejecuta; solo caracteres de versión (nada que escapar en JSON)
osr() { sed -n "s/^$1=//p" /etc/os-release 2>/dev/null | head -1 | tr -d '"' | tr -cd 'A-Za-z0-9._+~-'; }

productos=""
producto() {  # <producto del catálogo de vigia> <paquete>
  s="$(dpkg-query -W -f='${db:Status-Abbrev}${Version}' "$2" 2>/dev/null)"
  case "$s" in
    "ii "*) v="$(printf '%s' "${s#ii }" | tr -cd 'A-Za-z0-9._+~:-')" ;;
    *) return 0 ;;
  esac
  productos="${productos:+$productos,}{\"producto\":\"$1\",\"version\":\"$v\"}"
}
producto openmediavault openmediavault
producto proxmox-ve pve-manager

printf '{"v":2,"updates":%s,"security":%s,"os_id":"%s","os_version":"%s","productos":[%s],"checked":"%s"}\n' \
  "${total:-0}" "${security:-0}" "$(osr ID)" "$(osr VERSION_ID)" "$productos" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
