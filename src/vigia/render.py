"""Motor de plantillas seguro por defecto.

Cada `{{ expresión }}` de una plantilla sale como escalar YAML entrecomillado (JSON es un subconjunto de
YAML): un dato del sitio nunca puede romper la estructura ni inyectar claves. Solo `Crudo`, que construye
el propio paquete con valores ya validados, se inserta tal cual.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import jinja2
import yaml


class Crudo(str):
    """Fragmento generado por vigia (no por el sitio) que se inserta sin entrecomillar."""

    __slots__ = ()


def escalar(v: Any) -> str:
    if isinstance(v, Crudo):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return json.dumps(v)
    if v is None:
        return "null"
    if isinstance(v, str | list | tuple | dict):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError(f"valor no permitido en una plantilla: {type(v).__name__}")


def entorno() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FunctionLoader(_cargar),
        undefined=jinja2.StrictUndefined,
        finalize=escalar,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # noqa: S701 - no es HTML: el escape es `escalar` (finalize), aplicado a todo
    )
    env.filters["crudo"] = lambda v: Crudo(v)
    return env


def _cargar(nombre: str) -> str:
    return files("vigia").joinpath("templates", nombre).read_text(encoding="utf-8")


def plantilla(nombre: str, **ctx: Any) -> str:
    texto = entorno().get_template(nombre).render(**ctx)
    yaml.safe_load(texto)  # lo generado tiene que ser YAML válido
    return texto


def volcar_yaml(datos: Any, cabecera: str = "") -> str:
    """YAML de datos (objetivos, listas) sin plantilla: `safe_dump` y orden estable."""
    cuerpo = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120)
    return (cabecera + "\n" if cabecera else "") + cuerpo
