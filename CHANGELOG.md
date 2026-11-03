# Cambios

## Sin publicar

- **Nuevo**: política de rama en el catálogo. Prometheus sigue su LTS: ya no se ofrece la 3.15 a quien está en
  la 3.13 (ni alerta, ni panel, ni `/pendientes`, donde sale en «Decidido»). Un sitio puede seguir todas las
  ramas con `ciclos.politica: {prometheus: todas}`. Si tenías una decisión en `decisiones.yaml` para eso, sobra:
  `vigia decisiones --limpiar`.
- **Arreglo**: la plantilla de sitio fija Prometheus en la LTS 3.13.5 (la 3.15 pierde el soporte el 06-11-2026).

## 0.5.2 (2026-11-01)

Al actualizar un sitio: **reinstala `apt-updates-json.sh`** en cada host Debian/OMV/Proxmox (y, si quieres,
`syno-updates-json.sh` en DSM), como en [docs/actualizaciones.md](docs/actualizaciones.md). Los sudoers no cambian.

- **Arreglo**: `apt-updates-json.sh` llamaba a `sudo apt-get update -qq`, pero la línea de sudoers de la guía solo
  permite `apt-get update` sin argumentos, así que sudo lo rechazaba (en el journal del host, `command not
  allowed`) y la lista de paquetes solo se refrescaba con el temporizador diario de apt. Ahora llama exactamente
  a lo permitido. Los dos scripts usan `sudo -n` (si falta el permiso, fallan en vez de esperar una contraseña) y
  un test comprueba que cada llamada a sudo casa con su línea de sudoers.

## 0.5.1 (2026-11-01)

Al actualizar un sitio:
- El bot, netinv y el updates-exporter se recompilan con bases nuevas fijadas por digest (el updates-exporter,
  de Alpine 3.20 a 3.24): tras `vigia deploy`, *Build* o *Pull* en sus stacks si no se recompilan solos.
- Con el bot activo aparece la alerta «Bot sin contacto con Telegram».
- Nada cambia en `site.yaml`: lo nuevo es opcional (`puertos_cerrados`, `ping: false`, `textfile` en
  windows_exporter).

- **Puertos que deben estar cerrados** (`externos.objetivos[].puertos_cerrados`): sonda TCP al revés, alerta
  «Puerto expuesto» (crítica) si alguno responde desde internet y tabla propia en el panel «Externos»
  ([docs/externos.md](docs/externos.md), aviso sobre el NAT loopback). «Caído» no cuenta estos puertos.
- **Externos sin ping** (`ping: false` en un objetivo `host`): para equipos que filtran ICMP; se vigilan solo por
  sus `puertos` y «Caído» salta por ellos.
- **Tareas vigiladas en Windows** (`windows_exporter: {textfile: true}`): mismas métricas y alertas que en Linux,
  leídas por el colector textfile de windows_exporter, con un envoltorio de PowerShell para el Programador de
  tareas ([docs/tareas.md](docs/tareas.md)).
- **Fin de soporte de Linux Mint y Windows Server**: Mint por `node_os_info` (id `linuxmint`); Windows Server por
  `windows_os_info` de windows_exporter, con el ciclo buscado por la versión exacta (`windows_producto` en el
  catálogo y la tabla `vigia_ciclo_version`). Mismos avisos, `/host` y panel Mantenimiento que el resto
  ([docs/ciclos.md](docs/ciclos.md)).
- **Bot**: alerta «Bot sin contacto con Telegram» (más de 10 minutos sin respuesta de getUpdates), más resultados
  en `vigia_bot_mensajes_total` (ignorado, sin_respuesta, fallo_envio) y un aviso único cuando se limita
  ([docs/bot.md](docs/bot.md)).
- **Imágenes base fijadas por digest** (`<etiqueta>@sha256:…`): el bot, netinv y el updates-exporter se compilan
  siempre igual. El updates-exporter pasa de Alpine 3.20 (sin soporte desde 04-2026) a 3.24. Al publicar una
  versión se refrescan los digests.

