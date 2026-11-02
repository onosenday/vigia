"""Decisiones del sitio en /pendientes (vigia.decisiones, docs/bot.md): qué línea cubre cada una.

Sin pydantic ni vigia: el bot corre en su contenedor solo con la biblioteca estándar.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

VIGENTE, OBSOLETA, VENCIDA = "vigente", "obsoleta", "vencida"


@dataclass(frozen=True)
class Decision:
    seccion: str
    host: str
    objeto: str
    motivo: str
    ofrecido: str | None = None
    revisar: date | None = None
    ref: str | None = None


def desde_json(lista: Iterable[Mapping[str, Any]]) -> tuple[Decision, ...]:
    return tuple(
        Decision(
            seccion=str(d["seccion"]),
            host=str(d["host"]),
            objeto=str(d["objeto"]),
            motivo=str(d["motivo"]),
            ofrecido=None if d.get("ofrecido") is None else str(d["ofrecido"]),
            revisar=date.fromisoformat(d["revisar"]) if d.get("revisar") else None,
            ref=None if d.get("ref") is None else str(d["ref"]),
        )
        for d in lista
    )


@dataclass
class Juez:
    """Reparte las líneas de /pendientes entre las decisiones y recuerda cuáles se han usado."""

    decisiones: tuple[Decision, ...]
    hoy: date
    _usadas: set[int] = field(default_factory=set)

    def vencida(self, d: Decision) -> bool:
        return d.revisar is not None and d.revisar <= self.hoy

    def busca(self, seccion: str, m: Mapping[str, str], ofrecido: str | None = None) -> Decision | None:
        """La primera decisión vigente que cubre esta línea (etiquetas `m` de Prometheus), o None."""
        objetos = {m.get("contenedor"), m.get("producto")} - {None, ""}
        for i, d in enumerate(self.decisiones):
            if (
                d.seccion == seccion
                and d.host == m.get("nombre")
                and d.objeto in objetos
                and (d.ofrecido is None or d.ofrecido == ofrecido)
                and not self.vencida(d)
            ):
                self._usadas.add(i)
                return d
        return None

    def estado(self) -> list[tuple[Decision, str]]:
        """Cada decisión con su estado, en el orden del fichero (tras repartir todas las líneas)."""
        return [
            (d, VENCIDA if self.vencida(d) else VIGENTE if i in self._usadas else OBSOLETA)
            for i, d in enumerate(self.decisiones)
        ]
