"""Panel «Tareas»: tareas programadas que escriben su estado en el textfile de node_exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia import tareas
from vigia.dashboards.base import Panel, merged_table, row

if TYPE_CHECKING:
    from vigia.dashboards import Brand
    from vigia.model import Site

RESULTADO = [
    {
        "type": "value",
        "options": {
            "0": {"text": "bien", "color": "green"},
            "1": {"text": "error", "color": "red"},
            "2": {"text": "sin datos", "color": "text"},
        },
    }
]


def tasks(s: Site, m: Brand) -> dict[str, Any] | None:
    if not s.tareas:
        return None
    table = merged_table(
        2,
        "Tareas programadas",
        [
            (tareas.edad_horas(s), "Último éxito (h)"),
            (tareas.margen(s), "Margen (h)"),
            (tareas.resultado(s), "Resultado"),
        ],
        0,
        1,
        24,
        max(4, 2 + len(s.tareas)),
        key="Host",
    )
    table["transformations"][1]["options"]["renameByName"]["tarea"] = "Tarea"
    table["options"]["sortBy"] = [{"displayName": "Host", "desc": False}]
    table["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "Último éxito (h)"},
            "properties": [{"id": "decimals", "value": 1}],
        },
        {
            "matcher": {"id": "byName", "options": "Margen (h)"},
            "properties": [
                {"id": "decimals", "value": 1},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {
                    "id": "thresholds",
                    "value": {
                        "mode": "absolute",
                        "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}],
                    },
                },
            ],
        },
        {
            "matcher": {"id": "byName", "options": "Resultado"},
            "properties": [
                {"id": "mappings", "value": RESULTADO},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
            ],
        },
    ]
    panels: list[Panel] = [row(1, "Tareas", 0), table]
    return m.dash("tareas", "Tareas", panels, time_from="now-7d")
