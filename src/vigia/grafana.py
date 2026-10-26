"""Ajustes de Grafana que no se pueden provisionar por fichero (nombre de la organización)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from vigia.model import Site


class GrafanaError(RuntimeError):
    pass


def _url(s: Site) -> str:
    return f"http://{s.monitor_host.ip}:{s.monitor.puertos.grafana}"


def _request(s: Site, token: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - URL construida con IP y puerto validados
        _url(s) + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise GrafanaError(f"Grafana respondió {e.code} a {method} {path}") from None
    except OSError as e:
        raise GrafanaError(f"no se pudo conectar con Grafana en {_url(s)}: {e}") from None


def brand(s: Site, secrets: Mapping[str, str], apply: bool) -> str:
    """Pone el nombre del sitio a la organización de Grafana. Devuelve qué ha hecho (o haría)."""
    var = s.monitor.grafana_token
    if not var or not secrets.get(var):
        raise GrafanaError("falta monitor.grafana_token en site.yaml o su valor en el fichero de entorno")
    token = secrets[var]
    actual = _request(s, token, "GET", "/api/org").get("name")
    deseado = s.sitio.nombre
    if actual == deseado:
        return f"organización ya se llama «{deseado}»"
    if not apply:
        return f"organización «{actual}» → «{deseado}» (añade --yes para aplicarlo)"
    _request(s, token, "PUT", "/api/org", {"name": deseado})
    return f"organización renombrada: «{actual}» → «{deseado}»"
