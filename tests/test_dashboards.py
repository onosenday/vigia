from __future__ import annotations

import json
from typing import Any

from vigia.dashboards import paneles
from vigia.model import Site

from .conftest import EJEMPLO


def _gen(d: dict[str, Any]) -> dict[str, dict[str, Any]]:
    s = Site.model_validate(d)
    return {k: json.loads(v) for k, v in paneles(s, EJEMPLO).items()}


def test_branding_en_todos(datos_ejemplo: dict[str, Any]) -> None:
    gen = _gen(datos_ejemplo)
    for nombre, d in gen.items():
        if nombre == "node-exporter-full.json":  # de terceros: conserva su uid
            assert d["title"].startswith("Ejemplo · ")
            continue
        assert d["uid"].startswith("ejm-"), nombre
        assert d["tags"] == ["Ejemplo"], nombre
        if nombre != "inicio.json":
            assert d["title"].startswith("Ejemplo · "), nombre
            assert d["links"][0]["url"] == "/d/ejm-inicio"


def test_paneles_segun_capacidades(datos_ejemplo: dict[str, Any]) -> None:
    gen = _gen(datos_ejemplo)
    assert {"equipos-snmp.json", "windows.json", "dispositivos.json", "inicio.json"} <= set(gen)


def test_sitio_minimo_solo_sondas(datos_ejemplo: dict[str, Any]) -> None:
    d = datos_ejemplo
    d["hosts"] = [{"id": "nodo1", "tipo": "linux", "ip": "10.99.0.10"}]
    d["vips"], d["servicios"], d["dns"], d["bridges"] = [], [], None, []
    d["ping"] = [{"host": "nodo1"}]
    d["modulos"] = {"blackbox": True}
    d["branding"]["portada"] = False
    gen = _gen(d)
    assert set(gen) == {"red-y-servicios.json"}
    ids = {p["id"] for p in gen["red-y-servicios.json"]["panels"]}
    assert 21 not in ids and 33 not in ids and 31 in ids and 11 in ids


def test_orden_de_servidores(datos_ejemplo: dict[str, Any]) -> None:
    gen = _gen(datos_ejemplo)
    cpu = next(p for p in gen["servidores.json"]["panels"] if p["id"] == 2)
    assert [t["legendFormat"] for t in cpu["targets"]] == ["Nodo 1", "nodo2"]
