#!/bin/sh
# metrics.sh <updates.json> — convierte el agregado del recolector en métricas de Prometheus (texto).
# Acepta el formato v1 de los scripts de host (solo conteos) y el v2 (además, versión de los productos).
#   vigia_updexp_ok{host}                       1 si el host respondió (o hay caché), 0 si no
#   vigia_updexp_formato{host}                  versión del formato del script del host (1 o 2)
#   vigia_actualizaciones_pendientes{host}      paquetes pendientes (apt) o 1/0 (DSM)
#   vigia_actualizaciones_seguridad{host}       de ellos, de seguridad (solo apt)
#   vigia_producto_info{host,producto,version}  1 por producto que informa el host (v2)
#   vigia_updexp_comprobado_timestamp           última vuelta del recolector (sin `host`): frescura
# Los valores de las etiquetas solo pasan si son caracteres de versión (el host no es de fiar): el formato de
# texto de Prometheus solo admite \\, \" y \n, y un escape raro tiraría el scrape de todos.
set -eu
IN="$1"

# familia <métrica> <ayuda> <filtro jq>: el filtro recibe el JSON de un host (con $h = su id) y emite {l, v}:
# las etiquetas extra (",producto=…") y el valor.
familia() {
  printf '# HELP %s %s\n# TYPE %s gauge\n' "$1" "$2" "$1"
  jq -r --arg m "$1" "to_entries[] | select(.key | startswith(\"_\") | not)
    | .key as \$h | .value | select(type == \"object\") | $3
    | \"\(\$m){host=\(\$h | @json)\(.l)} \(.v)\"" "$IN"
}

familia vigia_updexp_ok "El host respondió al sondeo (o hay caché)." '{l: "", v: (if .error then 0 else 1 end)}'
familia vigia_updexp_formato "Versión del formato del script del host." \
  'select(.error | not) | {l: "", v: (.v | if type == "number" then . else 1 end)}'
familia vigia_actualizaciones_pendientes "Actualizaciones pendientes (paquetes; en DSM, 1 o 0)." \
  '(.updates // .dsm_update) | select(type == "number") | {l: "", v: .}'
familia vigia_actualizaciones_seguridad "Actualizaciones de seguridad pendientes." '.security | select(type == "number") | {l: "", v: .}'
familia vigia_producto_info "Producto y versión que informa el host." '(.productos | if type == "array" then .[] else empty end)
  | select(type == "object" and (.producto | type == "string" and test("^[a-z0-9-]{1,40}$"))
      and (.version | type == "string" and test("^[A-Za-z0-9._+~:-]{1,40}$")))
  | {l: ",producto=\(.producto | @json),version=\(.version | @json)", v: 1}'

printf '# HELP vigia_updexp_comprobado_timestamp Última vuelta del recolector.\n'
printf '# TYPE vigia_updexp_comprobado_timestamp gauge\n'
jq -r '._checked | select(type == "string") | fromdateiso8601? | "vigia_updexp_comprobado_timestamp \(.)"' "$IN"
