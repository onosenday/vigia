# Cambios

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
