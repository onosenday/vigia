# Bot de comandos entrantes por Telegram (vigia-c3b)

Hoy vigia solo envía: Grafana manda las alertas al chat de `alertas.telegram`. Este diseño añade un bot que
**escucha** comandos de consulta en ese mismo chat y responde con el estado del sitio. Solo consulta: no
reinicia, no silencia, no escribe en ningún sistema.

## Arquitectura

- **Dónde**: un servicio `bot` más dentro del stack `monitor` (el de Prometheus y Grafana). Habla con
  `prometheus` y `grafana` por la red interna de Docker, no publica puertos y se despliega con
  `vigia deploy monitor` (diff, copia previa y rollback de siempre). En hosts OMV sigue siendo gestionable
  desde la UI porque es el mismo stack.
- **Una sola fuente de datos de red: Prometheus.** Los dispositivos salen de las métricas que ya publica
  netinv (`netinv_device_info` con nombre, tipo, ubicación, IP, MAC, fabricante, modelo y encendido;
  `netinv_device_last_seen_seconds` y `…_first_seen_seconds`), que ya incorporan la clasificación manual del
  `devices.yaml` del sitio. El bot no lee `devices.json` (netinv va en la red del host) ni ficheros de
  inventario propios. Las alertas salen de la API de Grafana.
- **Código**: subpaquete `vigia.bot` (`src/vigia/bot/`), solo biblioteca estándar, con ruff, mypy estricto y
  tests como el resto del paquete. `vigia build` lo copia a `build/bot/` junto con `images/bot/Dockerfile` y
  un `config.json` generado; el contenedor lo ejecuta como `python -m vigia_bot`.
- **Telegram**: *long polling* con `getUpdates` (sin webhook ni exposición a internet). El mismo bot que
  usan las alertas: Grafana solo envía y el bot escucha.

### Configuración en `site.yaml`

```yaml
modulos:
  bot:
    activo: true
    grafana_token: BOT_GRAFANA_TOKEN   # nombre de la variable (service account, rol Viewer)
    zona: Europe/Madrid                # zona horaria de las horas que muestra
    puerto: 9466                       # /metrics, solo en la red interna
```

- Requiere `alertas.activo` y `alertas.telegram` (de ahí salen el token y el `chat_id`); si no, `vigia
  validate` da error. `grafana_token` es obligatorio con el bot activo.
- `grafana_token`: token de *service account* con rol **Viewer**, distinto del de administración
  (`monitor.grafana_token`).
- `config.json` (generado, sin secretos): nombre del sitio, `chat_id`, zona, puerto, URLs internas de
  Prometheus y Grafana, si hay netinv, umbral de disco y la lista de hosts en el orden de `hosts:` (id,
  nombre visible, IP, tipo).

### Piezas del código (`src/vigia/bot/`)

| Módulo | Tarea |
|--------|-------|
| `config.py` | lectura de `config.json` y de los tokens del entorno |
| `fuentes.py` | GET JSON con `urllib`; clientes de Prometheus (PromQL fijas) y de las alertas de Grafana |
| `formato.py` | escapado HTML, recorte a 30 líneas, horas y duraciones |
| `buscar.py` | normalización y búsqueda por nombre, IP o MAC |
| `comandos.py` | parseo de `/comando args`, despacho y respuestas |
| `telegram.py` | `getUpdates`, `sendMessage`, `setMyCommands`, filtro de chat y limitador |
| `__main__.py` | arranque, bucle con reintentos y `/metrics` |

## Comandos

| Comando | Fuente | Respuesta |
|---------|--------|-----------|
| `/estado` | Prometheus + Grafana | Una línea por host en el orden de `hosts:`: ✅/❌/❔; con node_exporter, CPU, RAM y disco más lleno; debajo, número y nombres de las alertas activas |
| `/alertas` | API de alertas de Grafana | Las disparadas ahora: `❌ Caído · nodo1 · desde 14:05 (23 min)`; si no hay, «Sin alertas» |
| `/host <nombre\|ip>` | Prometheus | Con node_exporter: CPU, RAM, carga, temperatura, uptime, disco por montaje y contenedores en marcha (cAdvisor). Con windows_exporter: discos. Con SNMP o solo ping: estado |
| `/dispositivo <nombre\|ip\|mac>` | netinv (Prometheus) | `🟢 Impresora · 10.99.0.40 · visto hace 3 min` o `⚪ Impresora · 10.99.0.40 · última vez ayer 23:10` |
| `/info <nombre\|ip\|mac>` | netinv (Prometheus) | Ficha: nombre, tipo, ubicación, fabricante, modelo, IP, MAC, estado, primera y última vez |
| `/lista [tipo]` | netinv (Prometheus) | Encendidos ahora, agrupados por tipo; con `tipo`, solo esos |
| `/ayuda` | — | Comandos con un ejemplo de cada uno |

