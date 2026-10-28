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
  `/var/lib/vigia/textfile`. En la práctica el despliegue necesita root; si no pudo crear la carpeta, avisa
  y la alerta «Tarea sin datos» lo deja visible (créala tú: `mkdir -p /var/lib/vigia/textfile`).
- Con `gestion: externo`, el exporter debe tener un directorio de textfile. El paquete de Debian/Raspbian
  ya usa `/var/lib/prometheus/node-exporter` (donde escribe, p. ej., `apt.prom`): poner otra carpeta en
  `ARGS` de `/etc/default/prometheus-node-exporter` la **sustituiría**. Si el exporter ya tiene carpeta de
  textfile, úsala en las tareas con `VIGIA_TEXTFILE_DIR` (la ruta no influye en las alertas); si no la
  tiene, añade `--collector.textfile.directory=/var/lib/vigia/textfile`.
- `max_horas`: margen sin una ejecución correcta antes de avisar (para una tarea diaria, 26).

## En la tarea

Al terminar, la tarea escribe `/var/lib/vigia/textfile/<tarea>.prom` de forma atómica:

```bash
#!/usr/bin/env bash
# uso: vigia-tarea.sh <tarea> <orden…>   (como root, p. ej. desde un servicio de systemd)
# VIGIA_TEXTFILE_DIR cambia la carpeta (por defecto /var/lib/vigia/textfile)
set -u
umask 022   # node_exporter corre como nobody y tiene que poder leer el fichero
tarea=$1; shift
dir=${VIGIA_TEXTFILE_DIR:-/var/lib/vigia/textfile}; f=$dir/$tarea.prom
"$@"; rc=$?
ok=$(awk '/^vigia_tarea_ultimo_exito_timestamp_seconds/ {print $2}' "$f" 2>/dev/null)
[ "$rc" -eq 0 ] && ok=$(date +%s)
tmp=$(mktemp "$dir/.$tarea.XXXXXX") || exit "$rc"   # el colector solo lee *.prom
{
  [ -n "$ok" ] && echo "vigia_tarea_ultimo_exito_timestamp_seconds{tarea=\"$tarea\"} $ok"
  echo "vigia_tarea_ultimo_resultado{tarea=\"$tarea\"} $(( rc != 0 ))"
} > "$tmp" && chmod 644 "$tmp" && mv "$tmp" "$f"
exit "$rc"
```

En un error se conserva la hora del último éxito. Ejemplo con systemd:

```ini
# /etc/systemd/system/copias-postgres.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/vigia-tarea.sh copias-postgres /usr/local/bin/copias-postgres.sh
```

```ini
# /etc/systemd/system/copias-postgres.timer
[Timer]
OnCalendar=*-*-* 02:30
Persistent=true

[Install]
WantedBy=timers.target
```

Se activa con `systemctl enable --now copias-postgres.timer`.

## Alertas y panel

| Alerta | Cuándo |
|--------|--------|
| Tarea sin éxito reciente | han pasado más de `max_horas` desde la última ejecución correcta (5 min) |
| Tarea con error | la última ejecución acabó con error |
| Tarea sin datos | la tarea no tiene ninguna ejecución correcta registrada (1 h): script sin instalar, textfile inactivo, errata en el nombre o una tarea que siempre falla |

Panel «Tareas»: horas desde el último éxito, margen hasta `max_horas` y resultado de cada tarea.
