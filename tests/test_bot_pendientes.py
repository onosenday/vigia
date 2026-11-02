"""/pendientes y la línea de versión de /host, con un Prometheus falso (datos sintéticos)."""

from __future__ import annotations

from datetime import date

import pytest

from vigia.alerting import printer_rules
from vigia.bot import consultas as c
from vigia.bot.comandos import responder
from vigia.bot.decisiones import OBSOLETA, VIGENTE, Decision
from vigia.bot.fuentes import FuenteError
from vigia.bot.pendientes import estado_decisiones
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
    assert texto == "⚠ Prometheus no responde"  # sin datos no dice que no haya nada pendiente


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


DEC = (
    Decision("imagenes", "Nodo 1", "grafana", "esperamos a la 13.4", ofrecido="13.3.0", ref="T-1"),
    Decision("soporte", "NAS", "debian", "se retira el NAS", revisar=date(2026, 12, 1)),
    Decision("soporte", "Nodo 2", "debian", "lo sabemos", ofrecido="11"),  # con ⚠: no se oculta
    Decision("digest", "Nodo 1", "pihole", "la actualiza watchtower", revisar=date(2027, 1, 1)),
    Decision("imagenes", "Nodo 1", "grafana", "oferta vieja", ofrecido="13.2.0"),  # obsoleta
)


def test_pendientes_con_decisiones() -> None:
    lineas = (responder("/pendientes", contexto(PROM, decisiones=DEC)) or "").splitlines()
    assert "NAS · Debian 12: soporte hasta 25-02-2027 · próximo" not in lineas
    assert "Nodo 2 · Debian 11: sin soporte desde hace 59 días ⚠ (decidido: lo sabemos)" in lineas
    assert "Nodo 1: 1 con imagen nueva sin cambiar de etiqueta (homepage)" in lineas
    i = lineas.index("<b>✔ Decidido (no hace falta hacer nada)</b>")
    assert lineas[i + 1 :] == [
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo — se retira el NAS; revisar el 01-12-2026",
        "Nodo 1 · grafana 13.0.2 → 13.3.0 — esperamos a la 13.4 (T-1)",
        "Nodo 1 · pihole: imagen nueva sin cambiar de etiqueta — la actualiza watchtower; "
        "revisar el 01-01-2027",
        "1 decisión obsoleta o vencida: vigia decisiones --limpiar",
    ]
    assert not any(x.startswith("Nodo 1 · grafana") for x in lineas[:i])


def test_todo_decidido() -> None:
    prom = {c.IMAGENES: PROM[c.IMAGENES][:1]}
    texto = responder("/pendientes", contexto(prom, decisiones=DEC[:1])) or ""
    assert texto.splitlines() == [
        "Nada pendiente ✅",
        "<b>✔ Decidido (no hace falta hacer nada)</b>",
        "Nodo 1 · grafana 13.0.2 → 13.3.0 — esperamos a la 13.4 (T-1)",
    ]


def test_estado_decisiones() -> None:
    ctx = contexto(PROM, decisiones=DEC)
    assert [e for _, e in estado_decisiones(ctx.cfg, ctx.prom, ctx.ahora())] == [
        VIGENTE, VIGENTE, VIGENTE, VIGENTE, OBSOLETA
    ]


def test_estado_decisiones_sin_prometheus() -> None:
    ctx = contexto(prom_caido=True, decisiones=DEC)
    with pytest.raises(FuenteError):
        estado_decisiones(ctx.cfg, ctx.prom, ctx.ahora())


def _soporte(nombre: str, restante: float) -> tuple[dict[str, str], float]:
    return _nodo(nombre, producto="debian", producto_nombre="Debian", ciclo="12", version="12"), restante


def test_decididas_en_orden_de_secciones() -> None:
    prom = {
        c.SOPORTE: [_soporte("NAS", 120.0), _soporte("Nodo 1", 100.0)],
        c.IMAGENES: PROM[c.IMAGENES],
    }
    dec = (
        Decision("soporte", "NAS", "debian", "a"),
        Decision("soporte", "Nodo 1", "debian", "b"),
        Decision("digest", "Nodo 1", "pihole", "c"),
        Decision("digest", "Nodo 1", "homepage", "d"),
    )
    lineas = (responder("/pendientes", contexto(prom, decisiones=dec)) or "").splitlines()
    assert lineas[lineas.index("<b>✔ Decidido (no hace falta hacer nada)</b>") + 1 :] == [
        "Nodo 1 · Debian 12: soporte hasta 05-02-2027 · próximo — b",
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo — a",
        "Nodo 1 · homepage: imagen nueva sin cambiar de etiqueta — d",
        "Nodo 1 · pihole: imagen nueva sin cambiar de etiqueta — c",
    ]


def test_datos_parciales_no_dicen_nada_pendiente() -> None:
    prom = {c.SOPORTE: [_soporte("NAS", 120.0)]}
    dec = (
        Decision("soporte", "NAS", "debian", "se retira"),
        Decision("imagenes", "Nodo 1", "grafana", "no se cuenta", ofrecido="13.3.0"),
    )
    ctx = contexto(prom, decisiones=dec, consulta_caida=c.IMAGENES)
    lineas = (responder("/pendientes", ctx) or "").splitlines()
    assert lineas == [
        "⚠ Prometheus no responde",
        "<b>✔ Decidido (no hace falta hacer nada)</b>",
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo — se retira",
    ]


def test_datos_parciales_con_pendientes_ponen_avisos_antes_de_lo_decidido() -> None:
    prom = {c.CERTIFICADOS: PROM[c.CERTIFICADOS], c.SOPORTE: [_soporte("NAS", 120.0)]}
    dec = (Decision("soporte", "NAS", "debian", "se retira"), Decision("digest", "Nodo 1", "x", "y"))
    ctx = contexto(prom, decisiones=dec, consulta_caida=c.IMAGENES)
    lineas = (responder("/pendientes", ctx) or "").splitlines()
    assert lineas[-3:] == [
        "⚠ Prometheus no responde",
        "<b>✔ Decidido (no hace falta hacer nada)</b>",
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo — se retira",
    ]


def test_decision_vencida() -> None:
    prom = {c.SOPORTE: [_soporte("NAS", 120.0)]}
    dec = (Decision("soporte", "NAS", "debian", "caducada", revisar=date(2026, 10, 28)),)
    lineas = (responder("/pendientes", contexto(prom, decisiones=dec)) or "").splitlines()
    assert lineas == [
        "<b>🧭 Soporte</b>",
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo",
        "1 decisión obsoleta o vencida: vigia decisiones --limpiar",
    ]
