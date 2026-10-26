from __future__ import annotations

import json
from typing import Any

from vigia.dashboards import dashboards_for
from vigia.model import Site

from .conftest import EXAMPLE


def _gen(d: dict[str, Any]) -> dict[str, dict[str, Any]]:
    s = Site.model_validate(d)
    return {k: json.loads(v) for k, v in dashboards_for(s, EXAMPLE).items()}


def test_branding_everywhere(example_data: dict[str, Any]) -> None:
    gen = _gen(example_data)
    for name, d in gen.items():
        if name == "node-exporter-full.json":  # de terceros: conserva su uid
            assert d["title"].startswith("Ejemplo · ")
            continue
        assert d["uid"].startswith("ejm-"), name
        assert d["tags"] == ["Ejemplo"], name
        if name != "inicio.json":
            assert d["title"].startswith("Ejemplo · "), name
            assert d["links"][0]["url"] == "/d/ejm-inicio"


def test_dashboards_by_capability(example_data: dict[str, Any]) -> None:
    gen = _gen(example_data)
    assert {"equipos-snmp.json", "windows.json", "dispositivos.json", "inicio.json"} <= set(gen)


def test_minimal_site_probes_only(example_data: dict[str, Any]) -> None:
    d = example_data
    d["hosts"] = [{"id": "nodo1", "tipo": "linux", "ip": "10.99.0.10"}]
    d["vips"], d["servicios"], d["dns"], d["bridges"] = [], [], None, []
    d["ping"] = [{"host": "nodo1"}]
    d["modulos"] = {"blackbox": True}
    d["branding"]["portada"] = False
    gen = _gen(d)
    assert set(gen) == {"red-y-servicios.json"}
    ids = {p["id"] for p in gen["red-y-servicios.json"]["panels"]}
    assert 21 not in ids and 33 not in ids and 31 in ids and 11 in ids


def test_server_order(example_data: dict[str, Any]) -> None:
    gen = _gen(example_data)
    cpu = next(p for p in gen["servidores.json"]["panels"] if p["id"] == 2)
    assert [t["legendFormat"] for t in cpu["targets"]] == ["Nodo 1", "nodo2"]
