# Ciclos de vida

vigia sabe cuándo pierde el soporte cada versión de los sistemas que vigila (Debian, Ubuntu, OpenMediaVault,
Synology DSM, Proxmox VE, TrueNAS) y lo lleva a Prometheus para avisar antes de que ocurra y cuando hay una
versión mayor nueva.

## El catálogo

Un YAML por producto en `src/vigia/catalogo/`, con los ciclos del más reciente al más antiguo:

```yaml
producto: openmediavault
fuente: manual              # o endoflife (con `endoflife: <slug>`)
fecha_aviso: normal         # qué fin de soporte cuenta: normal o extendido (Debian ELTS, DSM LTS…)
ciclo_regex: ^(\d+)\.       # versión instalada → ciclo (primer grupo)
ejemplos: {7.7.24-7: '7'}   # los tests comprueban la expresión con ellos
comprobado: '2026-10-29'
ciclos:
- {ciclo: '8', publicado: '2025-12-01'}                          # sin fecha de fin anunciada
- {ciclo: '7', publicado: '2024-03-01', fin_soporte: '2026-06-30'}
```

- **Desde endoflife.date** (Debian, Ubuntu, Proxmox VE, TrueNAS): `uv run vigia ciclos actualizar` en el repo
  de vigia refresca los ciclos y la fecha de comprobación; se revisa el diff y se commitea con la versión.
  Nunca lo ejecuta el build ni el despliegue. `fin_soporte` es el `eol` de endoflife.date (en Debian incluye
  el LTS) y `fin_extendido` su `extendedSupport`.
- **A mano** (OpenMediaVault, Synology DSM): `referencia` dice de dónde salen las fechas. Las que se publican
  por mes se guardan como el último día del mes.
- En **Ubuntu** la versión de referencia para «hay una versión mayor nueva» es la última LTS (`ultimo_lts`).
- **Contenedores** (PostgreSQL, MariaDB, MySQL, MongoDB, Redis, Valkey, Grafana, Prometheus, nginx, Traefik):
  `imagen_regex` saca la versión de la etiqueta de la imagen que ve cAdvisor (`postgres:16.4-alpine` → 16).
  Las etiquetas sin versión suficiente (`latest`, `redis:8` cuando los ciclos son `8.x`) no casan y no avisan;
  `ejemplos_imagen` fija qué casa y qué no. Los productos de ciclos cortos llevan su propio margen
  (`aviso_dias`: Prometheus 14, Grafana y nginx 30) y no avisan de versión mayor (`aviso_version: false`).
- `uv run vigia ciclos lista` muestra el ciclo de referencia y la última comprobación de cada producto.

## En el sitio

No hace falta configurar nada. Para cambiar qué fecha cuenta en un producto:

```yaml
ciclos:
  fecha_aviso: {debian: extendido}
```

## En Prometheus

El build genera `prometheus/rules/ciclos.yml` con reglas de grabación constantes:

| Serie | Qué es |
|-------|--------|
| `vigia_ciclo_fin_soporte_timestamp{producto, ciclo}` | Fin de soporte que cuenta (epoch). Solo si hay fecha |
| `vigia_ciclo_info{producto, ciclo, ultimo}` | 1 por ciclo conocido; `ultimo` es el ciclo de referencia |
| `vigia_ciclos_catalogo_timestamp{producto}` | Última comprobación del catálogo de ese producto |
| `vigia_ciclo_superado{producto, ciclo, ultimo}` | 1 por ciclo anterior al de referencia (si `aviso_version`) |
| `vigia_ciclo_aviso_dias{producto}` | Margen de aviso: `aviso_dias` del producto o `umbrales.soporte_dias` |

Y, con la versión instalada en cada equipo, en el mismo grupo (en orden, en la misma pasada):

| Serie | Qué es |
|-------|--------|
| `vigia_producto_ciclo{nombre, producto, producto_nombre, ciclo, version}` | 1 por equipo y producto. La distribución sale de `node_os_info` (`os_ids` del catálogo: debian, raspbian, ubuntu); OMV, Proxmox VE y DSM, de `vigia_producto_info` del updates-exporter ([actualizaciones.md](actualizaciones.md)); el software de los contenedores, de la imagen en cAdvisor (con la etiqueta `contenedor`) |
| `vigia_soporte_restante_dias{…}` | Días hasta el fin de soporte; negativo si ya no tiene |
| `vigia_version_mayor_disponible{…, ultimo}` | 1 si el ciclo instalado es anterior al de referencia |

## Alertas

| Regla | Gravedad | Cuándo avisa |
|-------|----------|--------------|
| Sistema sin soporte | critical | pasado el fin de soporte |
| Fin de soporte cercano | warning | quedan menos de `vigia_ciclo_aviso_dias` (`umbrales.soporte_dias`, 90, o el del producto) |
| Versión mayor disponible | info | hay un ciclo de referencia más nuevo |
| Versión fuera del catálogo | info | la versión instalada no está en el catálogo: ¿actualizar vigia? |
| Catálogo de ciclos antiguo | info | el catálogo de un producto en uso tiene más de `umbrales.catalogo_dias` (180) |

Todas son de categoría `mantenimiento` y se generan si hay algún node_exporter o el updates-exporter está
activo. Un host con OMV recibe los avisos de Debian (node_exporter) y los de OMV (updates-exporter, script v2).

El catálogo viaja con cada versión de vigia: un sitio que no actualiza vigia se queda con las fechas de esa
versión.
