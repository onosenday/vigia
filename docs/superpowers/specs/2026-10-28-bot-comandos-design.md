# Bot de comandos entrantes por Telegram (vigia-c3b)

Hoy vigia solo envía: Grafana manda las alertas al chat de `alertas.telegram`. Este diseño añade un bot que
**escucha** comandos de consulta en ese mismo chat y responde con el estado del sitio. Solo consulta: no
reinicia, no silencia, no escribe en ningún sistema.

## Arquitectura

- **Dónde**: un servicio `bot` más dentro del stack `monitor` (el de Prometheus y Grafana). Habla con
  `prometheus`, `grafana` y `netinv` por la red interna de Docker, no publica puertos y se despliega con
  `vigia deploy monitor` (diff, copia previa y rollback de siempre). En hosts OMV sigue siendo gestionable
  desde la UI porque es el mismo stack.
- **Imagen**: `src/vigia/images/bot/`, construida en el host como `netinv` y `updates_exporter`. Python con
  `httpx` y la biblioteca estándar; sin framework de bots.
- **Telegram**: *long polling* con `getUpdates` (sin webhook ni exposición a internet). El mismo bot que
  usan las alertas: Grafana solo envía y el bot escucha.

### Configuración en `site.yaml`

```yaml
modulos:
  bot:
    activo: true
    inventario: inventario/dispositivos.yaml   # opcional, para /info y /lista
    campos: [tipo, dueno, ubicacion]           # campos del inventario que se muestran
    grafana_token: BOT_GRAFANA_TOKEN           # nombre de la variable (service account, rol Viewer)
```

- Token y `chat_id` salen de `alertas.telegram`; si no existe, `vigia validate` da error.
- `grafana_token`: un token de *service account* con rol **Viewer**, distinto del de administración.
- **Inventario**: fichero YAML del repo del sitio, una entrada por dispositivo con `nombre`, `mac` y campos
  opcionales (`tipo`, `dueno`, `ubicacion`, `grupo`). vigia lo copia al build con solo los campos de la
  lista blanca; cualquier otro campo es error de validación. `campos` decide cuáles salen en las respuestas
  (un sitio puede no mostrar dueños).

### Piezas del código (`src/vigia/images/bot/`)

| Módulo | Tarea |
|--------|-------|
| `telegram.py` | `getUpdates`, `sendMessage`, `setMyCommands`; filtro de chat; reintentos |
| `comandos.py` | parseo de `/comando args`, despacho y búsqueda de nombres |
| `fuentes.py` | clientes de Prometheus (PromQL fijas), netinv (`devices.json`), Grafana (alertas) e inventario |
| `formato.py` | textos compactos en HTML de Telegram, escapado y recorte |
| `main.py` | arranque, bucle y `/metrics` |

## Comandos

| Comando | Fuente | Respuesta |
|---------|--------|-----------|
| `/estado` | Prometheus + Grafana | Una línea por servidor en el orden de `hosts:`: ✅/❌, CPU, RAM y disco más lleno; debajo, número y nombres de las alertas activas |
| `/alertas` | API de alertas de Grafana | Las disparadas ahora: `❌ Caído · nodo1 · desde 14:05 (23 min)`; si no hay, «Sin alertas» |
| `/host <nombre>` | Prometheus | CPU, RAM, carga, disco por montaje, temperatura, uptime, contenedores parados (cAdvisor); en hosts SNMP, lo que dé SNMP |
| `/dispositivo <nombre\|ip\|mac>` | netinv | `🟢 Impresora · 10.99.0.40 · conectado desde 18:30` o `⚪ visto por última vez ayer 23:10` |
| `/info <nombre\|ip\|mac>` | inventario + netinv | Ficha: nombre, campos permitidos, MAC, IP y último visto |
| `/lista [tipo]` | netinv + inventario | Conectados ahora, agrupados por tipo; con `tipo`, solo esos |
| `/ayuda` | — | Comandos con un ejemplo de cada uno |

- **Búsqueda**: sin distinguir mayúsculas ni acentos, por nombre, IP o MAC. Varias coincidencias → lista
  corta para afinar; ninguna → «No conozco X» y sugerencia de `/lista`.
- **Formato**: compacto, sin letras grandes, 30 líneas como máximo; lo que sobre se recorta y se indica
  cuántas faltan.
- Al arrancar, el bot registra sus comandos con `setMyCommands` para el autocompletado.

## Seguridad y datos

- **Quién**: solo se atienden mensajes cuyo `chat.id` sea el de `alertas.telegram.chat_id`. Lo demás
  (privados, otros grupos) se descarta sin responder; en el log solo queda el id numérico. Se recomienda
  modo privacidad activado (en un grupo el bot solo recibe `/comandos`) y *Allow Groups* desactivado.
- **Solo lectura**: PromQL fijas en el código (el usuario no escribe PromQL), GET a netinv y GET de alertas
  con rol Viewer. Los argumentos solo se buscan en listas ya cargadas; nunca se interpolan en consultas ni
  URLs. Argumentos de 64 caracteres como máximo.
- **Secretos**: token del bot y `grafana_token` por nombre, como el resto de vigia; llegan como variables
  del entorno del stack y `vigia deploy` aborta si faltan. El token va en la URL de la API de Telegram: el
  log de `httpx` se silencia y cualquier URL registrada se enmascara. vigia aborta si un secreto aparece en
  lo generado.
- **Datos personales**: dueño y ubicación son datos de personas; solo salen al chat de alertas (un grupo
  privado) y solo los campos de `campos`. El bot no guarda historial de mensajes.
- **Límites**: 1 respuesta por segundo y 20 por minuto como máximo; texto escapado en HTML.
- **Contenedor**: usuario sin privilegios, sistema de ficheros de solo lectura, `cap_drop: ALL`, sin
  puertos publicados.

## Errores

- Fuente caída (Prometheus, netinv o Grafana): se responde con lo disponible y una línea
  `⚠ netinv no responde`; nunca silencio ni trazas.
- Telegram o red caídos: reintentos con espera creciente de 1 s a 60 s. El `offset` vive en memoria; al
  arrancar se descartan los mensajes de más de 2 min para no contestar a destiempo.
- `/comando` desconocido: respuesta con `/ayuda`.
- Inventario inválido (YAML, campos fuera de la lista blanca): error en `vigia validate`, antes de desplegar.
- Salud: `/metrics` en la red interna (`vigia_bot_up`, mensajes atendidos y descartados), raspado por
  Prometheus; la regla «Exporter sin respuesta» avisa si el bot cae.

## Tests (nivel B, datos sintéticos `10.99.0.0/24`, `ejemplo.lan`)

- Unitarios: parseo y despacho; búsqueda (acentos, IP, MAC, ambigüedad); formato (recorte, escapado);
  filtro de chat (un mensaje de otro chat no produce respuesta ni llamada a `sendMessage`).
- Fuentes con `httpx.MockTransport`: respuestas fijas de Prometheus, netinv y Grafana, y fuente caída.
- Modelo: `modulos.bot` sin `alertas.telegram` → error; campos de inventario no permitidos → error.
- Golden: `monitor.yml` con el bot activo; ningún secreto en el build.
- Manual en un sitio real: cada comando en el grupo; un mensaje privado al bot no recibe respuesta.

## Fuera de alcance

Acciones sobre hosts o contenedores, silencios o *ack* de alertas, PromQL libre, varios chats o listas de
usuarios, webhook.
