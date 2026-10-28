"""Motor de plantillas seguro por defecto.

Cada `{{ expresión }}` de una plantilla sale como escalar YAML entrecomillado (JSON es un subconjunto de
YAML): un dato del sitio nunca puede romper la estructura ni inyectar claves. Solo `Raw`, que construye
el propio paquete con valores ya validados, se inserta tal cual.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import jinja2
import yaml

from vigia.tareas import TEXTFILE_DIR


class Raw(str):
    """Fragmento generado por vigia (no por el sitio) que se inserta sin entrecomillar."""

    __slots__ = ()


def to_scalar(v: Any) -> str:
    if isinstance(v, Raw):
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


def jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FunctionLoader(_load_template),
        undefined=jinja2.StrictUndefined,
        finalize=to_scalar,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # noqa: S701 - no es HTML: el escape es `to_scalar` (finalize), aplicado a todo
    )
    env.globals["TEXTFILE_DIR"] = TEXTFILE_DIR
    env.filters["raw"] = lambda v: Raw(v)
    return env


def _load_template(name: str) -> str:
    return files("vigia").joinpath("templates", name).read_text(encoding="utf-8")


def render_template(name: str, **ctx: Any) -> str:
    text = jinja_env().get_template(name).render(**ctx)
    yaml.safe_load(text)  # lo generado tiene que ser YAML válido
    return text


def dump_yaml(data: Any, header: str = "") -> str:
    """YAML de datos (objetivos, listas) sin plantilla: `safe_dump` y orden estable."""
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120)
    return (header + "\n" if header else "") + body
