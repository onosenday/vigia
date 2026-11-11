from __future__ import annotations

from typing import Any

from vigia.alerting import FS_EXCLUDED
from vigia.bot import consultas as q
from vigia.bot.comandos import parsear, responder
from vigia.bot.config import HostCfg

from .bot_fakes import AHORA, Serie, contexto, ts

N1, N2, NAS = {"nombre": "Nodo 1"}, {"nombre": "Nodo 2"}, {"nombre": "NAS"}

PROM: dict[str, Serie] = {
    q.SERVIDORES: [(N1, 1), (N2, 0)],
    q.PING: [(NAS, 1)],
    q.CPU: [(N1, 12.4)],
    q.RAM: [(N1, 40.2)],
    q.DISCO_MAX: [(N1, 95.0)],
    q.CARGA: [(N1, 0.52)],
    q.TEMP: [(N1, 48.0)],
    q.UPTIME: [(N1, 3 * 86400 + 7200)],
    q.DISCOS: [
        ({"nombre": "Nodo 1", "mountpoint": "/srv/datos"}, 95.2),
        ({"nombre": "Nodo 1", "mountpoint": "/"}, 61.0),
        ({"nombre": "Nodo 2", "mountpoint": "/"}, 10.0),
    ],
    q.CONTENEDORES: [(N1, 14)],
}
CAIDO: list[dict[str, Any]] = [
    {
        "labels": {"alertname": "Caído", "nombre": "Nodo 2"},
        "startsAt": "2026-10-28T13:05:00Z",
        "annotations": {},
    }
]


def test_fs_excluded_igual_que_las_alertas() -> None:
    assert q.FS_EXCLUDED == FS_EXCLUDED


def test_parsear() -> None:
    assert parsear("hola") is None
    assert parsear("/Host  nodo1 ") == ("host", "nodo1")
    assert parsear("/estado@ejemplo_bot") == ("estado", "")
    assert parsear("/info " + "x" * 100) == ("info", "x" * 64)


def test_texto_que_no_es_comando() -> None:
    assert responder("hola", contexto()) is None


def test_comando_desconocido_da_la_ayuda() -> None:
    r = responder("/tostadora", contexto())
    assert r is not None and r.startswith("<b>Comandos</b>")
    assert "/host &lt;nombre o IP&gt; — ficha de un servidor" in r


def test_estado() -> None:
    assert responder("/estado", contexto(PROM)) == (
        "<b>Ejemplo</b>\n✅ Nodo 1 · CPU 12% · RAM 40% · disco 95% ⚠\n❌ Nodo 2\n✅ NAS\nSin alertas"
    )


def test_estado_con_alertas() -> None:
    r = responder("/estado", contexto(PROM, CAIDO))
    assert r is not None and r.endswith("Alertas (1): Caído (Nodo 2)")


def test_estado_con_fuentes_caidas() -> None:
    assert responder("/estado", contexto(prom_caido=True, grafana_caida=True)) == (
        "<b>Ejemplo</b>\n❔ Nodo 1\n❔ Nodo 2\n❔ NAS\n⚠ Prometheus no responde\n⚠ Grafana no responde"
    )


def test_alertas() -> None:
    assert responder("/alertas", contexto(alertas=CAIDO)) == "❌ Caído · Nodo 2 · desde 14:05 (23 min)"
    assert responder("/alertas", contexto()) == "Sin alertas"
    assert responder("/alertas", contexto(grafana_caida=True)) == "⚠ Grafana no responde"


def test_host() -> None:
    assert responder("/host nodo 1", contexto(PROM)) == (
        "✅ <b>Nodo 1</b> · 10.99.0.10 · omv\n"
        "CPU 12% · RAM 40% · carga 0.52 · 48 °C\n"
        "Encendido hace 3 d 2 h\n"
        "💾 / 61%\n"
        "💾 /srv/datos 95% ⚠\n"
        "Contenedores en marcha: 14"
    )


def test_host_por_ip_y_sin_metricas() -> None:
    assert responder("/host 10.99.0.20", contexto(PROM)) == "✅ <b>NAS</b> · 10.99.0.20 · synology"


