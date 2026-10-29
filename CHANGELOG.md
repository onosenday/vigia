# Cambios

## Sin publicar

- **Catálogo de ciclos de vida** (`vigia ciclos lista|actualizar`, `ciclos.fecha_aviso` en el sitio): fechas de fin
  de soporte de Debian, Ubuntu, Proxmox VE, TrueNAS (desde endoflife.date), OpenMediaVault y Synology DSM (a
  mano), llevadas a Prometheus como reglas de grabación (`prometheus/rules/ciclos.yml`,
  [docs/ciclos.md](docs/ciclos.md)). Base de los avisos de fin de soporte y de versión mayor nueva.

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
