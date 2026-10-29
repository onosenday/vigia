---
name: vigia-actualizar
description: Comprobar si es seguro subir el sitio a otra versión de vigia antes de cambiar el tag - compara lo desplegado con el repo, lee las novedades, valida y genera el sitio con la versión nueva en seco y clasifica las diferencias por riesgo (alto, medio, bajo) - y decidir qué novedades aprovecha el sitio, dejándolas anotadas en su proyecto. Usar cuando el usuario quiera actualizar vigia, pregunte si hay una versión nueva o si algo se romperá al subir.
---

# Comprobar una subida de versión de vigia

Desde la raíz del repo del sitio (el que tiene `site.yaml` y `pyproject.toml`):

```bash
uv run python .claude/skills/vigia-actualizar/comprobar.py --a v0.4.0
```

- `--sin-desplegado`: no compara con los hosts (sin SSH). El veredicto lo marca como no comprobado.
- `--repo <url o ruta>`: otro origen de vigia; por defecto, el de `pyproject.toml`.
- Tags publicados: `git ls-remote --tags <repo>`.

No cambia el tag ni despliega: trabaja en una carpeta temporal y en un `site.yaml` temporal junto al real,
que borra al terminar.

## Qué hace

1. **Desplegado**: cada unidad (`vigia deploy <unidad>` sin `--yes`) debe dar 0 diferencias. Si no, lo
   desplegado no es lo del repo y la subida mezclaría dos cambios: resolverlo antes.
2. **Novedades**: secciones del `CHANGELOG.md` entre la versión instalada y la nueva.
3. **Validación**: la versión nueva (clon del tag ejecutado con `uvx`) valida el `site.yaml` con el rango
   ajustado. Si no valida, hay que adaptar el `site.yaml` (claves renombradas, campos nuevos).
4. **Diferencias** entre lo que generan la versión instalada y la nueva:

| Riesgo | Qué |
|--------|-----|
| ALTO | `site.yaml` no valida; lo desplegado no coincide con el repo; cambia la imagen de Prometheus o Grafana (guardan datos), los volúmenes o los parámetros de almacenamiento; desaparece un panel o cambia su `uid` |
| MEDIO | reinicios (otra imagen, parámetros o entorno de un servicio), alertas, configuración de Prometheus, imágenes propias que se reconstruyen, servicios nuevos o retirados |
| BAJO | paneles, objetivos o textos |

## Aprovechar las novedades

Una versión nueva no solo puede romper cosas: también trae funciones y lecciones que el sitio puede usar. Con
las novedades del punto 2 (y, tras la subida, con `git diff .claude/skills/` después de `vigia skill`, que
muestra lo nuevo de la skill `vigia`: lecciones de plataformas, falsos positivos, diagnóstico):

1. **Leer cada novedad contra este sitio**: su `site.yaml` (tipos de equipo, módulos activos, autenticaciones),
   el `CLAUDE.md` del proyecto y sus tareas abiertas. Para cada una, decidir:
   - **Aplicable ya**: el sitio tiene el caso (un equipo de ese tipo, un módulo activo, un problema conocido
     que la novedad resuelve). Proponer el cambio concreto en `site.yaml`, con su impacto.
   - **Útil más adelante**: no hay el caso hoy, pero lo habrá o encaja con algo planeado.
   - **No aplica**: se descarta sin más.
2. **Dejarlo registrado en el proyecto del sitio**, para que no dependa de esta sesión:
   - Lo aplicable ya y lo útil más adelante, como tareas en el gestor de tareas del proyecto (beads si lo
     tiene), una por novedad, con la versión de vigia que la trae y qué habría que cambiar.
   - Lo que cambia cómo se opera el sitio (una regla, una lección que contradice lo que dice su `CLAUDE.md`),
     como nota en ese `CLAUDE.md`. Las lecciones genéricas no se copian: ya están en la skill `vigia`.
3. **Presentarlo al usuario** junto al veredicto de riesgo: qué se puede aprovechar, qué ha quedado anotado y
   dónde. Nada de esto se aplica sin su OK; cada cambio sigue el flujo normal (diff, OK, `--yes`).

## Cómo presentarlo al usuario

- El veredicto, los puntos ALTO y MEDIO uno a uno con lo que implican (qué se reinicia, qué se pierde) y las
  novedades que le afectan. Los BAJO, resumidos. Después, lo aprovechable (sección anterior).
- Con ALTO: no proponer la subida hasta resolver o entender cada punto (p. ej. copia de los datos antes de
  cambiar la imagen de Prometheus).
- La subida en sí sigue el procedimiento del sitio, con OK: tag en `pyproject.toml`, rango `vigia:` en
  `site.yaml`, `uv sync`, `uv run vigia skill .`, `validate`, `deploy <unidad>` (diff) y `--yes`.
  Rollback: tag anterior, `uv sync` y `uv run vigia rollback <unidad> --yes`.
