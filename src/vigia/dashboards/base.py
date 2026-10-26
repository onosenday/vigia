"""Piezas comunes de los paneles: paneles, filas, contadores y orden fijo de las series."""

from __future__ import annotations

from typing import Any

DS = {"type": "prometheus", "uid": "prometheus"}
UPDOWN = [
    {
        "type": "value",
        "options": {"0": {"text": "CAÍDO", "color": "red"}, "1": {"text": "OK", "color": "green"}},
    }
]
RED_GREEN = [{"color": "red", "value": None}, {"color": "green", "value": 1}]
PCT = [{"color": "green", "value": None}, {"color": "orange", "value": 75}, {"color": "red", "value": 90}]
TEMP = [{"color": "green", "value": None}, {"color": "orange", "value": 65}, {"color": "red", "value": 80}]

Panel = dict[str, Any]


def promql_escape(v: str) -> str:
    """Escapa un valor para ponerlo entre comillas dobles en PromQL."""
    return v.replace("\\", "\\\\").replace('"', '\\"')


def panel(
    pid: int,
    title: str,
    ptype: str,
    expr: str,
    x: int,
    y: int,
    w: int,
    h: int,
    legend: str = "{{nombre}}",
    unit: str | None = None,
    instant: bool = False,
    mappings: list[Any] | None = None,
    thresholds: list[Any] | None = None,
    options: dict[str, Any] | None = None,
    transform: list[Any] | None = None,
) -> Panel:
    p: Panel = {
        "id": pid,
        "title": title,
        "type": ptype,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {
                "refId": "A",
                "datasource": DS,
                "expr": expr,
                "legendFormat": legend,
                "instant": instant,
                "range": not instant,
                **({"format": "table"} if ptype == "table" else {}),
            }
        ],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": options or {},
    }
    d = p["fieldConfig"]["defaults"]
    if unit:
        d["unit"] = unit
    if mappings:
        d["mappings"] = mappings
    if thresholds:
        d["thresholds"] = {"mode": "absolute", "steps": thresholds}
        d["color"] = {"mode": "thresholds"}
    if transform:
        p["transformations"] = transform
    return p


def row(pid: int, title: str, y: int) -> Panel:
    return {
        "id": pid,
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


def order_series(
    panels: list[Panel],
    ids: set[int],
    job: str,
    label: str,
    items: list[tuple[str, str]],
    legend: str = "{}",
) -> None:
    """Sustituye la consulta de los paneles `ids` por una por elemento, en el orden de `items`.

    Prometheus devuelve las series en su orden (por IP): así se fija el orden del sitio.
    """
    for p in panels:
        if p["id"] not in ids:
            continue
        base = p["targets"][0]
        p["targets"] = [
            {
                **base,
                "refId": chr(65 + i),
                "legendFormat": legend.format(name),
                "expr": base["expr"].replace(f'job="{job}"', f'job="{job}",{label}="{promql_escape(val)}"'),
            }
            for i, (val, name) in enumerate(items)
        ]
        if p["type"] == "table":  # una tabla por consulta → se unen en orden
            p["transformations"] = [{"id": "merge", "options": {}}, *p.get("transformations", [])]


def dashboard(
    uid: str,
    title: str,
    tag: str,
    panels: list[Panel],
    refresh: str = "1m",
    time_from: str = "now-24h",
    links: list[Any] | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "uid": uid,
        "title": title,
        "tags": [tag],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": refresh,
        "editable": False,
        "time": {"from": time_from, "to": "now"},
        "panels": panels,
    }
    if links:
        d["links"] = links
    return d
