"""Panel «Dispositivos» (netinv): inventario de todo lo que hay en la red."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia.dashboards.base import DS, Panel, panel, row
from vigia.model import Site

if TYPE_CHECKING:
    from vigia.dashboards import Brand

COLS = [
    "ip",
    "nombre",
    "tipo",
    "ubicacion",
    "fabricante",
    "nombres",
    "nubes_iot",
    "modelo",
    "mdns",
    "puertos",
    "so",
    "mac",
    "aleatoria",
    "Visto",
]
NAMES = {
    "ip": "IP",
    "nombre": "Nombre",
    "tipo": "Tipo",
    "ubicacion": "Ubicación",
    "fabricante": "Fabricante",
    "nombres": "Nombres anunciados",
    "nubes_iot": "Nubes IoT",
    "modelo": "Modelo / UPnP",
    "mdns": "mDNS",
    "puertos": "Puertos",
    "so": "SO (nmap)",
    "mac": "MAC",
    "aleatoria": "MAC aleatoria",
    "Visto": "Visto",
}


def device_table(pid: int, title: str, expr: str, y: int, h: int) -> Panel:
    p = panel(pid, title, "table", expr, 0, y, 24, h, legend="", instant=True)
    p["targets"].append(
        {
            "refId": "B",
            "datasource": DS,
            "expr": "netinv_device_last_seen_seconds * 1000",
            "format": "table",
            "instant": True,
            "range": False,
            "legendFormat": "",
        }
    )
    p["transformations"] = [
        {"id": "joinByField", "options": {"byField": "mac", "mode": "inner"}},
        {"id": "sortBy", "options": {"sort": [{"field": "orden"}]}},
        {
            "id": "organize",
            "options": {
                "includeByName": {c: True for c in COLS if c != "Visto"} | {"Value #B": True},
                "indexByName": {c: i for i, c in enumerate(COLS[:-1])} | {"Value #B": len(COLS) - 1},
                "renameByName": NAMES | {"Value #B": "Visto"},
            },
        },
    ]
    p["fieldConfig"]["defaults"]["custom"] = {"align": "left", "filterable": True}
    p["fieldConfig"]["defaults"]["noValue"] = "—"
    p["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "Visto"},
            "properties": [{"id": "unit", "value": "dateTimeFromNow"}, {"id": "custom.width", "value": 110}],
        },
        {"matcher": {"id": "byName", "options": "IP"}, "properties": [{"id": "custom.width", "value": 110}]},
        {
            "matcher": {"id": "byName", "options": "Nubes IoT"},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}},
            ],
        },
    ]
    p["options"] = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    return p


def count_stat(pid: int, title: str, expr: str, x: int, color: str = "text") -> Panel:
    return panel(
        pid,
        title,
        "stat",
        expr,
        x,
        1,
        6,
        3,
        legend="",
        instant=True,
        thresholds=[{"color": color, "value": None}],
        options={"graphMode": "none", "colorMode": "value", "text": {"titleSize": 12, "valueSize": 26}},
    )


Q24 = "netinv_device_dns_queries_24h"
PCT_DNS = f"100 * {Q24} / scalar(sum({Q24}))"


def summary_table(pid: int, y: int, h: int) -> Panel:
    """Lo de cada día: encendido, nombre, tipo, IP y hace cuánto se vio."""
    p = device_table(pid, "Dispositivos (vistos en 30 días)", "netinv_device_info", y, h)
    p["targets"].append(
        {
            "refId": "C",
            "datasource": DS,
            "expr": PCT_DNS,
            "format": "table",
            "instant": True,
            "range": False,
            "legendFormat": "",
        }
    )
    p["transformations"][0] = {"id": "merge", "options": {}}  # A, B y C unidos por mac (C puede faltar)
    p["transformations"][2] = {
        "id": "organize",
        "options": {
            "includeByName": {
                "encendido": True,
                "mostrar": True,
                "tipo": True,
                "ip": True,
                "Value #C": True,
                "Value #B": True,
            },
            "indexByName": {"encendido": 0, "mostrar": 1, "tipo": 2, "ip": 3, "Value #C": 4, "Value #B": 5},
            "renameByName": {
                "encendido": " ",
                "mostrar": "Nombre",
                "tipo": "Tipo",
                "ip": "IP",
                "Value #C": "% consultas DNS (24 h)",
                "Value #B": "Visto",
            },
        },
    }
    p["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": " "},
            "properties": [
                {"id": "custom.width", "value": 36},
                {
                    "id": "mappings",
                    "value": [
                        {
                            "type": "value",
                            "options": {
                                "●": {"color": "green", "index": 0},
                                "○": {"color": "text", "index": 1},
                            },
                        }
                    ],
                },
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
            ],
        },
        {
            "matcher": {"id": "byName", "options": "Visto"},
            "properties": [{"id": "unit", "value": "dateTimeFromNow"}, {"id": "custom.width", "value": 130}],
        },
        {"matcher": {"id": "byName", "options": "IP"}, "properties": [{"id": "custom.width", "value": 130}]},
        {
            "matcher": {"id": "byName", "options": "Tipo"},
            "properties": [{"id": "custom.width", "value": 120}],
        },
        {
            "matcher": {"id": "byName", "options": "% consultas DNS (24 h)"},
            "properties": [
                {"id": "unit", "value": "percent"},
                {"id": "decimals", "value": 1},
                {"id": "min", "value": 0},
                {"id": "max", "value": 100},
                {"id": "custom.width", "value": 230},
                {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}},
                {"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}},
            ],
        },
    ]
    return p


def iot_cloud_table(pid: int, y: int, h: int) -> Panel:
    """Aparatos que hablan con nubes de fabricantes IoT y cuántas consultas DNS han hecho en 24 h."""
    p = panel(
        pid,
        "Nubes IoT (aparatos que hablan con la nube de un fabricante)",
        "table",
        'netinv_device_info{nubes_iot!=""}',
        0,
        y,
        12,
        h,
        legend="",
        instant=True,
    )
    p["targets"] += [
        {
            "refId": r,
            "datasource": DS,
            "expr": e,
            "format": "table",
            "instant": True,
            "range": False,
            "legendFormat": "",
        }
        for r, e in (("B", Q24), ("C", PCT_DNS))
    ]
    p["transformations"] = [
        {"id": "merge", "options": {}},
        {
            "id": "filterByValue",
            "options": {
                "type": "include",
                "match": "any",
                "filters": [{"fieldName": "mostrar", "config": {"id": "regex", "options": {"value": ".+"}}}],
            },
        },
        {"id": "sortBy", "options": {"sort": [{"field": "Value #B", "desc": True}]}},
        {
            "id": "organize",
            "options": {
                "includeByName": {"mostrar": True, "nubes_iot": True, "Value #B": True, "Value #C": True},
                "indexByName": {"mostrar": 0, "nubes_iot": 1, "Value #B": 2, "Value #C": 3},
                "renameByName": {
                    "mostrar": "Dispositivo",
                    "nubes_iot": "Nubes",
                    "Value #B": "Consultas DNS 24 h",
                    "Value #C": "% del total",
                },
            },
        },
    ]
    p["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "% del total"},
            "properties": [{"id": "unit", "value": "percent"}, {"id": "decimals", "value": 1}],
        }
    ]
    p["fieldConfig"]["defaults"].update({"custom": {"align": "left"}, "noValue": "—", "decimals": 0})
    p["options"] = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    return p


def activity_timeline(pid: int, y: int, h: int, interval: int) -> Panel:
    """Activo/inactivo de cada dispositivo en el tiempo (todos los que ve netinv, servidores o no).

    Activo = visto (arp-scan o consulta a Pi-hole) en los dos últimos ciclos de netinv. Se ordena por nombre:
    Prometheus devuelve las series ordenadas por sus etiquetas, y `mostrar` va antes que `zmac` (desempate).
    """
    seen = f"(time() - netinv_device_last_seen_seconds < bool {2 * interval})"
    named = f"{seen} * on (mac) group_left (mostrar) max by (mac, mostrar) (netinv_device_info)"
    expr = f'max by (mostrar, zmac) (label_replace({named}, "zmac", "$1", "mac", "(.*)"))'
    return panel(
        pid,
        "Activo / inactivo",
        "state-timeline",
        expr,
        0,
        y,
        24,
        h,
        legend="{{mostrar}}",
        mappings=[
            {
                "type": "value",
                "options": {
                    "0": {"text": "inactivo", "color": "rgba(128, 128, 128, 0.25)"},
                    "1": {"text": "activo", "color": "green"},
                },
            }
        ],
        thresholds=[{"color": "rgba(128, 128, 128, 0.25)", "value": None}, {"color": "green", "value": 1}],
        options={
            "showValue": "never",
            "mergeValues": True,
            "rowHeight": 0.85,
            "legend": {"showLegend": False},
        },
    )


def devices(s: Site, m: Brand) -> dict[str, Any]:
    top_dns = panel(
        13,
        "Más consultas DNS en 24 h (% del total)",
        "bargauge",
        f"topk(15, {PCT_DNS} * on (mac) group_left (mostrar) max by (mac, mostrar) (netinv_device_info))",
        12,
        47,
        12,
        9,
        legend="{{mostrar}}",
        instant=True,
        options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": False},
        thresholds=[{"color": "blue", "value": None}],
    )
    top_dns["fieldConfig"]["defaults"].update({"decimals": 1, "unit": "percent"})
    details = row(20, "Detalle técnico (MAC, fabricante, nombres, nubes IoT, mDNS, UPnP, puertos, SO)", 66)
    details["collapsed"] = True
    details["panels"] = [device_table(21, "Detalle técnico", "netinv_device_info", 67, 18)]
    device_panels = [
        row(1, "Resumen", 0),
        count_stat(2, "Encendidos (24 h)", "count(netinv_device_info == 1) or vector(0)", 0),
        count_stat(
            3, "Sin clasificar", 'count(netinv_device_info{clasificado="no"} == 1) or vector(0)', 6, "orange"
        ),
        count_stat(
            4,
            "Nuevos en 24 h",
            "count(netinv_device_first_seen_seconds > time() - 86400) or vector(0)",
            12,
            "blue",
        ),
        count_stat(
            5, "Hablan con nubes IoT", 'count(netinv_device_info{nubes_iot!=""} == 1) or vector(0)', 18
        ),
        row(9, "Dispositivos", 4),
        summary_table(11, 5, 18),
        row(17, "Actividad (visto por netinv en los dos últimos ciclos)", 23),
        activity_timeline(18, 24, 22, s.modulos.netinv.intervalo),
        row(12, "Nubes IoT y actividad DNS (Pi-hole ve consultas, no bytes)", 46),
        iot_cloud_table(14, 47, 9),
        top_dns,
        row(15, "Sin clasificar (encendidos en 24 h)", 57),
        device_table(
            16,
            "Pendientes de clasificar (devices.yaml del sitio)",
            'netinv_device_info{clasificado="no"} == 1',
            58,
            8,
        ),
        details,
    ]
    return m.dash("dispositivos", "Dispositivos", device_panels, refresh="5m", time_from="now-24h")
