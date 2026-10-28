"""Tareas programadas vigiladas por el colector textfile de node_exporter (docs/tareas.md).

Cada tarea escribe en TEXTFILE_DIR/<tarea>.prom (atómico: .prom.tmp + mv):
  vigia_tarea_ultimo_exito_timestamp_seconds{tarea="…"}  epoch de la última ejecución correcta
  vigia_tarea_ultimo_resultado{tarea="…"}                0 = bien, 1 = error
Prometheus añade `nombre` (el host). Las expresiones se unen con `or`, un término por tarea declarada y
filtrado por su host: una tarea con el mismo nombre en otro host no cuenta.
"""

from __future__ import annotations

from collections.abc import Callable

from vigia.dashboards.base import promql_escape
from vigia.model import Host, Site, Tarea

TEXTFILE_DIR = "/var/lib/vigia/textfile"
EXITO = "vigia_tarea_ultimo_exito_timestamp_seconds"
RESULTADO = "vigia_tarea_ultimo_resultado"


def textfile_activo(h: Host) -> bool:
    """vigia despliega el node_exporter de `h` con el colector textfile (y crea la carpeta)."""
    ne = h.node_exporter
    return bool(ne and ne.gestion == "vigia" and ne.textfile)


def _sel(s: Site, t: Tarea) -> str:
    return f'nombre="{promql_escape(s.get_host(t.host).display_name)}", tarea="{promql_escape(t.nombre)}"'


def _por_tarea(s: Site, term: Callable[[Tarea, str], str]) -> str:
    return " or ".join(term(t, _sel(s, t)) for t in s.tareas)


def _edad(sel: str) -> str:
    return f"(time() - max by (nombre, tarea) ({EXITO}{{{sel}}})) / 3600"


def edad_horas(s: Site) -> str:
    """Horas desde la última ejecución correcta de cada tarea."""
    return _por_tarea(s, lambda t, sel: _edad(sel))


def retraso(s: Site) -> str:
    """Horas de más sobre `max_horas` (> 0 = retrasada)."""
    return _por_tarea(s, lambda t, sel: f"{_edad(sel)} - {t.max_horas}")


def margen(s: Site) -> str:
    """Horas que quedan hasta `max_horas` (< 0 = retrasada), para el panel."""
    return _por_tarea(s, lambda t, sel: f"{t.max_horas} - {_edad(sel)}")


def resultado(s: Site) -> str:
    """Último resultado: 0 bien, 1 error, 2 sin datos (no ha escrito nunca)."""
    return _por_tarea(
        s, lambda t, sel: f"max by (nombre, tarea) ({RESULTADO}{{{sel}}}) or 2 * absent({RESULTADO}{{{sel}}})"
    )


def ultimo_error(s: Site) -> str:
    """Último resultado de cada tarea (solo las que han escrito)."""
    return _por_tarea(s, lambda t, sel: f"max by (nombre, tarea) ({RESULTADO}{{{sel}}})")


def sin_datos(s: Site) -> str:
    """1 por cada tarea declarada que no ha escrito nunca su métrica de éxito."""
    return _por_tarea(s, lambda t, sel: f"absent({EXITO}{{{sel}}})")
