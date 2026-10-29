"""What's Up Docker: agente por host con `imagenes` y job de Prometheus que recorta sus etiquetas."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from vigia.build import build_site
from vigia.model import Site

from .conftest import EXAMPLE


def _build(data: dict[str, Any]) -> dict[str, Any]:
    return build_site(Site.model_validate(data), EXAMPLE)


def _job(out: dict[str, Any]) -> dict[str, Any]:
    prom = yaml.safe_load(out["prometheus/prometheus.yml"])
    (job,) = [j for j in prom["scrape_configs"] if j["job_name"] == "imagenes"]
    assert isinstance(job, dict)
    return job


def test_agente_y_job(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["imagenes"]["cron"] = "0 3 * * *"
    out = _build(example_data)
    # nodo1 es el host del monitor: sus agentes van en el compose del monitor
    monitor = yaml.safe_load(next(v for k, v in out.items() if k.endswith("_monitor.yml")))
    wud = monitor["services"]["wud"]
    assert wud["image"] == "getwud/wud"
    assert "WUD_WATCHER_LOCAL_CRON=0 3 * * *" in wud["environment"]
    assert wud["volumes"] == ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    assert "WUD_AUTH_ADMIN_PASSWORD=${WUD_ADMIN_CLAVE}" in wud["environment"]
    assert "WUD_PROMETHEUS_AUTH=false" in wud["environment"]
    assert wud["ports"] == ["9339:3000"]
    job = _job(out)
    assert job["metric_relabel_configs"][0] == {
        "source_labels": ["__name__"],
        "regex": "wud_containers",
        "action": "keep",
    }
    assert job["metric_relabel_configs"][-1]["action"] == "labelkeep"
    objetivos = yaml.safe_load(out["prometheus/targets/imagenes.yml"])
    assert objetivos == [{"targets": ["10.99.0.10:9339"], "labels": {"nombre": "Nodo 1"}}]


def test_sin_hosts_con_imagenes_no_hay_job(example_data: dict[str, Any]) -> None:
    for h in example_data["hosts"]:
        h.pop("imagenes", None)
    out = _build(example_data)
    prom = yaml.safe_load(out["prometheus/prometheus.yml"])
    assert "imagenes" not in {j["job_name"] for j in prom["scrape_configs"]}
    assert "prometheus/targets/imagenes.yml" not in out


def test_solo_en_hosts_con_docker(example_data: dict[str, Any]) -> None:
    router = next(h for h in example_data["hosts"] if h.get("tipo") == "router")
    router["imagenes"] = {"puerto": 9339}
    with pytest.raises(ValidationError, match="no ejecuta Docker"):
        Site.model_validate(example_data)


@pytest.mark.parametrize("cron", ["* * *", "0 3 * * * *", "0 3 * * mon$"])
def test_cron_invalido(example_data: dict[str, Any], cron: str) -> None:
    example_data["modulos"]["imagenes"]["cron"] = cron
    with pytest.raises(ValidationError):
        Site.model_validate(example_data)


def test_imagenes_sin_clave(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["imagenes"] = {}
    with pytest.raises(ValidationError, match="sin `modulos.imagenes.clave`"):
        Site.model_validate(example_data)
