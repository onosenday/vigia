"""Qué línea de /pendientes cubre cada decisión (datos sintéticos)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from vigia.bot.config import desde_dict, load
from vigia.bot.decisiones import OBSOLETA, VENCIDA, VIGENTE, Decision, Juez, desde_json

HOY = date(2026, 10, 28)
M = {"nombre": "Nodo 1", "contenedor": "prometheus", "producto": "prometheus"}


def _j(*ds: Decision) -> Juez:
    return Juez(ds, HOY)


def test_coincide_por_host_objeto_y_ofrecido() -> None:
    d = Decision("imagenes", "Nodo 1", "prometheus", "LTS", ofrecido="v3.15.1")
    j = _j(d)
    assert j.busca("imagenes", M, "v3.15.1") is d
    assert j.busca("imagenes", M, "v3.16.0") is None  # otra oferta: decisión nueva
    assert j.busca("versiones", M, "v3.15.1") is None
    assert j.busca("imagenes", M | {"nombre": "NAS"}, "v3.15.1") is None
    assert j.estado() == [(d, VIGENTE)]


def test_objeto_por_producto_o_contenedor() -> None:
    d = Decision("soporte", "Nodo 1", "grafana", "lejos", revisar=date(2026, 12, 1))
    assert _j(d).busca("soporte", {"nombre": "Nodo 1", "producto": "grafana"}, "13.0") is d
    assert _j(d).busca("soporte", {"nombre": "Nodo 1", "contenedor": "grafana", "producto": "x"}, "1") is d


def test_obsoleta_y_vencida() -> None:
    sin_uso = Decision("imagenes", "Nodo 1", "a", "m", ofrecido="2")
    vencida = Decision("digest", "Nodo 1", "prometheus", "m", revisar=HOY)  # el mismo día ya vence
    j = _j(sin_uso, vencida)
    assert j.busca("digest", M) is None
    assert j.estado() == [(sin_uso, OBSOLETA), (vencida, VENCIDA)]


def test_desde_json_y_config(tmp_path: Path) -> None:
    lista = [{"seccion": "soporte", "host": "NAS", "objeto": "g", "motivo": "m", "revisar": "2027-01-15"}]
    assert desde_json(lista) == (Decision("soporte", "NAS", "g", "m", revisar=date(2027, 1, 15)),)
    base = {
        "sitio": "S", "chat_id": -1, "zona": "Europe/Madrid", "puerto": 9466, "prometheus": "http://p:9090",
        "grafana": "http://g:3000", "netinv": False, "disco_pct": 90, "hosts": [],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(base | {"decisiones": lista}), encoding="utf-8")
    assert load(p, {"TELEGRAM_TOKEN": "t"}).decisiones == desde_json(lista)
    assert desde_dict(base, {}, sin_telegram=True).decisiones == ()  # config.json anterior, sin la clave
