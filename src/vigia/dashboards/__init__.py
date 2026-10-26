"""Paneles de Grafana generados a partir del sitio.

Cada panel solo se genera si existe lo que mide (sin NAS no hay SNMP, sin Docker no hay Contenedores…),
y todos llevan el branding del sitio (prefijo de título, uid, tag).
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from vigia.dashboards import dispositivos, extra
from vigia.dashboards.base import (
    DS,
    PCT,
    RED_GREEN,
    TEMP,
    UPDOWN,
    Panel,
    dashboard,
    ordenar,
    panel,
    promql_str,
    row,
)
from vigia.model import Site


class Marca:
    """Aplica el branding del sitio a títulos, uid y tags."""

    def __init__(self, s: Site) -> None:
        self.s = s
        b = s.branding
        self.prefijo, self.tag, self.uid_prefijo = b.prefijo_titulo, b.tag, b.uid_prefijo
        self.portada = b.portada

    def uid(self, slug: str) -> str:
        return f"{self.uid_prefijo}-{slug}"

    def titulo(self, t: str) -> str:
        return self.prefijo + t

    def links(self) -> list[Any] | None:
        if not self.portada:
            return None
        return [
            {
                "title": f"Inicio · {self.s.branding.nombre}",
                "type": "link",
                "icon": "dashboard",
                "url": f"/d/{self.uid('inicio')}",
                "targetBlank": False,
            }
        ]

    def dash(self, slug: str, title: str, panels: list[Panel], **kw: Any) -> dict[str, Any]:
        return dashboard(self.uid(slug), self.titulo(title), self.tag, panels, links=self.links(), **kw)


def _json(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)


# --- Red y servicios (blackbox) ---------------------------------------------------------------------


def contador(pid: int, title: str, job: str, x: int, y: int, color: str = "red") -> Panel:
    """Número de elementos caídos de un tipo, en pequeño (el detalle está en «Qué falla ahora»)."""
    return panel(
        pid,
        title,
        "stat",
        f'count(probe_success{{job="{job}"}} == 0) or vector(0)',
        x,
        y,
        4,
        3,
        legend="",
        instant=True,
        thresholds=[{"color": "green", "value": None}, {"color": color, "value": 1}],
        options={
            "textMode": "value",
            "colorMode": "value",
            "graphMode": "none",
            "text": {"titleSize": 12, "valueSize": 26},
        },
    )


def falla_ahora(pid: int, x: int, y: int, w: int, h: int) -> Panel:
    """Tabla con una fila por web, servicio o equipo caído (tipo, nombre, host)."""
    p = panel(
        pid,
        "Qué falla ahora",
        "table",
        'probe_success{job=~"web|servicio|ping"} == 0',
        x,
        y,
        w,
        h,
        legend="",
        instant=True,
        transform=[
            {
                "id": "organize",
                "options": {
                    "includeByName": {"job": True, "nombre": True, "host": True},
                    "indexByName": {"job": 0, "nombre": 1, "host": 2},
                    "renameByName": {"job": "Tipo", "nombre": "Nombre", "host": "Host"},
                },
            }
        ],
        options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
    )
    d = p["fieldConfig"]["defaults"]
    d["noValue"] = "Todo funciona"
    d["mappings"] = [
        {
            "type": "value",
            "options": {
                "web": {"text": "Web"},
                "servicio": {"text": "Servicio"},
                "ping": {"text": "Equipo (ping)"},
            },
        }
    ]
    d["custom"] = {"align": "left"}
    p["fieldConfig"]["overrides"] = [
        {"matcher": {"id": "byName", "options": "Tipo"}, "properties": [{"id": "custom.width", "value": 140}]}
    ]
    return p


def nombre_ip(s: Site, ip: str) -> str:
    for v in s.vips:
        if v.ip == ip:
            return v.nombre
    for h in s.hosts:
        if ip in h.ips:
            return h.visible
    return ip


def red_servicios(s: Site, m: Marca) -> dict[str, Any] | None:
    hay_web, hay_srv, hay_ping, hay_dns = bool(s.web.objetivos), bool(s.servicios), bool(s.ping), bool(s.dns)
    if not s.modulos.blackbox or not (hay_web or hay_srv or hay_ping or hay_dns):
        return None
    st = {"showValue": "never", "mergeValues": True, "rowHeight": 0.8}
    panels: list[Panel] = [
        row(1, "Resumen", 0),
        contador(2, "Webs caídas", "web", 0, 1),
        contador(3, "Servicios caídos", "servicio", 4, 1),
        contador(4, "Equipos sin ping", "ping", 0, 4, color="orange"),
        panel(
            5,
            "Certificado caduca en",
            "stat",
            'min((probe_ssl_earliest_cert_expiry{job="web"} - time()) / 86400)',
            4,
            4,
            4,
            3,
            legend="",
            instant=True,
            unit="d",
            thresholds=[
                {"color": "red", "value": None},
                {"color": "orange", "value": 15},
                {"color": "green", "value": 30},
            ],
            options={"graphMode": "none", "text": {"titleSize": 12, "valueSize": 26}},
        ),
        falla_ahora(6, 8, 1, 16, 6),
        row(10, f"Webs *.{s.red.dominio} (vía proxy inverso)", 5),
        panel(
            11,
            "Estado",
            "state-timeline",
            'probe_success{job="web"}',
            0,
            6,
            16,
            10,
            mappings=UPDOWN,
            thresholds=RED_GREEN,
            options=st,
        ),
        panel(
            12,
            "Tiempo de respuesta",
            "timeseries",
            'probe_duration_seconds{job="web"}',
            16,
            6,
            8,
            10,
            unit="s",
        ),
        row(20, "Servicios por IP:puerto", 16),
        panel(
            21,
            "Estado",
            "state-timeline",
            'probe_success{job="servicio"}',
            0,
            17,
            16,
            14,
            legend="{{nombre}} ({{host}})",
            mappings=UPDOWN,
            thresholds=RED_GREEN,
            options=st,
        ),
        panel(
            22,
            "Más lentos ahora",
            "bargauge",
            'topk(10, probe_duration_seconds{job="servicio"})',
            16,
            17,
            8,
            14,
            legend="{{nombre}}",
            unit="s",
            instant=True,
            options={"orientation": "horizontal", "displayMode": "basic"},
            thresholds=[
                {"color": "green", "value": None},
                {"color": "orange", "value": 1},
                {"color": "red", "value": 3},
            ],
        ),
        row(30, "Red", 31),
        panel(
            31,
            "Equipos (ping)",
            "state-timeline",
            'probe_success{job="ping"}',
            0,
            32,
            12,
            9,
            mappings=UPDOWN,
            thresholds=RED_GREEN,
            options=st,
        ),
        panel(
            32,
            "Latencia de ping",
            "timeseries",
            'probe_icmp_duration_seconds{job="ping",phase="rtt"}',
            12,
            32,
            12,
            9,
            unit="s",
        ),
    ]
    if s.dns:
        panels += [
            panel(
                33,
                f"DNS: resuelve {s.dns.consulta} → {nombre_ip(s, s.dns.espera)}",
                "state-timeline",
                'probe_success{job="dns"}',
                0,
                41,
                12,
                5,
                legend="{{instance}}",
                mappings=UPDOWN,
                thresholds=RED_GREEN,
                options=st,
            ),
            panel(
                34,
                "DNS: tiempo de consulta",
                "timeseries",
                'probe_dns_lookup_time_seconds{job="dns"}',
                12,
                41,
                12,
                5,
                legend="{{instance}}",
                unit="s",
            ),
        ]
    fuera = set()
    if not hay_web:
        fuera |= {2, 5, 10, 11, 12}
    if not hay_srv:
        fuera |= {3, 20, 21, 22}
    if not hay_ping:
        fuera |= {4, 31, 32}
    if not hay_ping and not hay_dns:
        fuera.add(30)
    panels = [p for p in panels if p["id"] not in fuera]
    for p in panels:  # el resumen ocupa 7 filas de rejilla: lo demás baja 2
        if p["id"] >= 10:
            p["gridPos"]["y"] += 2

    ordenar(panels, {31, 32}, "ping", "nombre", [(n, n) for _, n, _ in s.ping_resuelto()])
    if s.dns:
        ordenar(panels, {33, 34}, "dns", "instance", servidores_dns(s))
    return m.dash("red", "Red y servicios", panels)


def servidores_dns(s: Site) -> list[tuple[str, str]]:
    """Servidores DNS en orden: VIPs primero y luego los hosts en el orden del sitio."""
    assert s.dns
    orden = [v.ip for v in s.vips] + [ip for h in s.hosts for ip in h.ips]
    ips = sorted(s.dns.servidores, key=lambda ip: orden.index(ip) if ip in orden else len(orden))
    return [(ip, nombre_ip(s, ip)) for ip in ips]


# --- Servidores (node_exporter) ---------------------------------------------------------------------

FS = 'fstype!~"tmpfs|overlay|squashfs|ramfs|devtmpfs|fuse.*|nfs.*|cifs"'
RED_IGNORA = 'device!~"lo|veth.*|docker.*|br-.*|cni.*|flannel.*"'


def servidores_node(s: Site) -> list[tuple[str, str]]:
    return [(h.visible, h.visible) for h in s.hosts if h.node_exporter]


def servidores(s: Site, m: Marca) -> dict[str, Any] | None:
    items = servidores_node(s)
    if not items:
        return None
    hz = {"orientation": "horizontal", "displayMode": "gradient", "min": 0, "max": 100}
    cpu = '100 * (1 - avg by (nombre) (rate(node_cpu_seconds_total{job="node",mode="idle"}[5m])))'
    ram = '100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})'
    temp = (
        'max by (nombre) (node_hwmon_temp_celsius{job="node"}) or '
        'max by (nombre) (node_thermal_zone_temp{job="node"})'
    )
    panels = [
        row(1, "Ahora", 0),
        panel(
            2, "CPU", "bargauge", cpu, 0, 1, 6, 6, unit="percent", instant=True, thresholds=PCT, options=hz
        ),
        panel(
            3, "RAM", "bargauge", ram, 6, 1, 6, 6, unit="percent", instant=True, thresholds=PCT, options=hz
        ),
        panel(
            4,
            "Disco más lleno",
            "bargauge",
            f'max by (nombre) (100 * (1 - node_filesystem_avail_bytes{{job="node",{FS}}} / '
            f'node_filesystem_size_bytes{{job="node",{FS}}}))',
            12,
            1,
            6,
            6,
            unit="percent",
            instant=True,
            thresholds=PCT,
            options=hz,
        ),
        panel(
            5,
            "Temperatura máxima",
            "bargauge",
            temp,
            18,
            1,
            6,
            6,
            unit="celsius",
            instant=True,
            thresholds=TEMP,
            options={**hz, "min": 20},
        ),
        panel(
            6,
            "Encendido desde hace",
            "stat",
            'time() - node_boot_time_seconds{job="node"}',
            0,
            7,
            12,
            3,
            unit="s",
            instant=True,
            options={"colorMode": "none", "textMode": "value_and_name"},
        ),
        panel(
            7,
            "Carga (1 min) por núcleo",
            "stat",
            'node_load1{job="node"} / on (nombre) count by (nombre) '
            '(node_cpu_seconds_total{job="node",mode="idle"})',
            12,
            7,
            12,
            3,
            unit="percentunit",
            instant=True,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "orange", "value": 0.8},
                {"color": "red", "value": 1.5},
            ],
            options={"textMode": "value_and_name"},
        ),
        row(10, "Histórico", 10),
        panel(11, "CPU", "timeseries", cpu, 0, 11, 12, 8, unit="percent"),
        panel(12, "RAM usada", "timeseries", ram, 12, 11, 12, 8, unit="percent"),
        panel(
            13,
            "Red recibida",
            "timeseries",
            f'sum by (nombre) (rate(node_network_receive_bytes_total{{job="node",{RED_IGNORA}}}[5m]))',
            0,
            19,
            12,
            8,
            unit="Bps",
        ),
        panel(
            14,
            "Red enviada",
            "timeseries",
            f'sum by (nombre) (rate(node_network_transmit_bytes_total{{job="node",{RED_IGNORA}}}[5m]))',
            12,
            19,
            12,
            8,
            unit="Bps",
        ),
        panel(15, "Temperatura", "timeseries", temp, 0, 27, 12, 8, unit="celsius"),
        panel(
            16,
            "Espacio libre por disco",
            "table",
            f'node_filesystem_avail_bytes{{job="node",{FS}}}',
            12,
            27,
            12,
            8,
            legend="",
            unit="bytes",
            instant=True,
            transform=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "instance": True,
                            "device": True,
                        },
                        "renameByName": {
                            "nombre": "Servidor",
                            "mountpoint": "Montaje",
                            "fstype": "Tipo",
                            "Value": "Libre",
                        },
                    },
                }
            ],
        ),
    ]
    ordenar(panels, {2, 3, 4, 5, 6, 7, 11, 12, 13, 14, 15, 16}, "node", "nombre", items)
    return m.dash("servidores", "Servidores", panels)


def gauge(
    pid: int,
    title: str,
    expr: str,
    x: int,
    y: int,
    unit: str = "percent",
    mn: int = 0,
    mx: int = 100,
    steps: list[Any] = PCT,
    w: int = 3,
) -> Panel:
    p = panel(
        pid,
        title,
        "gauge",
        expr,
        x,
        y,
        w,
        5,
        legend="",
        unit=unit,
        instant=True,
        thresholds=steps,
        options={"showThresholdMarkers": True, "showThresholdLabels": False},
    )
    p["fieldConfig"]["defaults"].update({"min": mn, "max": mx, "decimals": 0, "noValue": "—"})
    return p


def vista_rapida(s: Site, m: Marca) -> dict[str, Any] | None:
    """Los gauges de Node Exporter Full para todos los servidores a la vez."""
    items = servidores_node(s)
    if not items:
        return None
    quick: list[Panel] = []
    pid = 100
    for i, (h, _) in enumerate(items):
        y = i * 6
        n = f'job="node",nombre="{promql_str(h)}"'
        fs = f"{n},{FS}"
        quick.append(row(pid, h, y))
        pid += 1
        quick += [
            gauge(
                pid, "CPU", f'100 * (1 - avg(rate(node_cpu_seconds_total{{{n},mode="idle"}}[5m])))', 0, y + 1
            ),
            gauge(
                pid + 1,
                "Carga (1 min)",
                f'100 * node_load1{{{n}}} / scalar(count(node_cpu_seconds_total{{{n},mode="idle"}}))',
                3,
                y + 1,
                mx=200,
            ),
            gauge(
                pid + 2,
                "RAM",
                f"100 * (1 - node_memory_MemAvailable_bytes{{{n}}} / node_memory_MemTotal_bytes{{{n}}})",
                6,
                y + 1,
            ),
            gauge(
                pid + 3,
                "Swap",
                f"100 * (1 - node_memory_SwapFree_bytes{{{n}}} / node_memory_SwapTotal_bytes{{{n}}})",
                9,
                y + 1,
            ),
            gauge(
                pid + 4,
                "Disco sistema (/)",
                f'100 * (1 - node_filesystem_avail_bytes{{{fs},mountpoint="/"}} / '
                f'node_filesystem_size_bytes{{{fs},mountpoint="/"}})',
                12,
                y + 1,
            ),
            gauge(
                pid + 5,
                "Disco de datos",
                f'max(100 * (1 - node_filesystem_avail_bytes{{{fs},mountpoint!~"/|/boot.*"}} / '
                f'node_filesystem_size_bytes{{{fs},mountpoint!~"/|/boot.*"}}))',
                15,
                y + 1,
            ),
            gauge(
                pid + 6,
                "Temperatura",
                f"max(node_hwmon_temp_celsius{{{n}}}) or max(node_thermal_zone_temp{{{n}}})",
                18,
                y + 1,
                unit="celsius",
                mn=20,
                mx=100,
                steps=TEMP,
            ),
        ]
        info = panel(
            pid + 7,
            "",
            "stat",
            f'count(node_cpu_seconds_total{{{n},mode="idle"}})',
            21,
            y + 1,
            3,
            5,
            legend="núcleos",
            instant=True,
            options={"textMode": "value_and_name", "colorMode": "none", "orientation": "horizontal"},
        )
        info["targets"] += [
            {
                "refId": "B",
                "datasource": DS,
                "expr": f"node_memory_MemTotal_bytes{{{n}}}",
                "legendFormat": "RAM",
                "instant": True,
                "range": False,
            },
            {
                "refId": "C",
                "datasource": DS,
                "expr": f"time() - node_boot_time_seconds{{{n}}}",
                "legendFormat": "encendido",
                "instant": True,
                "range": False,
            },
        ]
        info["fieldConfig"]["overrides"] = [
            {
                "matcher": {"id": "byFrameRefID", "options": "B"},
                "properties": [{"id": "unit", "value": "bytes"}],
            },
            {"matcher": {"id": "byFrameRefID", "options": "C"}, "properties": [{"id": "unit", "value": "s"}]},
        ]
        quick.append(info)
        pid += 10
    return m.dash("vista-rapida", "Vista rápida de servidores", quick, refresh="30s", desde="now-1h")


# --- Contenedores (cAdvisor) ------------------------------------------------------------------------


def contenedores(s: Site, m: Marca) -> dict[str, Any] | None:
    docker = [(h.visible, h.visible) for h in s.hosts if h.cadvisor]
    if not docker:
        return None
    c = 'job="cadvisor",name!=""'
    lg = "{{name}} ({{nombre}})"
    hz = {"orientation": "horizontal", "displayMode": "gradient"}
    ctr = [
        row(1, "Ahora", 0),
        panel(
            2,
            "Contenedores en marcha",
            "stat",
            f"count by (nombre) (container_last_seen{{{c}}})",
            0,
            1,
            6,
            5,
            legend="{{nombre}}",
            instant=True,
            options={"textMode": "value_and_name", "colorMode": "none"},
        ),
        panel(
            3,
            "Más RAM",
            "bargauge",
            f"topk(12, container_memory_working_set_bytes{{{c}}})",
            6,
            1,
            9,
            10,
            legend=lg,
            unit="bytes",
            instant=True,
            options=hz,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "orange", "value": 1e9},
                {"color": "red", "value": 3e9},
            ],
        ),
        panel(
            4,
            "Más CPU (núcleos)",
            "bargauge",
            f"topk(12, rate(container_cpu_usage_seconds_total{{{c}}}[5m]))",
            15,
            1,
            9,
            10,
            legend=lg,
            unit="none",
            instant=True,
            options=hz,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "orange", "value": 0.5},
                {"color": "red", "value": 1.5},
            ],
        ),
        panel(
            5,
            "Arrancados hace menos de 1 h",
            "table",
            f"(time() - container_start_time_seconds{{{c}}}) < 3600",
            0,
            6,
            6,
            5,
            legend="",
            unit="s",
            instant=True,
            transform=[
                {
                    "id": "organize",
                    "options": {
                        "includeByName": {"name": True, "nombre": True, "Value": True},
                        "renameByName": {"name": "Contenedor", "nombre": "Host", "Value": "Hace"},
                    },
                }
            ],
        ),
        row(10, "Histórico", 11),
        panel(
            11,
            "RAM (top 10)",
            "timeseries",
            f"topk(10, container_memory_working_set_bytes{{{c}}})",
            0,
            12,
            12,
            9,
            legend=lg,
            unit="bytes",
        ),
        panel(
            12,
            "CPU (top 10, núcleos)",
            "timeseries",
            f"topk(10, rate(container_cpu_usage_seconds_total{{{c}}}[5m]))",
            12,
            12,
            12,
            9,
            legend=lg,
            unit="none",
        ),
        panel(
            13,
            "Red recibida (top 10)",
            "timeseries",
            f"topk(10, sum by (name, nombre) (rate(container_network_receive_bytes_total{{{c}}}[5m])))",
            0,
            21,
            12,
            9,
            legend=lg,
            unit="Bps",
        ),
        panel(
            14,
            "Red enviada (top 10)",
            "timeseries",
            f"topk(10, sum by (name, nombre) (rate(container_network_transmit_bytes_total{{{c}}}[5m])))",
            12,
            21,
            12,
            9,
            legend=lg,
            unit="Bps",
        ),
    ]
    ordenar(ctr, {2}, "cadvisor", "nombre", docker)
    return m.dash("contenedores", "Contenedores", ctr)


# --- Pi-hole ----------------------------------------------------------------------------------------


def pihole(s: Site, m: Marca) -> dict[str, Any] | None:
    if not s.modulos.pihole_exporter.activo or not s.piholes:
        return None
    piholes = [(urlsplit(h.pihole.url).hostname or "", h.visible) for h in s.piholes if h.pihole]
    primaria = next(
        (urlsplit(h.pihole.url).hostname for h in s.piholes if h.pihole and h.pihole.primaria), piholes[0][0]
    )
    ph = 'job="pihole"'
    php = f'{ph},hostname="{promql_str(primaria or "")}"'
    hl = "{{hostname}}"
    stat = {"textMode": "value_and_name", "colorMode": "none"}
    panels = [
        row(1, "Hoy", 0),
        panel(
            2,
            "Estado (1 = activo)",
            "stat",
            f"pihole_status{{{ph}}}",
            0,
            1,
            4,
            4,
            legend=hl,
            instant=True,
            mappings=[
                {
                    "type": "value",
                    "options": {
                        "0": {"text": "PARADO", "color": "red"},
                        "1": {"text": "ACTIVO", "color": "green"},
                    },
                }
            ],
            options={"textMode": "value_and_name"},
        ),
        panel(
            3,
            "Consultas hoy",
            "stat",
            f"pihole_dns_queries_today{{{ph}}}",
            4,
            1,
            5,
            4,
            legend=hl,
            instant=True,
            options=stat,
        ),
        panel(
            4,
            "Bloqueadas hoy",
            "stat",
            f"pihole_ads_blocked_today{{{ph}}}",
            9,
            1,
            5,
            4,
            legend=hl,
            instant=True,
            options=stat,
        ),
        panel(
            5,
            "% bloqueado",
            "stat",
            f"pihole_ads_percentage_today{{{ph}}}",
            14,
            1,
            4,
            4,
            legend=hl,
            unit="percent",
            instant=True,
            options=stat,
        ),
        panel(
            6,
            "Clientes",
            "stat",
            f"pihole_unique_clients{{{ph}}}",
            18,
            1,
            3,
            4,
            legend=hl,
            instant=True,
            options=stat,
        ),
        panel(
            7,
            "Dominios en listas",
            "stat",
            f"pihole_domains_being_blocked{{{ph}}}",
            21,
            1,
            3,
            4,
            legend=hl,
            instant=True,
            options=stat,
        ),
        row(10, "Histórico", 5),
        panel(
            11,
            "Consultas por segundo",
            "timeseries",
            f"pihole_request_rate{{{ph}}}",
            0,
            6,
            12,
            8,
            legend=hl,
            unit="reqps",
        ),
        panel(
            12,
            "% bloqueado",
            "timeseries",
            f"pihole_ads_percentage_today{{{ph}}}",
            12,
            6,
            12,
            8,
            legend=hl,
            unit="percent",
        ),
        panel(
            13,
            "Tiempo de respuesta de los DNS de salida",
            "timeseries",
            f"pihole_forward_destinations_responsetime{{{ph}}}",
            0,
            14,
            12,
            8,
            legend="{{destination}} ({{hostname}})",
            unit="ms",
        ),
        panel(
            14,
            "Respuestas por tipo (primaria)",
            "piechart",
            f"pihole_reply{{{php}}} > 0",
            12,
            14,
            12,
            8,
            legend="{{type}}",
            instant=True,
            options={"legend": {"displayMode": "table", "placement": "right", "values": ["value"]}},
        ),
        row(20, "Bloqueos", 22),
        panel(
            21,
            "Dominios más bloqueados (primaria)",
            "bargauge",
            f"topk(15, pihole_top_ads{{{php}}})",
            0,
            23,
            24,
            10,
            legend="{{domain}}",
            instant=True,
            options={"orientation": "horizontal", "displayMode": "basic"},
        ),
    ]
    ordenar(panels, {2, 3, 4, 5, 6, 7, 11, 12}, "pihole", "hostname", piholes)
    ordenar(panels, {13}, "pihole", "hostname", piholes, legend="{{{{destination}}}} ({})")
    return m.dash("pihole", "Pi-hole", panels)


# --- conjunto ---------------------------------------------------------------------------------------


def node_exporter_full(s: Site, m: Marca) -> dict[str, Any] | None:
    """Panel de terceros (ver externos/NOTICE.md): conserva su uid y solo lleva el prefijo de título."""
    if not servidores_node(s):
        return None
    texto = files("vigia").joinpath("dashboards", "externos", "node-exporter-full.json").read_text("utf-8")
    d: dict[str, Any] = json.loads(texto)
    d["title"] = m.titulo(d["title"])
    return d


def paneles(s: Site, raiz_sitio: Path) -> dict[str, str]:
    """{nombre de fichero: JSON} de los paneles del sitio."""
    m = Marca(s)
    gen = {
        "red-y-servicios.json": red_servicios(s, m),
        "servidores.json": servidores(s, m),
        "vista-rapida.json": vista_rapida(s, m),
        "contenedores.json": contenedores(s, m),
        "pihole.json": pihole(s, m),
        "dispositivos.json": dispositivos.dispositivos(s, m) if s.modulos.netinv.activo else None,
        "equipos-snmp.json": extra.snmp(s, m),
        "windows.json": extra.windows(s, m),
        "node-exporter-full.json": node_exporter_full(s, m),
    }
    out = {k: _json(v) for k, v in gen.items() if v is not None}
    if s.branding.portada:
        out["inicio.json"] = _json(extra.inicio(s, m))
    return out
