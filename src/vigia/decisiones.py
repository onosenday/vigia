"""Decisiones del sitio sobre /pendientes (`modulos.bot.decisiones`, docs/bot.md).

Lo que ya está decidido y no pide acción, con el motivo. Toda decisión caduca: cuando lo ofrecido cambia
(`ofrecido`) o en una fecha (`revisar`), así el fichero solo guarda lo vigente.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

Seccion = Literal["soporte", "versiones", "imagenes", "digest"]
"""Las secciones de /pendientes donde decidir tiene sentido (las demás siempre piden acción)."""


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seccion: Seccion
    host: str = Field(min_length=1, max_length=100)
    """Nombre visible del host (la etiqueta `nombre`)."""
    objeto: str = Field(min_length=1, max_length=100)
    """Contenedor (imagenes, digest) o producto (soporte, versiones)."""
    motivo: str = Field(min_length=1, max_length=200)
    ofrecido: str | None = Field(default=None, min_length=1, max_length=100)
    """Lo que se descarta: ciclo (soporte), versión (versiones) o etiqueta remota (imagenes)."""
    revisar: dt.date | None = None
    ref: str | None = Field(default=None, min_length=1, max_length=60)

    @field_validator("host", "objeto", "ofrecido", "ref", mode="before")
    @classmethod
    def _texto(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v

    @model_validator(mode="after")
    def _caduca(self) -> Decision:
        if self.ofrecido is None and self.revisar is None:
            raise ValueError("toda decisión necesita `ofrecido` o `revisar` (si no, no caduca nunca)")
        if self.seccion == "digest" and self.ofrecido is not None:
            raise ValueError("en `digest` no hay versión ofrecida: usa `revisar`")
        return self


_LISTA = TypeAdapter(list[Decision])


def load_decisiones(path: Path, hosts: Iterable[str]) -> list[Decision]:
    """Lee y valida el fichero (solo `yaml.safe_load`); `hosts`, los nombres visibles del sitio."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    lista = _LISTA.validate_python(data if data is not None else [])
    malos = sorted({d.host for d in lista} - set(hosts))
    if malos:
        raise ValueError(f"{path.name}: hosts que no están en site.yaml: {malos}")
    return lista


def a_json(decisiones: Sequence[Decision]) -> list[dict[str, Any]]:
    """Para el config.json del bot (sin los campos vacíos)."""
    return [d.model_dump(mode="json", exclude_none=True) for d in decisiones]


def quitar_entradas(texto: str, indices: set[int]) -> str:
    """Quita las entradas `indices` (posición en la lista) sin tocar el resto del texto.

    Cada entrada es su línea `- ` de la columna 0 más las líneas sangradas que la siguen. Los comentarios y
    líneas en blanco de primer nivel se conservan. Si el fichero no tiene esa forma, no se toca.
    """
    lineas = texto.splitlines(keepends=True)
    inicios = [i for i, linea in enumerate(lineas) if linea.startswith("- ")]
    data = yaml.safe_load(texto)
    if not isinstance(data, list) or len(data) != len(inicios):
        raise ValueError(
            "formato que --limpiar no sabe editar (una entrada por `- ` en la columna 0): hazlo a mano"
        )
    fuera: set[int] = set()
    for k, ini in enumerate(inicios):
        if k not in indices:
            continue
        fin = ini + 1
        while fin < len(lineas) and lineas[fin].startswith((" ", "\t")):
            fin += 1
        fuera.update(range(ini, fin))
    return "".join(linea for i, linea in enumerate(lineas) if i not in fuera)
