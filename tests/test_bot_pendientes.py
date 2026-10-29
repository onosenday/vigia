"""/pendientes y la línea de versión de /host, con un Prometheus falso (datos sintéticos)."""

from __future__ import annotations

from vigia.alerting import printer_rules
from vigia.bot import consultas as c
from vigia.bot.comandos import responder
from vigia.model import Site

from .bot_fakes import Serie, cfg, contexto


def _nodo(nombre: str, **m: str) -> dict[str, str]:
    return {"nombre": nombre} | m


PROM: dict[str, Serie] = {
    c.CERTIFICADOS: [
        ({"nombre": "web-1", "instance": "https://web-1.ejemplo.lan"}, 9.4),
        ({"nombre": "web-2", "instance": "https://web-2.ejemplo.lan"}, 30.0),
        ({"nombre": "web-3", "instance": "https://web-3.ejemplo.lan"}, 200.0),
    ],
    c.CONSUMIBLES: [
        ({"nombre": "Impresora", "prtMarkerSuppliesDescription": "Tóner negro;SN123"}, 8.0),
        ({"nombre": "Impresora", "prtMarkerSuppliesDescription": "Tóner cian;SN124"}, 19.0),
        ({"nombre": "Impresora", "prtMarkerSuppliesDescription": "Tóner amarillo;SN125"}, 70.0),
    ],
    c.DISCOS: [
        ({"nombre": "Nodo 2", "mountpoint": "/srv"}, 92.0),
        ({"nombre": "Nodo 1", "mountpoint": "/"}, 81.0),
        ({"nombre": "Nodo 1", "mountpoint": "/datos"}, 40.0),
    ],
    c.AVISO_DIAS: [({"producto": "debian"}, 90), ({"producto": "postgresql"}, 90)],
    c.SOPORTE: [
        (_nodo("Nodo 1", producto="debian", producto_nombre="Debian", ciclo="13", version="13"), 1300.0),
        (_nodo("Nodo 2", producto="debian", producto_nombre="Debian", ciclo="11", version="11"), -59.0),
        (
            _nodo(
                "Nodo 1",
                contenedor="bd",
                producto="postgresql",
                producto_nombre="PostgreSQL",
                ciclo="14",
                version="14",
            ),
            14.0,
        ),
        (_nodo("NAS", producto="debian", producto_nombre="Debian", ciclo="12", version="12"), 120.0),
    ],
    c.PRODUCTOS: [
        (_nodo("Nodo 1", producto="debian", producto_nombre="Debian", ciclo="13", version="13"), 1),
        (
            _nodo(
                "Nodo 1",
                producto="openmediavault",
                producto_nombre="OpenMediaVault",
                ciclo="8",
                version="8.6.0-1",
            ),
            1,
        ),
        (
            _nodo("Nodo 1", contenedor="bd", producto="postgresql", producto_nombre="PostgreSQL", ciclo="14"),
            1,
        ),
    ],
    c.VERSIONES: [
        (
            _nodo(
                "Nodo 2", producto="debian", producto_nombre="Debian", ciclo="11", version="11", ultimo="13"
            ),
            1,
        ),
    ],
    c.PENDIENTES: [({"nombre": "Nodo 1"}, 12.0), ({"nombre": "Nodo 2"}, 0.0)],
    c.SEGURIDAD: [({"nombre": "Nodo 1"}, 3.0)],
    c.IMAGENES: [
        (_nodo("Nodo 1", contenedor="grafana", tipo="tag", local="13.0.2", remota="13.3.0"), 1),
        (_nodo("Nodo 1", contenedor="pihole", tipo="digest", local="sha256:a", remota="sha256:b"), 1),
        (_nodo("Nodo 1", contenedor="homepage", tipo="digest", local="sha256:c", remota="sha256:d"), 1),
    ],
}


def test_pendientes() -> None:
    texto = responder("/pendientes", contexto(PROM))
    assert texto is not None
    assert texto.splitlines() == [
        "<b>🔐 Certificados</b>",
        "web-1: caduca en 9 días ⚠",
        "web-2: caduca en 30 días · próximo",
        "<b>🖨 Consumibles</b>",
        "Impresora: Tóner negro 8% ⚠ · Tóner cian 19% próximo",
        "<b>💽 Discos</b>",
        "Nodo 1 / 81% · próximo",
        "Nodo 2 /srv 92% ⚠",
        "<b>🧭 Soporte</b>",
        "Nodo 1 · PostgreSQL 14 (bd): pierde el soporte en 14 días ⚠",
        "Nodo 2 · Debian 11: sin soporte desde hace 59 días ⚠",
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo",
        "<b>⬆ Versiones mayores</b>",
        "Nodo 2 · Debian 11 → 13",
        "<b>🛡 Actualizaciones</b>",
        "Nodo 1: 12 (3 de seguridad) ⚠",
        "<b>🐳 Imágenes</b>",
        "Nodo 1 · grafana 13.0.2 → 13.3.0",
        "Nodo 1: 2 con imagen nueva sin cambiar de etiqueta (homepage, pihole)",
    ]


def test_nada_pendiente() -> None:
    assert responder("/pendientes", contexto({})) == "Nada pendiente ✅"


def test_pendientes_con_prometheus_caido() -> None:
    texto = responder("/pendientes", contexto(prom_caido=True))
    assert texto == "Nada pendiente ✅\n⚠ Prometheus no responde"


def test_margenes_propios() -> None:
    ctx = contexto(PROM)
    ctx.cfg = cfg(
        proximo=type(ctx.cfg.proximo)(certificado_dias=10, consumible_pct=10, disco_pct=91, soporte_dias=30)
    )
    texto = responder("/pendientes", ctx) or ""
    assert "web-2" not in texto and "cian" not in texto and "Nodo 1 / " not in texto and "NAS" not in texto


def test_host_con_versiones() -> None:
    texto = responder("/host nodo 1", contexto(PROM)) or ""
    assert "🧭 Debian 13 · soporte hasta" in texto
    assert "🧭 OpenMediaVault 8.6.0-1 · soporte sin fecha de fin" in texto
    assert "PostgreSQL" not in texto  # los contenedores no salen en /host


def test_host_sin_soporte_y_version_mayor() -> None:
    texto = responder("/host nodo 2", contexto(PROM | {c.PRODUCTOS: [(PROM[c.SOPORTE][1][0], 1)]})) or ""
    assert "🧭 Debian 11 · sin soporte desde hace 59 días ⚠ · ya existe la 13" in texto


def test_consumibles_igual_que_la_alerta(example_data: dict[str, object]) -> None:
    (consumible, _) = printer_rules(Site.model_validate(example_data))
    assert consumible["data"][0]["model"]["expr"] == c.CONSUMIBLES
