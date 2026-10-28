"""Textos del bot: HTML de Telegram escapado, compacto y con horas locales."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

MAX_LINEAS = 30
MAX_CARACTERES = 4000
"""Telegram admite 4096 caracteres por mensaje."""


def esc(v: object) -> str:
    return html.escape(str(v), quote=False)


def recortar(lineas: list[str], maximo: int = MAX_LINEAS) -> str:
    """Como mucho `maximo` líneas (la última dice cuántas faltan) y MAX_CARACTERES caracteres.

    El corte por caracteres se hace en un salto de línea o en «, » para no partir una entidad ni una etiqueta.
    """
    if len(lineas) > maximo:
        lineas = [*lineas[: maximo - 1], f"… y {len(lineas) - maximo + 1} más"]
    texto = "\n".join(lineas)
    if len(texto) <= MAX_CARACTERES:
        return texto
    limite = MAX_CARACTERES - 2
    corte = max(texto.rfind("\n", 0, limite), texto.rfind(", ", 0, limite))
    return texto[: corte if corte > 0 else limite] + " …"


def duracion(segundos: float) -> str:
    s = int(max(segundos, 0))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h {s % 3600 // 60} min"
    return f"{s // 86400} d {s % 86400 // 3600} h"


def hora(ts: float, ahora: float, zona: str) -> str:
    """14:05 si es hoy, «ayer 23:10» si fue ayer y «20-10 09:00» si es anterior."""
    tz = ZoneInfo(zona)
    t, n = datetime.fromtimestamp(ts, tz), datetime.fromtimestamp(ahora, tz)
    if t.date() == n.date():
        return t.strftime("%H:%M")
    if (n.date() - t.date()).days == 1:
        return "ayer " + t.strftime("%H:%M")
    return t.strftime("%d-%m %H:%M")


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}%"
