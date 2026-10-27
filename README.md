# vigia

Monitorización de redes por **sitio**: Prometheus, Grafana, blackbox, SNMP, node/windows_exporter, cAdvisor,
inventario de dispositivos y comprobación de actualizaciones, generados desde un `site.yaml` por red y con la
marca de cada sitio (títulos, carpeta, portada, logo y favicon de Grafana, etiquetas, nombres de contenedores).

El paquete no contiene datos de ningún sitio: cada red vive en su propio repo y fija la versión de vigia.

## Uso

```bash
uvx --from git+https://github.com/onosenday/vigia.git vigia new-site ./mi-red \
    --id oficina --name "Red de la oficina" --brand Oficina \
    --subnet 10.0.0.0/24 --domain oficina.lan --monitor-ip 10.0.0.10 --ssh-user admin
cd mi-red && uv sync
uv run vigia validate              # errores y avisos del site.yaml
uv run vigia build                 # genera build/ (para revisar)
uv run vigia units                 # unidades desplegables
uv run vigia deploy monitor        # diff contra lo que corre en el host
uv run vigia deploy monitor --yes  # despliega (copia previa en el host)
uv run vigia rollback monitor --yes
```

Otros comandos: `diff` (contra una carpeta), `bridges` (redes Docker de los hosts), `descubrir` (propuesta
de hosts a partir de la red, con autorización), `grafana-brand`
(nombre de la organización de Grafana), `skill` (instala o actualiza la skill de Claude Code en el sitio).

## Qué sabe vigilar

Cada equipo declara su `tipo` y vigia elige cómo medirlo: node_exporter (Linux, OMV, Proxmox, TrueNAS),
windows_exporter (Windows), SNMP v3 (Synology, QNAP, switches, impresoras, SAI) o solo ping/HTTP (router, AP).
Los paneles se generan según lo que exista en el sitio.

Alertas con la marca del sitio por Telegram y correo (caído, certificado, disco, exporter): ver
[docs/alertas.md](docs/alertas.md).

## Seguridad

- `site.yaml` se valida en estricto (pydantic, `extra="forbid"`); textos, ids, rutas y URLs acotados.
- Los secretos solo se nombran (`secreto: VARIABLE`): sus valores viven en el fichero de entorno del sitio,
  viajan por stdin y nunca en argv; vigia aborta si alguno aparece en lo generado.
- Las plantillas entrecomillan todo valor; SSH con `StrictHostKeyChecking=yes`; sudo por stdin.
- Descubrimiento activo de la red solo con autorización registrada en `site.yaml`.

## Con Claude Code

El paquete incluye una skill para Claude Code (`src/vigia/claude/skills/vigia/SKILL.md`): flujo de cambios con
diff y OK, reglas y lo aprendido de cada plataforma. `vigia new-site` la instala en el repo del sitio
(`.claude/skills/vigia/SKILL.md`) junto con un `CLAUDE.md` con las reglas del sitio, y `vigia skill` la actualiza
cuando cambia la versión de vigia.

## Licencia

MIT. Incluye «Node Exporter Full» (LGPL-3.0), ver `src/vigia/dashboards/externos/NOTICE.md`.
