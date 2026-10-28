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


def _cortar_linea(linea: str) -> str:
    """Corta una línea suelta en MAX_CARACTERES sin dejar una entidad ni una etiqueta a medias."""
    t = linea[: MAX_CARACTERES - 2]
    corte = max(t.rfind(", "), t.rfind(" "))
    if corte > 0:
        t = t[:corte].rstrip(",")
    for abre, cierra in (("&", ";"), ("<", ">")):
        if t.rfind(abre) > t.rfind(cierra):
            t = t[: t.rfind(abre)]
    return t + " …"


def recortar(lineas: list[str], maximo: int = MAX_LINEAS) -> str:
    """Como mucho `maximo` líneas y MAX_CARACTERES caracteres; la última línea dice cuántas faltan.

    Si pasa de MAX_CARACTERES quita líneas enteras del final. Solo si una línea no cabe por sí sola la corta
    (en «, » o espacio, sin partir una entidad ni una etiqueta) para no mandar HTML inválido a Telegram.
    """
    total = len(lineas)
    if total > maximo:
        lineas = lineas[: maximo - 1]
    resto = [f"… y {total - len(lineas)} más"] if len(lineas) < total else []
    texto = "\n".join([*lineas, *resto])
    if len(texto) <= MAX_CARACTERES:
        return texto
    for k in range(len(lineas) - 1, 0, -1):
        texto = "\n".join([*lineas[:k], f"… y {total - k} más"])
        if len(texto) <= MAX_CARACTERES:
            return texto
    return _cortar_linea(lineas[0])


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
