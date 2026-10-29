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

El catálogo viaja con cada versión de vigia: un sitio que no actualiza vigia se queda con las fechas de esa
versión.
