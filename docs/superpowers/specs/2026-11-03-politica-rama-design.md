# Política de rama por producto (vigia-y5q)

## Problema

vigia fija algunas versiones por un motivo (Prometheus en su LTS: las demás ramas duran 6 semanas), pero el
motivo no llega a los sitios. What's Up Docker ofrece el tag más nuevo de otra rama (`v3.13.5` → `v3.15.1`) y
salta la alerta «Versión nueva de una imagen», aparece en el panel «Mantenimiento» y en `/pendientes`. Cada
sitio tendría que descubrir el porqué y escribir su propia decisión en `decisiones.yaml`, que además no
silencia la alerta de Grafana.

## Objetivo

Que el catálogo de ciclos declare la política de rama de un producto con su motivo, y que alertas, panel y bot
la respeten sin que el sitio escriba nada. Fuera de alcance: que las decisiones del sitio silencien alertas
(pieza aparte).

## Diseño

### 1. Catálogo

Campo opcional en `Producto` (`src/vigia/ciclos.py`):

```yaml
politica: {rama: lts, motivo: "vigia sigue la LTS; las demás ramas duran 6 semanas"}
```

- `rama`: `lts` (único valor por ahora; sin `politica` = todas las ramas, como hoy).
- `motivo`: 1-120 caracteres, mismo patrón seguro que `nombre` (va en una etiqueta de Prometheus y en el bot).
- Validación: `rama: lts` exige al menos un ciclo con `lts: true` y `imagen_regex` (la política se aplica a
  imágenes).
- `vigia ciclos actualizar` conserva `politica` al refrescar desde endoflife.date.
- Se añade en `catalogo/prometheus.yaml`.

### 2. Reglas de grabación

En `ciclos.reglas`, para cada producto con `politica.rama == "lts"`:

- Constante `vigia_politica_ciclo{producto, ciclo, lts, motivo}` = 1 por cada ciclo del catálogo
  (`lts` = `"true"`/`"false"`), salvo que el sitio la desactive.
- Derivada `vigia_imagen_descartada{nombre, contenedor, local, remota, producto, motivo}` = 1 cuando, en
  `wud_containers{nueva="true", tipo="tag"}`:
  - el ciclo de `imagen:local` es LTS (`* on (producto, ciclo) … {lts="true"}`), y
  - el ciclo de `imagen:remota` es un ciclo conocido no LTS (`* on (producto, ciclo_remota) … {lts="false"}`).

  El ciclo se saca con `label_join` (`imagen` + `:` + tag) y `label_replace` con `imagen_regex` y
  `ciclo_regex`, como en `_desde_contenedor`.
- Si la local no está en una LTS no se descarta nada: ese sitio sí debe moverse (y ya le avisa «Fin de soporte
  cercano»). Un tag remoto de la misma LTS (`v3.13.6`) se sigue avisando.
- Se generan siempre (sin `wud_containers` no producen series).

### 3. Consumidores

- Alerta `vigia-imagen-version` (`alerting.image_rules`): `wud_containers{…} unless on (nombre, contenedor,
  remota) vigia_imagen_descartada`.
- Panel «Mantenimiento» (`dashboards/mantenimiento.py`): misma exclusión en la tabla de imágenes nuevas.
- `/pendientes` (`bot/pendientes.py`): consulta `vigia_imagen_descartada`; las líneas que casan por
  (`nombre`, `contenedor`, `remota`) van a «Decidido» con `(vigia) <motivo>`. Una decisión del sitio sobre la
  misma línea tiene prioridad (su motivo es más concreto) y sigue contando como usada para `vigia decisiones`.
- `docs/imagenes.md`, `docs/ciclos.md` y `docs/bot.md` lo explican.

### 4. Salida del sitio

`site.yaml`, junto a la `fecha_aviso` por producto que ya existe:

```yaml
ciclos:
  politica: {prometheus: todas}   # el sitio sigue todas las ramas: avisa también de la 3.15
```

Único valor: `todas` (desactiva la política del catálogo para ese producto); sin entrada, se aplica la de
vigia. Producto desconocido o sin política en el catálogo → error de validación. Se lleva a las reglas igual
que `fecha_aviso` (parámetro de `ciclos.reglas`).

## Errores y casos límite

- Tag remoto sin versión (`latest`) o que no casa con `imagen_regex`: no se descarta (se avisa como hoy).
- Ciclo remoto fuera del catálogo (vigia antiguo): no se descarta (no se sabe si es LTS); ya avisa «Catálogo
  de ciclos antiguo» cuando toca.
- Nueva LTS publicada y catalogada: su ciclo es LTS, así que se ofrece sola.

## Tests

- `test_ciclos.py`: validación de `politica` (sin LTS, sin `imagen_regex`, motivo con caracteres prohibidos)
  y que `actualizar` la conserva.
- `test_ciclos_promtool.py` (`promtool test rules`): 3.13.5 → 3.15.1 descartada; 3.13.5 → 3.13.6 avisada;
  3.15.1 → 3.16.0 avisada; sitio con `todas`: sin series.
- `test_alerting.py`, `test_dashboards.py`: la exclusión está en la expresión.
- `test_bot_pendientes.py`: línea descartada en «Decidido» con `(vigia)`; la decisión del sitio gana.
- `test_model.py`: `ciclos.politica` válida e inválida.
- Golden regenerados.
