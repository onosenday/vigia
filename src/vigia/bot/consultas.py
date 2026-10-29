"""PromQL fijas del bot y lectura de los dispositivos de netinv.

Nada de lo que escribe el usuario entra en una consulta: se pide todo el sitio y se filtra en Python.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fuentes import FuenteError, Prometheus

FS_EXCLUDED = "tmpfs|ramfs|overlay|squashfs|nsfs|devtmpfs|fuse.+"
"""Igual que `vigia.alerting.FS_EXCLUDED`: en su contenedor el bot no tiene vigia (un test lo vigila)."""
_FS = f'fstype!~"{FS_EXCLUDED}"'
_USO = f"100 * (1 - node_filesystem_avail_bytes{{{_FS}}} / node_filesystem_size_bytes{{{_FS}}})"

SERVIDORES = 'max by (nombre) (up{job=~"node|windows|snmp"})'
PING = 'max by (nombre) (probe_success{job="ping"})'
CPU = '100 * (1 - avg by (nombre) (rate(node_cpu_seconds_total{mode="idle"}[5m])))'
RAM = (
    "100 * (1 - max by (nombre) (node_memory_MemAvailable_bytes) "
    "/ max by (nombre) (node_memory_MemTotal_bytes))"
)
DISCO_MAX = f"max by (nombre) ({_USO})"
DISCOS = f"max by (nombre, mountpoint) ({_USO})"
WIN_DISCOS = (
    'max by (nombre, volume) (100 * (1 - windows_logical_disk_free_bytes{volume=~"[A-Z]:"} '
    '/ windows_logical_disk_size_bytes{volume=~"[A-Z]:"}))'
)
CARGA = "max by (nombre) (node_load1)"
TEMP = (
    'max by (nombre) (node_hwmon_temp_celsius{job="node"}) or '
    'max by (nombre) (node_thermal_zone_temp{job="node"})'
)
UPTIME = "max by (nombre) (time() - node_boot_time_seconds)"
CONTENEDORES = 'count by (nombre) (container_last_seen{job="cadvisor", name!=""})'
# /pendientes: lo mismo que miran las alertas (sin umbral: el bot marca qué avisa y qué está cerca)
CERTIFICADOS = (
    'min by (nombre, instance) ((probe_ssl_earliest_cert_expiry{job=~"web|externo", alerta!="no"} - time())'
    " / 86400)"
)
_PJ = 'job="snmp", tipo="impresora"'
CONSUMIBLES = (
    f"min by (nombre, prtMarkerSuppliesDescription) (100 * prtMarkerSuppliesLevel{{{_PJ}, "
    f'prtMarkerSuppliesType!~"waste.*"}} / (prtMarkerSuppliesMaxCapacity{{{_PJ}}} > 0) >= 0)'
)
"""Igual que la regla «Consumible de impresora bajo» de vigia.alerting (un test lo vigila)."""
_PRODUCTO = "nombre, contenedor, producto, producto_nombre, ciclo, version"
PRODUCTOS = f"max by ({_PRODUCTO}) (vigia_producto_ciclo)"
SOPORTE = f"min by ({_PRODUCTO}) (vigia_soporte_restante_dias)"
AVISO_DIAS = "max by (producto) (vigia_ciclo_aviso_dias)"
VERSIONES = f"max by ({_PRODUCTO}, ultimo) (vigia_version_mayor_disponible)"
PENDIENTES = "max by (nombre) (vigia_actualizaciones_pendientes)"
SEGURIDAD = "max by (nombre) (vigia_actualizaciones_seguridad)"
IMAGENES = 'max by (nombre, contenedor, tipo, local, remota) (wud_containers{nueva="true"})'
DISP_INFO = "netinv_device_info"
DISP_ULTIMA = "netinv_device_last_seen_seconds"
DISP_PRIMERA = "netinv_device_first_seen_seconds"

PROM_CAIDO = "⚠ Prometheus no responde"
GRAFANA_CAIDO = "⚠ Grafana no responde"


class Avisos:
    """Fuentes que no respondieron mientras se preparaba una respuesta (cada aviso, una vez)."""

    def __init__(self) -> None:
        self.lineas: list[str] = []

    def add(self, texto: str) -> None:
        if texto not in self.lineas:
            self.lineas.append(texto)


def serie(prom: Prometheus, avisos: Avisos, expr: str) -> list[tuple[dict[str, str], float]]:
    try:
        return prom.query(expr)
    except FuenteError:
        avisos.add(PROM_CAIDO)
        return []


def por(prom: Prometheus, avisos: Avisos, expr: str, etiqueta: str = "nombre") -> dict[str, float]:
    return {m.get(etiqueta, ""): v for m, v in serie(prom, avisos, expr)}


def estado_host(nombre: str, up: dict[str, float], ping: dict[str, float]) -> str:
    """✅ si responde algún exporter o el ping, ❌ si los hay y ninguno responde, ❔ sin datos."""
    valores = [d[nombre] for d in (up, ping) if nombre in d]
    if not valores:
        return "❔"
    return "✅" if max(valores) >= 1 else "❌"


@dataclass(frozen=True)
class Dispositivo:
    mac: str
    ip: str
    nombre: str
    tipo: str
    ubicacion: str
    fabricante: str
    modelo: str
    encendido: bool
    ultima: float
    primera: float


def dispositivos(prom: Prometheus) -> list[Dispositivo]:
    """Los que netinv vio en sus últimos 30 días. Lanza FuenteError si Prometheus no responde."""
    ultima = {m.get("mac", ""): v for m, v in prom.query(DISP_ULTIMA)}
    primera = {m.get("mac", ""): v for m, v in prom.query(DISP_PRIMERA)}
    out = []
    for m, _ in prom.query(DISP_INFO):
        mac = m.get("mac", "")
        out.append(
            Dispositivo(
                mac=mac,
                ip=m.get("ip", ""),
                nombre=m.get("mostrar") or m.get("nombre") or mac,
                tipo=m.get("tipo", ""),
                ubicacion=m.get("ubicacion", ""),
                fabricante=m.get("fabricante", ""),
                modelo=m.get("modelo", ""),
                encendido=m.get("encendido") == "●",
                ultima=ultima.get(mac, 0.0),
                primera=primera.get(mac, 0.0),
            )
        )
    return out