## 0.5.0 (2026-10-29)

Al actualizar un sitio:
- Todas las alertas ganan las etiquetas `gravedad` y `categoria`: las que estén disparadas se resuelven y
  vuelven a dispararse una vez (un aviso repetido) y su `for` empieza de cero.
- El job `actualizaciones` lee `/metrics.txt` del updates-exporter, que solo sirve su imagen nueva: despliega
  `updates` antes que `monitor` (si no, «Exporter sin respuesta» hasta que llegue). Para tener versiones de OMV,
  Proxmox y DSM, reinstala en cada host su script (formato v2, [docs/actualizaciones.md](docs/actualizaciones.md)).
- `imagenes` necesita `modulos.imagenes.clave` en el fichero de entorno (sin `$`).

- **Catálogo de ciclos de vida** (`vigia ciclos lista|actualizar`, `ciclos.fecha_aviso` en el sitio): fechas de fin
  de soporte de Debian, Ubuntu, Proxmox VE, TrueNAS (desde endoflife.date), OpenMediaVault y Synology DSM (a
  mano), llevadas a Prometheus como reglas de grabación (`prometheus/rules/ciclos.yml`,
  [docs/ciclos.md](docs/ciclos.md)).
- **Avisos de fin de soporte**: sistema sin soporte, fin de soporte cercano (`umbrales.soporte_dias`), versión
  mayor disponible, versión fuera del catálogo y catálogo antiguo (`umbrales.catalogo_dias`), con la versión de
  la distribución de `node_os_info`.
- **Fin de soporte del software de los contenedores**: PostgreSQL, MariaDB, MySQL, MongoDB, Redis, Valkey,
  Grafana, Prometheus, nginx y Traefik, por la etiqueta de la imagen (cAdvisor). Margen de aviso por producto
  (`aviso_dias`) y sin aviso de versión mayor en los de ciclos cortos (`aviso_version`).
- **Imágenes nuevas de los contenedores** (`imagenes` por host, `modulos.imagenes`): What's Up Docker junto
  a los agentes y avisos de versión nueva de una imagen y de imagen nueva sin aplicar
  (`umbrales.imagen_durante`, para lo que queda fuera de watchtower) ([docs/imagenes.md](docs/imagenes.md)).
  What's Up Docker no toca el socket de Docker: pasa por un proxy de solo lectura (sin POST), corre con el
  sistema de ficheros de solo lectura y sin capacidades, y publica su puerto solo en la IP del host.
- **`/pendientes`** en el bot (certificados, consumibles, discos, soporte, versiones mayores,
  actualizaciones, imágenes nuevas; ⚠ si ya avisa, «próximo» dentro de `modulos.bot.proximo`), **versión y
  soporte en `/host`** y panel **Mantenimiento** ([docs/bot.md](docs/bot.md)).
- **`vigia deploy` copia `prometheus/rules/`** (las reglas de ciclos).
- **updates-exporter con métricas** (`/metrics.txt`, job `actualizaciones`) y **scripts de host v2**, que
  además informan de la versión del sistema y de OMV, Proxmox VE y DSM. Alertas de seguridad pendiente
  (`umbrales.seguridad_durante`), script antiguo y host sin comprobar ([docs/actualizaciones.md](docs/actualizaciones.md)).
  Hay que reinstalar el script en cada host para tener sus versiones.
- **Gravedad y categoría** en todas las alertas (etiquetas `gravedad` y `categoria`); los avisos `info` se
  repiten cada `alertas.repetir_info` (168h).

## 0.4.1 (2026-10-29)

- **Contexto SNMPv3** (`contexto` en `modulos.snmp.auths`, solo v3) → `context_name` de snmp_exporter. Para
  equipos que sin él devuelven el walk vacío (impresoras HP con Jetdirect).
