---
name: vigia-actualizar
description: Comprobar si es seguro subir el sitio a otra versión de vigia antes de cambiar el tag - compara lo desplegado con el repo, lee las novedades, valida y genera el sitio con la versión nueva en seco y clasifica las diferencias por riesgo (alto, medio, bajo). Usar cuando el usuario quiera actualizar vigia, pregunte si hay una versión nueva o si algo se romperá al subir.
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

## Cómo presentarlo al usuario

- El veredicto, los puntos ALTO y MEDIO uno a uno con lo que implican (qué se reinicia, qué se pierde) y las
  novedades que le afectan. Los BAJO, resumidos.
- Con ALTO: no proponer la subida hasta resolver o entender cada punto (p. ej. copia de los datos antes de
  cambiar la imagen de Prometheus).
- La subida en sí sigue el procedimiento del sitio, con OK: tag en `pyproject.toml`, rango `vigia:` en
  `site.yaml`, `uv sync`, `uv run vigia skill .`, `validate`, `deploy <unidad>` (diff) y `--yes`.
  Rollback: tag anterior, `uv sync` y `uv run vigia rollback <unidad> --yes`.