def test_host_errores() -> None:
    c = contexto(PROM)
    assert responder("/host", c) == "Uso: /host &lt;nombre o IP&gt;"
    assert responder("/host <x>", c) == "No conozco &lt;x&gt;. Hosts: Nodo 1, Nodo 2, NAS"
    assert responder("/host nodo", c) == "Varios coinciden: Nodo 1, Nodo 2. Afina un poco."


def test_host_con_prometheus_caido() -> None:
    assert responder("/host nas", contexto(prom_caido=True)) == (
        "❔ <b>NAS</b> · 10.99.0.20 · synology\n⚠ Prometheus no responde"
    )


def test_alertas_con_fecha_ilegible() -> None:
    raras = [{"labels": {"alertname": "Caído", "nombre": "Nodo 2"}, "startsAt": "basura", "annotations": {}}]
    assert responder("/alertas", contexto(alertas=raras)) == "❌ Caído · Nodo 2 · desde ?"


IMPRESORA = {
    "mac": "aa:bb:cc:00:00:40",
    "ip": "10.99.0.40",
    "nombre": "Impresora",
    "mostrar": "Impresora",
    "tipo": "impresora",
    "ubicacion": "Despacho",
    "fabricante": "Ejemplo SA",
    "modelo": "",
    "encendido": "●",
}
TELE = {
    "mac": "aa:bb:cc:00:00:50",
    "ip": "10.99.0.50",
    "nombre": "",
    "mostrar": "tele-salon ¿?",
    "tipo": "",
    "ubicacion": "",
    "fabricante": "Ejemplo TV",
    "modelo": "",
    "encendido": "○",
}
DISP: dict[str, Serie] = {
    q.DISP_INFO: [(IMPRESORA, 1), (TELE, 1)],
    q.DISP_ULTIMA: [
        ({"mac": "aa:bb:cc:00:00:40"}, AHORA - 180),
        ({"mac": "aa:bb:cc:00:00:50"}, ts(2026, 10, 27, 23, 10)),
    ],
    q.DISP_PRIMERA: [({"mac": "aa:bb:cc:00:00:40"}, ts(2026, 10, 20, 9, 0))],
}


def test_dispositivo() -> None:
    c = contexto(DISP)
    assert responder("/dispositivo impresora", c) == "🟢 Impresora · 10.99.0.40 · visto hace 3 min"
    assert responder("/dispositivo 10.99.0.50", c) == "⚪ tele-salon ¿? · 10.99.0.50 · última vez ayer 23:10"
    assert responder("/dispositivo tostadora", c) == "No conozco tostadora. Prueba /lista"
    assert responder("/dispositivo", c) == "Uso: /dispositivo &lt;nombre, IP o MAC&gt;"


def test_info() -> None:
    assert responder("/info AA-BB-CC-00-00-40", contexto(DISP)) == (
        "🟢 <b>Impresora</b>\n"
        "Tipo: impresora\n"
        "Ubicación: Despacho\n"
        "Fabricante: Ejemplo SA\n"
        "IP: 10.99.0.40\n"
        "MAC: aa:bb:cc:00:00:40\n"
        "Primera vez: 20-10 09:00\n"
        "Última vez: 14:25"
    )


def test_lista() -> None:
    c = contexto(DISP)
    assert responder("/lista", c) == "<b>Encendidos: 1</b>\nimpresora (1): Impresora"
    assert responder("/lista Impresora", c) == "<b>Encendidos: 1</b>\nimpresora (1): Impresora"
    assert responder("/lista tv", c) == "Nada encendido de tipo tv"


def test_dispositivos_sin_netinv_o_sin_prometheus() -> None:
    sin = "Este sitio no tiene netinv: no hay inventario de dispositivos."
    assert responder("/lista", contexto(DISP, netinv=False)) == sin
    assert responder("/info impresora", contexto(DISP, netinv=False)) == sin
    assert responder("/dispositivo impresora", contexto(prom_caido=True)) == "⚠ Prometheus no responde"


def test_estado_escapa_nombres_de_host() -> None:
    hosts = (HostCfg("raro", "A&B <x>", "10.99.0.30", "linux"),)
    r = responder("/estado", contexto(hosts=hosts))
    assert r is not None and "❔ A&amp;B &lt;x&gt;" in r


