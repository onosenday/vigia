"""HTTP de solo lectura a Prometheus y Grafana (y transporte de Telegram), con la biblioteca estándar.

Los errores nunca llevan la URL ni la excepción original: la URL de Telegram contiene el token del bot.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

MAX_RESPUESTA = 5_000_000
ALERTAS_API = "/api/alertmanager/grafana/api/v2/alerts?active=true&silenced=false&inhibited=false"


class FuenteError(Exception):
    """Una fuente no respondió o respondió algo inesperado. El texto es solo el tipo de fallo."""


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    """No sigue redirecciones: el token de Grafana no debe viajar a otro host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_SinRedireccion)


class Http(Protocol):
    def __call__(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any: ...


def http_json(
    url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
) -> Any:
    """GET (o POST con `body` en JSON) y respuesta JSON."""
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")  # noqa: S310 - URLs fijas de config.json
    try:
        with _OPENER.open(req, timeout=timeout) as r:  # noqa: S310 - URLs fijas de config.json
            return json.loads(r.read(MAX_RESPUESTA))
    except urllib.error.HTTPError as e:
        raise FuenteError(f"HTTP {e.code}") from None
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise FuenteError(type(e).__name__) from None


class Prometheus:
    def __init__(self, base: str, http: Http) -> None:
        self.base = base.rstrip("/")
        self.http = http

    def query(self, expr: str) -> list[tuple[dict[str, str], float]]:
        """Consulta instantánea: [(etiquetas, valor)]."""
        d = self.http(f"{self.base}/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
        try:
            if d["status"] != "success":
                raise FuenteError("consulta fallida")
            return [
                ({str(k): str(v) for k, v in r["metric"].items()}, float(r["value"][1]))
                for r in d["data"]["result"]
            ]
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise FuenteError("respuesta no válida") from None


@dataclass(frozen=True)
class Alerta:
    regla: str
    objeto: str
    """Etiqueta `nombre` (el host o servicio afectado)."""
    desde: float
    resumen: str


class Grafana:
    def __init__(self, base: str, token: str, http: Http) -> None:
        self.base = base.rstrip("/")
        self._token = token
        self.http = http

    def __repr__(self) -> str:
        return f"Grafana({self.base!r})"

    def alertas(self) -> list[Alerta]:
        """Alertas disparadas ahora (sin las silenciadas), de la más antigua a la más reciente."""
        if not self._token:
            raise FuenteError("sin token")
        d = self.http(self.base + ALERTAS_API, headers={"Authorization": f"Bearer {self._token}"})
        if not isinstance(d, list):
            raise FuenteError("respuesta no válida")
        out = []
        for a in d:
            if not isinstance(a, dict):
                continue
            lab, ann = a.get("labels") or {}, a.get("annotations") or {}
            if not isinstance(lab, dict) or not isinstance(ann, dict):
                continue
            out.append(
                Alerta(
                    str(lab.get("alertname", "")),
                    str(lab.get("nombre", "")),
                    _instante(str(a.get("startsAt", ""))),
                    str(ann.get("summary", "")),
                )
            )
        return sorted(out, key=lambda x: x.desde)


def _instante(v: str) -> float:
    """ISO 8601 de Grafana (nanosegundos y Z) a epoch; 0 si no se entiende."""
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v).timestamp()
    except ValueError:
        return 0.0
