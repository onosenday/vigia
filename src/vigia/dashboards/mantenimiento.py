"""Panel «Mantenimiento»: versiones y fin de soporte, actualizaciones de los hosts e imágenes nuevas.

Lo mismo que /pendientes del bot, en tablas: sale de las reglas de ciclos (docs/ciclos.md), del
updates-exporter (docs/actualizaciones.md) y de What's Up Docker (docs/imagenes.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia import ciclos
from vigia.dashboards.base import Panel, merged_table, row

if TYPE_CHECKING:
    from vigia.dashboards import Brand
    from vigia.model import Site

_PRODUCTO = "nombre, contenedor, producto_nombre, ciclo, version"
COLUMNAS = {
    "nombre": "Host",
    "contenedor": "Contenedor",
    "producto_nombre": "Producto",
    "ciclo": "Ciclo",
    "version": "Versión",
    "ultimo": "Última",
}


def _soporte(s: Site, pid: int, y: int) -> Panel:
    t = merged_table(
        pid,
        "Versiones y soporte",
        [
            (
                f"max by ({_PRODUCTO}, ultimo) "
                f"({ciclos.PRODUCTO_CICLO} * on (producto, ciclo) group_left (ultimo) {ciclos.INFO})",
                "_",
            ),
            (f"max by ({_PRODUCTO}) ({ciclos.RESTANTE})", "Soporte (días)"),
        ],
        0,
        y,
        24,
        10,
        key="Host",
    )
    org = t["transformations"][1]["options"]
    org["renameByName"] |= COLUMNAS
    org["excludeByName"]["_"] = True
    org["indexByName"] = {c: i for i, c in enumerate([*COLUMNAS.values(), "Soporte (días)"])}
    t["options"]["sortBy"] = [{"displayName": "Soporte (días)", "desc": False}]
    t["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "Soporte (días)"},
            "properties": [
                {"id": "decimals", "value": 0},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {
                    "id": "thresholds",
                    "value": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "red", "value": None},
                            {"color": "orange", "value": 0},
                            {"color": "green", "value": s.alertas.umbrales.soporte_dias},
                        ],
                    },
                },
            ],
        }
    ]
    return t


def _actualizaciones(pid: int, y: int) -> Panel:
    t = merged_table(
        pid,
        "Actualizaciones de los hosts",
        [
            ("max by (nombre) (vigia_actualizaciones_pendientes)", "Pendientes"),
            ("max by (nombre) (vigia_actualizaciones_seguridad)", "De seguridad"),
        ],
        0,
        y,
        12,
        8,
        key="Host",
    )
    t["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "De seguridad"},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {
                    "id": "thresholds",
                    "value": {
                        "mode": "absolute",
                        "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 1}],
                    },
                },
            ],
        }
    ]
    return t


def _imagenes(pid: int, x: int, y: int, w: int) -> Panel:
    t = merged_table(
        pid,
        "Imágenes nuevas",
        [('max by (nombre, contenedor, imagen, tipo, local, remota) (wud_containers{nueva="true"})', "_")],
        x,
        y,
        w,
        8,
        key="Host",
    )
    org = t["transformations"][1]["options"]
    org["renameByName"] |= {"contenedor": "Contenedor", "imagen": "Imagen", "tipo": "Tipo", "local": "Local"}
    org["renameByName"]["remota"] = "Nueva"
    org["excludeByName"]["_"] = True
    return t


def mantenimiento(s: Site, m: Brand) -> dict[str, Any] | None:
    versiones = ciclos.hay_versiones(s)
    updates = s.modulos.updates_exporter.activo
    imagenes = any(h.imagenes for h in s.hosts)
    if not (versiones or updates or imagenes):
        return None
    panels: list[Panel] = [row(1, "Mantenimiento", 0)]
    y = 1
    if versiones:
        panels.append(_soporte(s, 2, y))
        y += 10
    if updates:
        panels.append(_actualizaciones(3, y))
    if imagenes:
        panels.append(_imagenes(4, 12 if updates else 0, y, 12 if updates else 24))
    return m.dash("mantenimiento", "Mantenimiento", panels, time_from="now-24h")
