"""Búsqueda por nombre, IP o MAC sin distinguir mayúsculas ni acentos: primero exacta, luego «contiene»."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence

_MAC = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$")


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).casefold().strip()


def _clave(texto: str) -> str:
    n = normalizar(texto)
    return n.replace("-", ":") if _MAC.match(n) else n


def buscar[T](consulta: str, items: Sequence[T], claves: Callable[[T], Iterable[str]]) -> list[T]:
    q = _clave(consulta)
    if not q:
        return []
    exactos = [i for i in items if q in {_clave(k) for k in claves(i) if k}]
    if exactos:
        return exactos
    return [i for i in items if any(q in _clave(k) for k in claves(i) if k)]
