# Tareas programadas

vigia avisa si una tarea programada (una copia de seguridad, un informe…) deja de terminar bien. Cada tarea
deja su estado en un fichero que lee el colector *textfile* de node_exporter.

## En el sitio

```yaml
hosts:
  - id: srv-1
    node_exporter: {puerto: 9100, textfile: true}
tareas:
  - {nombre: copias-postgres, host: srv-1, max_horas: 26}
```

- Con `gestion: vigia`, el despliegue añade `--collector.textfile.directory` al node_exporter y crea
  `/var/lib/vigia/textfile` (si el usuario de despliegue no es root ni tiene sudo, avisa: créala tú).
- Con `gestion: externo`, añade tú al exporter `--collector.textfile.directory=/var/lib/vigia/textfile`
  (paquete de Debian/Raspbian: en `ARGS` de `/etc/default/prometheus-node-exporter`).
- `max_horas`: margen sin una ejecución correcta antes de avisar (para una tarea diaria, 26).

## En la tarea

Al terminar, la tarea escribe `/var/lib/vigia/textfile/<tarea>.prom` de forma atómica:

```bash
#!/usr/bin/env bash
# uso: vigia-tarea.sh <tarea> <orden…>   (como root, p. ej. desde un servicio de systemd)
set -u
tarea=$1; shift
dir=/var/lib/vigia/textfile; f=$dir/$tarea.prom
"$@"; rc=$?
ok=$(awk '/^vigia_tarea_ultimo_exito_timestamp_seconds/ {print $2}' "$f" 2>/dev/null)
[ "$rc" -eq 0 ] && ok=$(date +%s)
{
  [ -n "$ok" ] && echo "vigia_tarea_ultimo_exito_timestamp_seconds{tarea=\"$tarea\"} $ok"
  echo "vigia_tarea_ultimo_resultado{tarea=\"$tarea\"} $(( rc != 0 ))"
} > "$f.tmp" && mv "$f.tmp" "$f"
exit "$rc"
```

En un error se conserva la hora del último éxito. Ejemplo con systemd:

```ini
# /etc/systemd/system/copias-postgres.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/vigia-tarea.sh copias-postgres /usr/local/bin/copias-postgres.sh
```

## Alertas y panel

| Alerta | Cuándo |
|--------|--------|
| Tarea sin éxito reciente | han pasado más de `max_horas` desde la última ejecución correcta (5 min) |
| Tarea con error | la última ejecución acabó con error |
| Tarea sin datos | la tarea no ha escrito nunca su métrica (1 h): script sin instalar, textfile inactivo o errata en el nombre |

Panel «Tareas»: horas desde el último éxito, margen hasta `max_horas` y resultado de cada tarea.
