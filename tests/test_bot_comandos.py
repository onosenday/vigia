from __future__ import annotations

from typing import Any

from vigia.alerting import FS_EXCLUDED
from vigia.bot import consultas as q
from vigia.bot.comandos import parsear, responder

from .bot_fakes import Serie, contexto

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
        "<b>Ejemplo</b>\n"
        "✅ Nodo 1 · CPU 12% · RAM 40% · disco 95% ⚠\n"
        "❌ Nodo 2\n"
        "✅ NAS\n"
        "Sin alertas"
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
