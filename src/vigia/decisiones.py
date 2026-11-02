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

    @field_validator("host", "objeto", "ref", mode="before")
    @classmethod
    def _texto(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v

    @field_validator("ofrecido", mode="before")
    @classmethod
    def _version(cls, v: Any) -> Any:
        # YAML convierte 3.10 en 3.1 y 016 en 14: una versión sin comillas cambia sin avisar.
        if isinstance(v, int | float) and not isinstance(v, bool):
            raise ValueError('pon la versión entre comillas (p. ej. ofrecido: "18")')
        return v

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
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, ValueError) as e:
        raise ValueError(f"{path.name}: {e}") from e
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

    Cada entrada es su línea `- ` de la columna 0 más las líneas sangradas que la siguen (y las líneas en
    blanco entre ellas). Los comentarios y líneas en blanco de primer nivel se conservan. Si el fichero no
    tiene esa forma, o el resultado no es exactamente la lista sin esas entradas, se rechaza.
    """
    a_mano = "formato que --limpiar no sabe editar (una entrada por `- ` en la columna 0): hazlo a mano"
    lineas = texto.splitlines(keepends=True)
    inicios = [i for i, linea in enumerate(lineas) if linea.startswith("- ")]
    try:
        data = yaml.safe_load(texto)
    except (yaml.YAMLError, ValueError) as e:
        raise ValueError(f"{e}; {a_mano}") from e
    fuera_de_rango = any(not 0 <= k < len(inicios) for k in indices)
    if not isinstance(data, list) or len(data) != len(inicios) or fuera_de_rango:
        raise ValueError(a_mano)
    fuera: set[int] = set()
    for k, ini in enumerate(inicios):
        if k not in indices:
            continue
        fin = ini + 1
        while fin < len(lineas):
            sig = fin
            while sig < len(lineas) and not lineas[sig].strip():
                sig += 1
            if sig < len(lineas) and lineas[sig].startswith((" ", "\t")):
                fin = sig + 1
            else:
                break
        fuera.update(range(ini, fin))
    nuevo = "".join(linea for i, linea in enumerate(lineas) if i not in fuera)
    if not nuevo.endswith("\n") and nuevo:
        nuevo += "\n"
    try:
        ok = yaml.safe_load(nuevo) == [e for k, e in enumerate(data) if k not in indices]
    except (yaml.YAMLError, ValueError):
        ok = False
    if not ok:
        raise ValueError(a_mano)
    return nuevo
