from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
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
            {
                "labels": {"alertname": "Disco casi lleno", "nombre": "Nodo 1"},
                "startsAt": "2026-10-28T13:20:00Z",
                "annotations": {"summary": "s"},
            },
            {
                "labels": {"alertname": "Caído", "nombre": "Nodo 2"},
                "startsAt": "2026-10-28T13:05:00.123456789Z",
                "annotations": {},
            },
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
                "sitio": "Ejemplo",
                "chat_id": CHAT,
                "zona": "Europe/Madrid",
                "puerto": 9466,
                "prometheus": "http://prometheus:9090",
                "grafana": "http://grafana:3000",
                "netinv": True,
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


class _H(BaseHTTPRequestHandler):
    visto: dict[str, Any] = {}

    def _resp(self, code: int, body: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if "500" in self.path:
            self._resp(500, b"x")
        elif "redir" in self.path:
            self._resp(302, b"", {"Location": "/otro"})
        elif "texto" in self.path:
            self._resp(200, b"no es json")
        elif "alertas" in self.path:
            self._resp(200, json.dumps([{"labels": [1]}, {"labels": {"alertname": "A"}}]).encode())
        else:
            self._resp(200, b"{}")

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers["Content-Length"])
        _H.visto = {"ct": self.headers["Content-Type"], "body": json.loads(self.rfile.read(n))}
        self._resp(200, b"{}")

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def base() -> Iterator[str]:
    srv = HTTPServer(("127.0.0.1", 0), _H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        th.join()


def test_http_500_sin_filtrar_la_ruta(base: str) -> None:
    with pytest.raises(FuenteError) as e:
        http_json(base + "/SECRETO/500")
    assert str(e.value) == "HTTP 500" and "SECRETO" not in repr(e.value)


def test_http_redireccion_no_se_sigue(base: str) -> None:
    with pytest.raises(FuenteError, match="HTTP 302"):
        http_json(base + "/redir")


def test_http_cuerpo_no_json(base: str) -> None:
    with pytest.raises(FuenteError):
        http_json(base + "/texto")


def test_http_post_json(base: str) -> None:
    assert http_json(base + "/p", body={"a": 1}) == {}
    assert _H.visto == {"ct": "application/json", "body": {"a": 1}}


def test_grafana_salta_alertas_malformadas(base: str) -> None:

    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        return http_json(base + "/alertas", headers=headers)

    assert [a.regla for a in Grafana(base, "t", http).alertas()] == ["A"]