- **Estado de un host**: ✅ si responde alguno de sus exporters (`up` de node, windows o snmp) o su ping
  (`probe_success` del job `ping`); ❌ si los hay y ninguno responde; ❔ si no hay datos.
- **Búsqueda**: sin distinguir mayúsculas ni acentos, por nombre, IP o MAC (exacto primero, luego contiene).
  Varias coincidencias → lista corta (8 como máximo) para afinar; ninguna → «No conozco X» y sugerencia de
  `/lista`.
- **Formato**: compacto, sin letras grandes, 30 líneas como máximo; lo que sobre se recorta y se indica
  cuántas faltan.
- Al arrancar, el bot registra sus comandos con `setMyCommands` para el autocompletado.

## Seguridad y datos

- **Quién**: solo se atienden mensajes cuyo `chat.id` sea el de `alertas.telegram.chat_id`. Lo demás
  (privados, otros grupos) se descarta sin responder; en el log solo queda el id numérico. Se recomienda
  modo privacidad activado (en un grupo el bot solo recibe `/comandos`) y *Allow Groups* desactivado.
- **Solo lectura**: PromQL fijas en el código (el usuario no escribe PromQL) y GET de alertas con rol
  Viewer. Los argumentos nunca se interpolan en consultas ni URLs: se consulta todo el sitio y se filtra en
  Python. Argumentos de 64 caracteres como máximo.
- **Secretos**: token del bot y `grafana_token` por nombre, como el resto de vigia; llegan como variables
  del entorno del stack y `vigia deploy` aborta si faltan. El token va en la URL de la API de Telegram: los
  errores se registran solo con su tipo y código HTTP, nunca con la URL ni el mensaje completo. vigia aborta
  si un secreto aparece en lo generado.
- **Datos personales**: la ubicación y los nombres de los dispositivos solo salen al chat de alertas (un
  grupo privado); son los mismos datos que ya muestra el panel Dispositivos de Grafana. El bot no guarda
  historial de mensajes.
- **Límites**: 1 respuesta por segundo y 20 por minuto como máximo; texto escapado en HTML.
- **Contenedor**: usuario sin privilegios (65534), sistema de ficheros de solo lectura, `cap_drop: ALL`,
  `no-new-privileges`, sin puertos publicados.

## Errores

- Fuente caída (Prometheus o Grafana): se responde con lo disponible y una línea `⚠ Grafana no responde`;
  nunca silencio ni trazas. Sin netinv en el sitio, los comandos de dispositivos lo dicen.
- Telegram o red caídos: reintentos con espera creciente de 1 s a 60 s. El `offset` vive en memoria; al
  arrancar se descartan los mensajes de más de 2 min para no contestar a destiempo.
- `/comando` desconocido: respuesta con `/ayuda`. Texto que no es comando: se ignora.
- Salud: `/metrics` en la red interna (`vigia_bot_up`, `vigia_bot_mensajes_total{resultado}`), raspado por
  Prometheus en el job `bot` (etiqueta `nombre: Bot de Telegram`); la regla «Exporter sin respuesta» avisa
  si el bot cae.

## Tests (nivel B, datos sintéticos `10.99.0.0/24`, `ejemplo.lan`)

- Unitarios: parseo y despacho; búsqueda (acentos, IP, MAC, ambigüedad); formato (recorte, escapado,
  horas); filtro de chat (un mensaje de otro chat no produce respuesta ni llamada a `sendMessage`);
  limitador; bucle con reintentos.
- Fuentes con un `fetch` falso: respuestas fijas de Prometheus y Grafana, y fuente caída.
- Modelo: `modulos.bot` sin `alertas.telegram` o sin `grafana_token` → error.
- Golden: el sitio de ejemplo con el bot activo (compose, job de Prometheus, `config.json`, código); ningún
  secreto en el build; unidad `monitor` con la variable del token de Grafana.
- Manual en un sitio real: cada comando en el grupo; un mensaje privado al bot no recibe respuesta.

## Fuera de alcance

Acciones sobre hosts o contenedores, silencios o *ack* de alertas, PromQL libre, varios chats o listas de
usuarios, webhook, métricas detalladas por SNMP.
