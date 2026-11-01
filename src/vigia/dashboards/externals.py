"""Panel «Externos»: equipos y webs fuera de la red del sitio (sondas salientes desde el monitor)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia.dashboards.base import UPDOWN, Panel, merged_table, panel, row

if TYPE_CHECKING:
    from vigia.dashboards import Brand
    from vigia.model import Site

EJ = 'job="externo", tipo!="cerrado"'
CLOSED = 'job="externo", tipo="cerrado"'
EXPOSED = [
    {
        "type": "value",
        "options": {"0": {"text": "Cerrado", "color": "green"}, "1": {"text": "EXPUESTO", "color": "red"}},
    }
]


def externals(s: Site, m: Brand) -> dict[str, Any] | None:
    if not s.externos.objetivos:
        return None
    by = "nombre, tipo, puerto"
    table = merged_table(
        2,
        "Estado",
        [
            (f"max by ({by}) (probe_success{{{EJ}}})", "Responde"),
            (f"max by ({by}) (probe_duration_seconds{{{EJ}}})", "Tiempo"),
            (f"max by ({by}) (probe_http_status_code{{{EJ}}})", "HTTP"),
            (
                f"min by ({by}) ((probe_ssl_earliest_cert_expiry{{{EJ}}} - time()) / 86400)",
                "Certificado (días)",
            ),
        ],
        0,
        1,
        24,
        8,
    )
    renames = table["transformations"][1]["options"]["renameByName"]
    renames.update({"tipo": "Sonda", "puerto": "Puerto"})
    table["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "Responde"},
            "properties": [{"id": "mappings", "value": UPDOWN}],
        },
        {"matcher": {"id": "byName", "options": "Tiempo"}, "properties": [{"id": "unit", "value": "s"}]},
        {
            "matcher": {"id": "byName", "options": "Certificado (días)"},
            "properties": [{"id": "decimals", "value": 0}],
        },
    ]
    latency = panel(
        3,
        "Tiempo de respuesta",
        "timeseries",
        f"max by (nombre, tipo) (probe_duration_seconds{{{EJ}}})",
        0,
        9,
        24,
        8,
        legend="{{nombre}} ({{tipo}})",
        unit="s",
    )
    panels: list[Panel] = [row(1, "Fuera de la red del sitio", 0), table, latency]
    if any(o.puertos_cerrados for o in s.externos.objetivos):
        closed = merged_table(
            4,
            "Puertos que deben estar cerrados",
            [(f"max by (nombre, puerto) (probe_success{{{CLOSED}}})", "Estado")],
            0,
            18,
            24,
            6,
        )
        closed["transformations"][1]["options"]["renameByName"]["puerto"] = "Puerto"
        closed["fieldConfig"]["overrides"] = [
            {
                "matcher": {"id": "byName", "options": "Estado"},
                "properties": [{"id": "mappings", "value": EXPOSED}],
            }
        ]
        panels.append(closed)
    return m.dash("externos", "Externos", panels)
