"""Config, http y datos falsos del bot (sintéticos)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from vigia.bot.comandos import Contexto
from vigia.bot.config import Config, HostCfg
from vigia.bot.fuentes import FuenteError, Grafana, Http, Prometheus

ZONA = "Europe/Madrid"
TZ = ZoneInfo(ZONA)
CHAT = -1000000000001
Serie = list[tuple[dict[str, str], float]]


def ts(y: int, mo: int, d: int, h: int, mi: int) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


AHORA = ts(2026, 10, 28, 14, 28)

HOSTS = (
    HostCfg("nodo1", "Nodo 1", "10.99.0.10", "omv"),
    HostCfg("nodo2", "Nodo 2", "10.99.0.11", "linux"),
    HostCfg("nas", "NAS", "10.99.0.20", "synology"),
)


def cfg(**cambios: Any) -> Config:
    base: dict[str, Any] = {
        "sitio": "Ejemplo",
        "chat_id": CHAT,
        "zona": ZONA,
        "puerto": 9466,
        "prometheus": "http://prometheus:9090",
        "grafana": "http://grafana:3000",
        "netinv": True,
        "disco_pct": 90,
        "hosts": HOSTS,
        "telegram_token": "123456:token-sintetico",
        "grafana_token": "glsa_sintetico",
    }
    base.update(cambios)
    return Config(**base)


def fake_http(
    prom: Mapping[str, Serie] | None = None,
    alertas: list[dict[str, Any]] | None = None,
    prom_caido: bool = False,
    grafana_caida: bool = False,
) -> Http:
    """Prometheus responde `prom[expresión]`; Grafana, `alertas`. `*_caido` simula la fuente sin respuesta."""

    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        if url.startswith("http://prometheus:9090/"):
            if prom_caido:
                raise FuenteError("URLError")
            expr = parse_qs(urlsplit(url).query)["query"][0]
            result = [{"metric": m, "value": [AHORA, str(v)]} for m, v in (prom or {}).get(expr, [])]
            return {"status": "success", "data": {"resultType": "vector", "result": result}}
        if url.startswith("http://grafana:3000/"):
            if grafana_caida:
                raise FuenteError("HTTP 401")
            return alertas or []
        raise AssertionError(f"URL inesperada: {url}")

    return http


def contexto(
    prom: Mapping[str, Serie] | None = None,
    alertas: list[dict[str, Any]] | None = None,
    prom_caido: bool = False,
    grafana_caida: bool = False,
    **cambios: Any,
) -> Contexto:
    c = cfg(**cambios)
    h = fake_http(prom, alertas, prom_caido, grafana_caida)
    prom_, grafana = Prometheus(c.prometheus, h), Grafana(c.grafana, c.grafana_token, h)
    return Contexto(c, prom_, grafana, ahora=lambda: AHORA)
