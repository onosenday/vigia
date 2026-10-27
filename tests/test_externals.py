"""Objetivos externos: validación estricta (destinos públicos, puertos sensibles con opt-in) y lo generado."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from vigia.build import build_site
from vigia.model import Site

from .conftest import EXAMPLE


def _with(example_data: dict[str, Any], *objs: dict[str, Any], **cfg: Any) -> dict[str, Any]:
    example_data["externos"] = {"objetivos": list(objs), **cfg}
    return example_data


@pytest.mark.parametrize(
    ("obj", "msg"),
    [
        ({"nombre": "x", "host": "10.1.2.3"}, "no es una IP pública"),
        ({"nombre": "x", "host": "192.168.1.1"}, "no es una IP pública"),
        ({"nombre": "x", "host": "127.0.0.1"}, "no es una IP pública"),
        ({"nombre": "x", "host": "169.254.169.254"}, "no es una IP pública"),  # metadatos de nube
        ({"nombre": "x", "host": "100.64.0.1"}, "no es una IP pública"),  # CGNAT
        ({"nombre": "x", "host": "::1"}, "no es una IP pública"),
        ({"nombre": "x", "host": "localhost"}, "nombre interno"),
        ({"nombre": "x", "host": "nas.lan"}, "nombre interno"),
        ({"nombre": "x", "url": "https://10.0.0.5/"}, "no es una IP pública"),
        ({"nombre": "x", "url": "https://intranet.local/"}, "nombre interno"),
        ({"nombre": "x", "host": "srv.example.net", "puertos": [3306]}, "puertos_sensibles"),
        ({"nombre": "x", "host": "srv.example.net", "puertos": [22, 443]}, "SSH"),
        ({"nombre": "x", "url": "https://www.example.org/", "host": "www.example.org"}, "uno de los dos"),
        ({"nombre": "x"}, "uno de los dos"),
        ({"nombre": "x", "url": "https://www.example.org/", "puertos": [443]}, "`puertos` va con `host`"),
        ({"nombre": "x", "host": "srv.example.net", "puertos": [443, 443]}, "repetidos"),
    ],
)
def test_destinos_rechazados(example_data: dict[str, Any], obj: dict[str, Any], msg: str) -> None:
    with pytest.raises(ValidationError, match=msg):
        Site.model_validate(_with(example_data, obj))


def test_nombre_del_dominio_del_sitio_rechazado(example_data: dict[str, Any]) -> None:
    example_data["red"]["dominio"] = "ejemplo.org"
    with pytest.raises(ValidationError, match="dominio del sitio"):
        Site.model_validate(_with(example_data, {"nombre": "x", "url": "https://intranet.ejemplo.org/"}))


def test_intervalo_minimo_y_tope(example_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="mínimo 60s"):
        Site.model_validate(_with(example_data, intervalo="30s"))
    many = [{"nombre": f"web {i}", "url": f"https://w{i}.example.org/"} for i in range(51)]
    with pytest.raises(ValidationError, match="como mucho 50"):
        Site.model_validate(_with(example_data, *many))


def test_opt_in_de_puerto_sensible_y_aviso_de_http(example_data: dict[str, Any]) -> None:
    s = Site.model_validate(
        _with(
            example_data,
            {"nombre": "ssh", "host": "srv.example.net", "puertos": [22], "puertos_sensibles": True},
            {"nombre": "web vieja", "url": "http://old.example.org/"},
        )
    )
    assert any("http sin TLS" in w for w in s.warnings())


def test_generado(example_data: dict[str, Any]) -> None:
    out = build_site(Site.model_validate(example_data), EXAMPLE)
    groups = yaml.safe_load(out["prometheus/targets/externos.yml"])
    by = {(g["labels"]["nombre"], g["labels"]["tipo"]): g for g in groups}
    assert by[("Web corporativa", "web")]["labels"]["__param_module"] == "https_externo"
    assert by[("Servidor externo", "ping")]["targets"] == ["servidor.example.net"]
    assert by[("Servidor externo", "tcp")]["targets"] == ["servidor.example.net:443"]
    assert by[("SSH del servidor externo", "tcp")]["labels"]["alerta"] == "no"
    bb = yaml.safe_load(out["blackbox/blackbox.yml"])["modules"]
    assert bb["https_externo"]["http"]["fail_if_not_ssl"] is True
    assert "insecure_skip_verify" not in str(bb["https_externo"])  # TLS verificado siempre
    assert bb["tcp_externo"]["prober"] == "tcp" and "query_response" not in bb["tcp_externo"].get("tcp", {})
    prom = yaml.safe_load(out["prometheus/prometheus.yml"])
    job = next(j for j in prom["scrape_configs"] if j["job_name"] == "externo")
    assert job["scrape_interval"] == "60s"
    rules = {
        r["uid"]: r["data"][0]["model"]["expr"]
        for r in yaml.safe_load(out["grafana-provisioning/alerting/vigia.yml"])["groups"][0]["rules"]
    }
    assert "externo" in rules["vigia-caido"] and "externo" in rules["vigia-certificado"]
    assert 'job!~"web|servicio|ping|dns|externo"' in rules["vigia-exporter"]
    assert "dashboards/externos.json" in out


def test_sin_externos_no_se_genera_nada(example_data: dict[str, Any]) -> None:
    example_data.pop("externos", None)
    out = build_site(Site.model_validate(example_data), EXAMPLE)
    assert "prometheus/targets/externos.yml" not in out and "dashboards/externos.json" not in out
    assert "https_externo" not in out["blackbox/blackbox.yml"]
