"""Paneles que dependen del tipo de equipo (SNMP, Windows) y la portada con la marca del sitio."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia.dashboards.base import PCT, RED_GREEN, TEMP, UPDOWN, Panel, ordenar, panel, row
from vigia.model import Site, Tipo

if TYPE_CHECKING:
    from vigia.dashboards import Marca

HZ = {"orientation": "horizontal", "displayMode": "gradient"}
ST = {"showValue": "never", "mergeValues": True, "rowHeight": 0.8}


def _snmp(s: Site, *tipos: Tipo) -> list[tuple[str, str]]:
    return [(h.visible, h.visible) for h in s.hosts if h.snmp and h.tipo in tipos]


def snmp(s: Site, m: Marca) -> dict[str, Any] | None:
    """NAS, switches, impresoras y SAI medidos por SNMP: una sección por tipo presente."""
    if not (s.modulos.snmp.activo and any(h.snmp for h in s.hosts)):
        return None
    todos = [(h.visible, h.visible) for h in s.hosts if h.snmp]
    panels: list[Panel] = [
        row(1, "Alcance", 0),
        panel(
            2,
            "Responde a SNMP",
            "state-timeline",
            'up{job="snmp"}',
            0,
            1,
            24,
            2 + len(todos),
            mappings=UPDOWN,
            thresholds=RED_GREEN,
            options=ST,
        ),
    ]
    ordenar(panels, {2}, "snmp", "nombre", todos)
    y = 3 + len(todos)
    nas = _snmp(s, Tipo.synology)
    if nas:
        sj = 'job="snmp",tipo="synology"'
        estado = [
            {
                "type": "value",
                "options": {
                    "1": {"text": "Normal", "color": "green"},
                    "2": {"text": "FALLO", "color": "red"},
                },
            }
        ]
        sec = [
            row(10, "NAS Synology", y),
            panel(
                11,
                "Sistema",
                "stat",
                f"systemStatus{{{sj}}}",
                0,
                y + 1,
                6,
                4,
                instant=True,
                mappings=estado,
                options={"textMode": "value_and_name"},
            ),
            panel(
                12,
                "Temperatura",
                "bargauge",
                f"temperature{{{sj}}}",
                6,
                y + 1,
                6,
                4,
                unit="celsius",
                instant=True,
                thresholds=TEMP,
                options={**HZ, "min": 20, "max": 90},
            ),
            panel(
                13,
                "Volúmenes / RAID ocupados",
                "bargauge",
                f"100 * (1 - raidFreeSize{{{sj}}} / raidTotalSize{{{sj}}})",
                12,
                y + 1,
                12,
                4,
                legend="{{raidName}} ({{nombre}})",
                unit="percent",
                instant=True,
                thresholds=PCT,
                options={**HZ, "min": 0, "max": 100},
            ),
            panel(
                14,
                "Estado de los RAID (1 = normal)",
                "stat",
                f"raidStatus{{{sj}}}",
                0,
                y + 5,
                12,
                4,
                legend="{{raidName}} ({{nombre}})",
                instant=True,
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "green", "value": 1},
                    {"color": "orange", "value": 2},
                ],
                options={"textMode": "value_and_name"},
            ),
            panel(
                15,
                "Temperatura de los discos",
                "bargauge",
                f"diskTemperature{{{sj}}}",
                12,
                y + 5,
                12,
                4,
                legend="{{diskID}} ({{nombre}})",
                unit="celsius",
                instant=True,
                thresholds=[
                    {"color": "green", "value": None},
                    {"color": "orange", "value": 50},
                    {"color": "red", "value": 60},
                ],
                options={**HZ, "min": 20, "max": 70},
            ),
        ]
        ordenar(sec, {11, 12}, "snmp", "nombre", nas)
        panels += sec
        y += 9
    red = _snmp(s, Tipo.switch, Tipo.qnap)
    if red:
        ij = 'job="snmp"'
        sec = [
            row(20, "Interfaces (switches y otros equipos SNMP)", y),
            panel(
                21,
                "Tráfico recibido",
                "timeseries",
                f"8 * rate(ifHCInOctets{{{ij}}}[5m]) > 0",
                0,
                y + 1,
                12,
                8,
                legend="{{ifName}} ({{nombre}})",
                unit="bps",
            ),
            panel(
                22,
                "Tráfico enviado",
                "timeseries",
                f"8 * rate(ifHCOutOctets{{{ij}}}[5m]) > 0",
                12,
                y + 1,
                12,
                8,
                legend="{{ifName}} ({{nombre}})",
                unit="bps",
            ),
        ]
        panels += sec
        y += 9
    imp = _snmp(s, Tipo.impresora)
    if imp:
        pj = 'job="snmp",tipo="impresora"'
        panels += [
            row(30, "Impresoras", y),
            panel(
                31,
                "Consumibles",
                "bargauge",
                f"100 * prtMarkerSuppliesLevel{{{pj}}} / prtMarkerSuppliesMaxCapacity{{{pj}}} >= 0",
                0,
                y + 1,
                24,
                8,
                legend="{{prtMarkerSuppliesDescription}} ({{nombre}})",
                unit="percent",
                instant=True,
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 10},
                    {"color": "green", "value": 25},
                ],
                options={**HZ, "min": 0, "max": 100},
            ),
        ]
        y += 9
    sai = _snmp(s, Tipo.sai)
    if sai:
        uj = 'job="snmp",tipo="sai"'
        panels += [
            row(40, "SAI", y),
            panel(
                41,
                "Carga de la batería",
                "bargauge",
                f"upsEstimatedChargeRemaining{{{uj}}}",
                0,
                y + 1,
                8,
                5,
                unit="percent",
                instant=True,
                thresholds=[
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 40},
                    {"color": "green", "value": 80},
                ],
                options={**HZ, "min": 0, "max": 100},
            ),
            panel(
                42,
                "Autonomía",
                "stat",
                f"upsEstimatedMinutesRemaining{{{uj}}}",
                8,
                y + 1,
                8,
                5,
                unit="m",
                instant=True,
                options={"textMode": "value_and_name"},
            ),
            panel(
                43,
                "Carga de salida",
                "bargauge",
                f"upsOutputPercentLoad{{{uj}}}",
                16,
                y + 1,
                8,
                5,
                unit="percent",
                instant=True,
                thresholds=PCT,
                options={**HZ, "min": 0, "max": 100},
            ),
        ]
    return m.dash("equipos-snmp", "Equipos SNMP", panels)


def windows(s: Site, m: Marca) -> dict[str, Any] | None:
    items = [(h.visible, h.visible) for h in s.hosts if h.windows_exporter]
    if not items:
        return None
    wj = 'job="windows"'
    hz = {**HZ, "min": 0, "max": 100}
    panels = [
        row(1, "Ahora", 0),
        panel(
            2,
            "CPU",
            "bargauge",
            f'100 * (1 - avg by (nombre) (rate(windows_cpu_time_total{{{wj},mode="idle"}}[5m])))',
            0,
            1,
            8,
            6,
            unit="percent",
            instant=True,
            thresholds=PCT,
            options=hz,
        ),
        panel(
            3,
            "RAM",
            "bargauge",
            f"100 * (1 - windows_memory_available_bytes{{{wj}}} / "
            f"windows_memory_physical_total_bytes{{{wj}}})",
            8,
            1,
            8,
            6,
            unit="percent",
            instant=True,
            thresholds=PCT,
            options=hz,
        ),
        panel(
            4,
            "Disco más lleno",
            "bargauge",
            f"max by (nombre) (100 * (1 - windows_logical_disk_free_bytes{{{wj}}} / "
            f"windows_logical_disk_size_bytes{{{wj}}}))",
            16,
            1,
            8,
            6,
            unit="percent",
            instant=True,
            thresholds=PCT,
            options=hz,
        ),
        row(10, "Histórico", 7),
        panel(
            11,
            "CPU",
            "timeseries",
            f'100 * (1 - avg by (nombre) (rate(windows_cpu_time_total{{{wj},mode="idle"}}[5m])))',
            0,
            8,
            12,
            8,
            unit="percent",
        ),
        panel(
            12,
            "Espacio libre por disco",
            "table",
            f"windows_logical_disk_free_bytes{{{wj}}}",
            12,
            8,
            12,
            8,
            legend="",
            unit="bytes",
            instant=True,
            transform=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {"Time": True, "__name__": True, "job": True, "instance": True},
                        "renameByName": {"nombre": "Equipo", "volume": "Unidad", "Value": "Libre"},
                    },
                }
            ],
        ),
    ]
    ordenar(panels, {2, 3, 4, 11, 12}, "windows", "nombre", items)
    return m.dash("windows", "Equipos Windows", panels)


def inicio(s: Site, m: Marca) -> dict[str, Any]:
    """Portada con la marca del sitio: logo, nombre, lo que falla y enlaces a los paneles."""
    b = s.branding
    logo = "![logo](public/img/grafana_icon.svg)\n\n" if (b.grafana and b.logo) else ""
    texto = (
        f"{logo}# {b.nombre}\n\n**{s.sitio.nombre}** · red `{s.red.subred}` · dominio `{s.red.dominio}`\n\n"
        f"Paneles en la carpeta **{b.carpeta}**."
    )
    cabecera = panel(1, "", "text", "", 0, 0, 8, 7, legend="", options={"mode": "markdown", "content": texto})
    del cabecera["targets"]
    color = {"color": {"mode": "fixed", "fixedColor": b.colores.primario}}
    panels: list[Panel] = [cabecera]
    if s.modulos.blackbox:
        caidos = panel(
            2,
            "Elementos caídos ahora",
            "stat",
            'count(probe_success{job=~"web|servicio|ping"} == 0) or vector(0)',
            8,
            0,
            8,
            7,
            legend="",
            instant=True,
            thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
            options={"textMode": "value", "colorMode": "background", "graphMode": "none"},
        )
        panels.append(caidos)
    servidores = [h for h in s.hosts if h.node_exporter or h.windows_exporter or h.snmp]
    if servidores:
        vivos = panel(
            3,
            "Equipos que reportan métricas",
            "stat",
            'count(up{job=~"node|windows|snmp"} == 1) or vector(0)',
            16,
            0,
            8,
            7,
            legend="",
            instant=True,
            options={"textMode": "value", "colorMode": "value", "graphMode": "none"},
        )
        vivos["fieldConfig"]["defaults"].update(color)
        panels.append(vivos)
    lista = panel(
        4,
        "Paneles",
        "dashlist",
        "",
        0,
        7,
        24,
        10,
        legend="",
        options={
            "showStarred": False,
            "showRecentlyViewed": False,
            "showSearch": True,
            "showHeadings": False,
            "tags": [b.tag],
            "maxItems": 30,
            "query": "",
        },
    )
    del lista["targets"]
    panels.append(lista)
    d = m.dash("inicio", "", panels, refresh="1m", desde="now-1h")
    d["title"] = f"{b.nombre} · Inicio"
    d.pop("links", None)
    return d
