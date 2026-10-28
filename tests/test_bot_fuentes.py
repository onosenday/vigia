from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from vigia.bot.config import load
from vigia.bot.fuentes import ALERTAS_API, FuenteError, Grafana, Prometheus, http_json

from .bot_fakes import CHAT, fake_http, ts


def test_prometheus_query() -> None:
    http = fake_http({"up": [({"nombre": "Nodo 1"}, 1.0)]})
    assert Prometheus("http://prometheus:9090", http).query("up") == [({"nombre": "Nodo 1"}, 1.0)]


def test_prometheus_respuesta_de_error() -> None:
    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        return {"status": "error", "error": "parse error"}

    with pytest.raises(FuenteError):
        Prometheus("http://prometheus:9090", http).query("up")


def test_grafana_alertas_ordenadas_y_con_token() -> None:
    vistos: list[Mapping[str, str] | None] = []

    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        vistos.append(headers)
        assert url.endswith(ALERTAS_API)
        return [
            {"labels": {"alertname": "Disco casi lleno", "nombre": "Nodo 1"},
             "startsAt": "2026-10-28T13:20:00Z", "annotations": {"summary": "s"}},
            {"labels": {"alertname": "Caído", "nombre": "Nodo 2"},
             "startsAt": "2026-10-28T13:05:00.123456789Z", "annotations": {}},
        ]

    al = Grafana("http://grafana:3000", "glsa_x", http).alertas()
    assert [a.regla for a in al] == ["Caído", "Disco casi lleno"]
    assert abs(al[0].desde - (ts(2026, 10, 28, 14, 5) + 0.123456)) < 0.001
    assert vistos[0] == {"Authorization": "Bearer glsa_x"}


def test_grafana_sin_token() -> None:
    with pytest.raises(FuenteError):
        Grafana("http://grafana:3000", "", fake_http()).alertas()


def test_repr_sin_token() -> None:
    assert "glsa_x" not in repr(Grafana("http://grafana:3000", "glsa_x", fake_http()))


def test_http_json_no_filtra_la_url() -> None:
    with pytest.raises(FuenteError) as e:
        http_json("http://127.0.0.1:9/bot123456:SECRETO/getMe", timeout=2)
    assert "SECRETO" not in str(e.value) and "SECRETO" not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def _config_json(tmp_path: Path) -> Path:
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "sitio": "Ejemplo", "chat_id": CHAT, "zona": "Europe/Madrid", "puerto": 9466,
                "prometheus": "http://prometheus:9090", "grafana": "http://grafana:3000", "netinv": True,
                "disco_pct": 90,
                "hosts": [{"id": "nodo1", "nombre": "Nodo 1", "ip": "10.99.0.10", "tipo": "omv"}],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_config_load(tmp_path: Path) -> None:
    c = load(_config_json(tmp_path), {"TELEGRAM_TOKEN": "123:abc", "GRAFANA_TOKEN": "glsa_x"})
    assert c.chat_id == CHAT and c.hosts[0].nombre == "Nodo 1" and c.telegram_token == "123:abc"
    assert "123:abc" not in repr(c) and "glsa_x" not in repr(c)


def test_config_sin_token_de_telegram(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        load(_config_json(tmp_path), {})