def test_dispositivo_encendido_sin_ultima_vez() -> None:
    d: dict[str, Serie] = {q.DISP_INFO: [(IMPRESORA, 1)]}
    assert responder("/dispositivo impresora", contexto(d)) == "🟢 Impresora · 10.99.0.40 · conectado"


def test_varios_con_mas_de_ocho_coincidencias() -> None:
    hs = tuple(HostCfg(f"h{i}", f"Equipo {i}", f"10.99.0.{i}", "linux") for i in range(1, 11))
    r = responder("/host equipo", contexto(hosts=hs))
    assert r is not None and r.endswith("Equipo 8 …. Afina un poco.")


def test_lista_sin_tipo_va_a_sin_clasificar() -> None:
    sin_tipo = {**TELE, "encendido": "●"}
    d: dict[str, Serie] = {q.DISP_INFO: [(sin_tipo, 1)]}
    assert responder("/lista", contexto(d)) == "<b>Encendidos: 1</b>\nsin clasificar (1): tele-salon ¿?"


SNMP_HOSTS = (
    HostCfg("imp", "Impresora", "10.99.0.30", "impresora"),
    HostCfg("nas", "NAS", "10.99.0.20", "synology"),
    HostCfg("sw", "Switch", "10.99.0.2", "switch"),
    HostCfg("sai", "SAI", "10.99.0.40", "sai"),
)
IMP, SW, SAI = {"nombre": "Impresora"}, {"nombre": "Switch"}, {"nombre": "SAI"}
PROM_SNMP: dict[str, Serie] = {
    q.SERVIDORES: [(IMP, 1), (NAS, 1), (SW, 1), (SAI, 1)],
    q.IMPRESORA_ESTADO: [(IMP | {"hrPrinterStatus": "idle"}, 1)],
    q.IMPRESORA_PAGINAS: [(IMP, 12345)],
    q.IMPRESORA_PAGINAS_24H: [(IMP, 37.2)],
    q.CONSUMIBLES: [
        (IMP | {"prtMarkerSuppliesDescription": "Tóner negro;SN123"}, 45.0),
        (IMP | {"prtMarkerSuppliesDescription": "Tóner cian;SN124"}, 8.0),
    ],
    q.IMPRESORA_ERRORES: [(IMP | {"vigia_impresora_error": "jammed"}, 1)],
    q.NAS_SISTEMA: [(NAS, 1)],
    q.NAS_TEMP: [(NAS, 41.0)],
    q.NAS_RAID_USO: [(NAS | {"raidName": "Volume 1"}, 62.0), (NAS | {"raidName": "Volume 2"}, 93.0)],
    q.NAS_RAID_ESTADO: [(NAS | {"raidName": "Volume 1"}, 1), (NAS | {"raidName": "Volume 2"}, 11)],
    q.IF_ACTIVAS: [(SW, 8)],
    q.IF_ARRIBA: [(SW, 5)],
    q.SAI_CARGA: [(SAI, 100)],
    q.SAI_MINUTOS: [(SAI, 45)],
    q.SAI_SALIDA: [(SAI, 23)],
}


def test_host_snmp() -> None:
    def ficha(nombre: str) -> str:
        return responder(f"/host {nombre}", contexto(PROM_SNMP, hosts=SNMP_HOSTS)) or ""

    assert ficha("impresora") == (
        "✅ <b>Impresora</b> · 10.99.0.30 · impresora\n"
        "En espera · 12345 páginas (+37 en 24 h)\n"
        "🖨 Tóner cian 8% ⚠ · Tóner negro 45%\n"
        "Errores: jammed ⚠"
    )
    assert ficha("nas") == (
        "✅ <b>NAS</b> · 10.99.0.20 · synology\n"
        "Sistema normal · 41 °C\n"
        "💾 Volume 1 62%\n"
        "💾 Volume 2 93% ⚠ · degradado ⚠"
    )
    assert ficha("switch") == "✅ <b>Switch</b> · 10.99.0.2 · switch\nInterfaces conectadas: 5 de 8"
    assert ficha("sai") == "✅ <b>SAI</b> · 10.99.0.40 · sai\nBatería 100% · 45 min de autonomía · carga 23%"
