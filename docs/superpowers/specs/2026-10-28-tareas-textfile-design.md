# Tareas programadas por el colector textfile de node_exporter (vigia-86m)

Petición de un sitio (2026-10-28, vigia v0.3.1): las copias de seguridad u otras tareas con un temporizador
pueden fallar o dejar de ejecutarse sin que nadie se entere. vigia ya vigila el host; con el colector textfile
de node_exporter, cada tarea deja su estado en un fichero y vigia alerta y lo muestra en un panel.

## Configuración (`site.yaml`)

```yaml
hosts:
  - id: srv-1
    node_exporter: {puerto: 9100, textfile: true}
tareas:
  - {nombre: copias-postgres, host: srv-1, max_horas: 26}
```

- `Exporter.textfile: bool = False`. Solo tiene sentido en `node_exporter` (error si se pone en
  `windows_exporter` o `cadvisor`).
- `Site.tareas: list[Tarea]`, con `Tarea(nombre: Id, host: Id, max_horas: int)`, `1 <= max_horas <= 744`.
- Validación del sitio:
  - nombres de tarea únicos;
  - el host existe y tiene `node_exporter` con `textfile: true`.
- Con `gestion: externo`, `textfile: true` significa que el administrador ya ha configurado
  `--collector.textfile.directory` en ese exporter; vigia no despliega nada en él, solo alerta y pinta.

## Despliegue (solo `gestion: vigia`)

- El macro `node_exporter` de `templates/compose/_agents.j2` añade, si `textfile`,
  `--collector.textfile.directory=/host/var/lib/vigia/textfile`. El `/` del host ya está montado en `/host`
  (`ro,rslave`), así que no hace falta otro volumen.
- Carpeta en el host: `/var/lib/vigia/textfile` (constante `TEXTFILE_DIR`). El script de despliegue de la
  unidad que lleva ese node_exporter (`agentes:<host>` o `monitor` si es el host del monitor) ejecuta
  `install -d -m 755 /var/lib/vigia/textfile` antes del `up`, con el mismo sudo que el resto del script.
  Es idempotente y no toca lo que haya dentro. El rollback no la borra (pueden quedar métricas del usuario).
  Si el usuario no puede crearla (adaptador compose sin sudo), el despliegue avisa y sigue: la alerta «Tarea
  sin datos» lo hará visible.

## Convención de métricas

Cada tarea escribe `/var/lib/vigia/textfile/<tarea>.prom` de forma atómica (`.prom.tmp` + `mv`):

```
vigia_tarea_ultimo_exito_timestamp_seconds{tarea="copias-postgres"} 1.7613e+09
vigia_tarea_ultimo_resultado{tarea="copias-postgres"} 0
```

- `ultimo_resultado`: 0 = bien, 1 = error. En un error se conserva el último timestamp de éxito.
- Prometheus añade la etiqueta `nombre` (host) desde los targets del job `node`.

## Alertas (`alerting.py`)

Solo si hay `tareas`. Una regla por tipo; la condición por tarea se une con `or` y cada término filtra por
`tarea` y `nombre` del host declarado (una tarea con el mismo nombre en otro host no cuenta).

| uid | Título | Expresión (por tarea, unidas con `or`) | Condición | `for` |
|-----|--------|----------------------------------------|-----------|-------|
| `vigia-tarea-retrasada` | Tarea sin éxito reciente | `(time() - max by (nombre, tarea) (vigia_tarea_ultimo_exito_timestamp_seconds{nombre="H", tarea="T"})) / 3600 - max_horas` | `> 0` | 5m |
| `vigia-tarea-error` | Tarea con error | `max by (nombre, tarea) (vigia_tarea_ultimo_resultado{nombre="H", tarea="T"})` | `> 0` | 0s |
| `vigia-tarea-sin-datos` | Tarea sin datos | `absent(vigia_tarea_ultimo_exito_timestamp_seconds{nombre="H", tarea="T"})` | `> 0` | 1h |

- Resúmenes: «`<nombre>`: la tarea `<tarea>` no termina bien desde hace más de N h», «… acabó con error»,
  «… no ha escrito nunca su métrica (¿script instalado? ¿textfile activo?)».
- `vigia-tarea-retrasada` muestra las horas de retraso con `humanize`.
- Si el exporter del host cae, ya avisa «Exporter sin respuesta»; `absent` también saltaría tras 1 h, lo
  que es aceptable (no se duplica antes de esa hora).

## Panel «Tareas» (`tareas.json`)

Dashboard propio, solo si hay `tareas`. Una tabla compacta, una fila por tarea declarada, ordenada por host
y tarea (seguir el orden de `hosts:` exigiría una consulta por tarea y columna):

| Host | Tarea | Último éxito (h) | Margen (h) | Resultado |

- «Margen» = `max_horas` − horas desde el último éxito: rojo si es negativo.
- «Resultado»: mapeo 0 → `bien` (verde), 1 → `error` (rojo), 2 → `sin datos` (gris; viene de `absent`).
- Estilo de los paneles existentes (`Brand`, letras pequeñas).

## Documentación

- `docs/tareas.md`: qué hace, cómo se declara, y un envoltorio de bash de ejemplo (~10 líneas) que ejecuta
  la orden y escribe el `.prom` atómicamente; cómo activarlo en un node_exporter externo (parámetro) y un
  ejemplo de temporizador de systemd.
- Una línea en la skill `vigia` (`claude/skills/vigia/SKILL.md`), en `docs/alertas.md` (tabla) y en el
  CHANGELOG.

## Tests

- Modelo: `textfile` fuera de `node_exporter`, tarea con host inexistente, host sin `textfile`, nombres
  repetidos, `max_horas` fuera de rango.
- Golden: el sitio de ejemplo con un host `textfile: true` y una tarea (compose con el parámetro, reglas,
  `tareas.json`).
- Alertas: las tres expresiones con dos tareas en hosts distintos (filtran por `nombre` y `tarea`).
- Despliegue: el script de la unidad incluye `install -d` solo si su node_exporter tiene `textfile`.

## Fuera de alcance

- Instalar un binario auxiliar (`vigia-tarea`) en los hosts: solo el ejemplo en la documentación.
- Pasar el node_exporter de pimonitor a vigia (myNet-5ar).
- Comando del bot para tareas.