- **Skill `vigia`**: impresoras (contexto, MD5/DES, v1/v2 en solo lectura para los drivers, equipos dormidos),
  falsos positivos del control de fugas de `deploy`, paso de un node_exporter de paquete al stack de agentes y
  diagnóstico de SNMP sin datos por `snmp_scrape_pdus_returned`.
- **Skill `vigia-actualizar`**: además del riesgo, revisa las novedades contra el sitio (aplicable ya, útil más
  adelante, no aplica) y deja lo aprovechable anotado en el proyecto del sitio (tareas y su `CLAUDE.md`).

## 0.4.0 (2026-10-28)

- **Tareas programadas** (`tareas`, `node_exporter.textfile`): alertas de tarea retrasada, con error y sin datos,
  y panel «Tareas», con el colector textfile de node_exporter ([docs/tareas.md](docs/tareas.md)).
- **Bot de consultas por Telegram** (`modulos.bot`): `/estado`, `/alertas`, `/host`, `/dispositivo`,
  `/info`, `/lista` y `/ayuda` en el chat de las alertas; solo lectura, solo ese chat, sin puertos
  publicados ([docs/bot.md](docs/bot.md)).
- **SNMPv3 con otros protocolos**: `protocolo_auth` (MD5, SHA, SHA224…SHA512) y `protocolo_priv` (DES, AES,
  AES192, AES256) en cada `modulos.snmp.auths`; por defecto SHA256/AES. Para equipos que solo admiten SHA-1.

## 0.3.1 (2026-10-28)

- **Skill `vigia-actualizar`**: comprueba en seco el riesgo de subir a otra versión (lo desplegado, novedades,
  validación y diferencias de lo generado por riesgo). `vigia skill` instala todas las skills del paquete.

## 0.3.0 (2026-10-28)

- **Impresoras por SNMP**: panel propio y alertas de consumible bajo y de error (sin papel, atasco, puerta…).
- **Objetivos externos** (`externos.objetivos`): equipos y webs fuera de la red del sitio, solo con sondas
  salientes y validación estricta de destinos ([docs/externos.md](docs/externos.md)).
- **Varias subredes por sitio** (`red.subredes_extra`); `descubrir` las barre todas o una con `--subred`.
- **Actividad de dispositivos**: dashboard nuevo con cuándo ha estado activo cada dispositivo que ve netinv,
  válido en rangos largos (cada punto marca activo si se vio en algún momento de su tramo).
- **`descubrir`**: propone servidores Windows (WinRM, controlador de dominio), clasifica por el título y la
  cabecera `Server` de la web cuando no se ve el fabricante, lista comentados los clientes sin proponer y los
  hosts del sitio que no responden, y no propone las IPs del propio equipo.
- Alertas: guía del grupo privado de Telegram para compartir los avisos y prueba por la API de Grafana 12.
- **Rango**: los sitios pasan a `vigia: ">=0.3,<0.4"`.

## 0.2.1 (2026-10-27)

- El `site.yaml` no carga si la versión instalada de vigia no está en su rango `vigia:`.
- `new-site` genera el rango de la serie instalada y el tag del `pyproject.toml` a partir de la versión.

## 0.2.0 (2026-10-27)

- **Alertas** de Grafana con la marca del sitio, por Telegram y correo: caído, certificado a punto de caducar,
  disco casi lleno y exporter sin respuesta; `alerta: false` para lo que se apaga a propósito
  ([docs/alertas.md](docs/alertas.md)).
- En OpenMediaVault, el despliegue comprueba que el *Environment* del stack tiene las variables que usa el
  compose antes de tocar nada.
- **`vigia descubrir`**: propone hosts de infraestructura a partir de netinv o de un barrido local, solo con
  autorización en `site.yaml` y `--yes`; la propuesta va a un fichero fuera de git.

## 0.1.0 (2026-10-26)

- Primera versión: `site.yaml` validado, perfiles por tipo de equipo, paneles con branding, despliegue
  (compose, OMV, Synology) con diff, copia y rollback, `bridges`, `grafana-brand`, `new-site` y skill de
  Claude Code.
