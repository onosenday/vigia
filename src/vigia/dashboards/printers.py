"""Panel «Impresoras»: estado, páginas, consumibles y errores.

SNMP con printer_mib, hrDevice y vigia_impresora (módulo propio de vigia).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia.dashboards.base import Panel, merged_table, panel, row

if TYPE_CHECKING:
    from vigia.dashboards import Brand
    from vigia.model import Site

PJ = 'job="snmp",tipo="impresora"'
# «Black Toner, PN 006R01742;SN8063…»: el número de serie del cartucho sobra en el panel
NO_SERIAL = [{"id": "renameByRegex", "options": {"regex": "^([^;]*);.*$", "renamePattern": "$1"}}]


def printers(s: Site, m: Brand) -> dict[str, Any] | None:
    if not s.printers_snmp:
        return None
    pct = s.alertas.umbrales.consumible_pct
    status = merged_table(
        2,
        "Estado",
        [
            (f"max by (nombre, hrPrinterStatus) (hrPrinterStatus{{{PJ}}} == 1)", "Estado"),
            (f"max by (nombre) (prtMarkerLifeCount{{{PJ}}})", "Páginas"),
            (f"max by (nombre) (increase(prtMarkerLifeCount{{{PJ}}}[24h]))", "Últimas 24 h"),
        ],
        0,
        1,
        12,
        6,
        key="Impresora",
    )
    errors = merged_table(
        3,
        "Errores activos",
        [(f"max by (nombre, vigia_impresora_error) (vigia_impresora_error{{{PJ}}} == 1)", "Activo")],
        12,
        1,
        12,
        6,
        key="Impresora",
    )
    errors["transformations"][1]["options"]["renameByName"]["vigia_impresora_error"] = "Error"
    errors["fieldConfig"]["defaults"]["noValue"] = "Sin errores"
    supplies = panel(
        4,
        "Consumibles",
        "bargauge",
        f"100 * prtMarkerSuppliesLevel{{{PJ}}} / (prtMarkerSuppliesMaxCapacity{{{PJ}}} > 0) >= 0",
        0,
        7,
        24,
        9,
        legend="{{nombre}} · {{prtMarkerSuppliesDescription}}",
        unit="percent",
        instant=True,
        thresholds=[
            {"color": "red", "value": None},
            {"color": "orange", "value": pct},
            {"color": "green", "value": max(pct * 2, 25)},
        ],
        options={"orientation": "horizontal", "displayMode": "gradient", "min": 0, "max": 100},
        transform=NO_SERIAL,
    )
    pages = panel(
        5,
        "Páginas por hora",
        "timeseries",
        f"sum by (nombre) (increase(prtMarkerLifeCount{{{PJ}}}[1h]))",
        0,
        16,
        24,
        7,
        unit="short",
    )
    panels: list[Panel] = [row(1, "Impresoras", 0), status, errors, supplies, pages]
    return m.dash("impresoras", "Impresoras", panels, time_from="now-7d")
