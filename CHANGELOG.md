# Cambios

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
