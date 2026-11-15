"""netinv: sin nombres anunciados (`nombres_anunciados: false`) y escucha en una sola IP."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from vigia.build import build_site
from vigia.model import Site

from .conftest import EXAMPLE

NETINV = Path(__file__).parent.parent / "src" / "vigia" / "images" / "netinv" / "netinv.py"


def _netinv(monkeypatch: pytest.MonkeyPatch, names: str) -> Any:
    """Carga netinv.py con zeroconf simulado (solo existe en su imagen)."""
    zc = types.ModuleType("zeroconf")
    for n in ("ServiceBrowser", "ServiceListener", "Zeroconf", "ZeroconfServiceTypes"):
        setattr(zc, n, type(n, (), {}))
    monkeypatch.setitem(sys.modules, "zeroconf", zc)
    monkeypatch.setenv("SUBNET", "10.99.0.0/24")
    monkeypatch.setenv("NAMES", names)
    spec = importlib.util.spec_from_file_location("netinv_test", NETINV)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DEV = {
    "mac": "02:00:00:00:00:09",
    "aleatoria": True,
    "ip": "10.99.0.50",
    "fabricante": "(MAC aleatoria)",
    "visto_ultima": 0,
    "n_dhcp": ["iPhone-de-Persona"],
    "n_mdns": ["Persona-MacBook"],
    "n_netbios": ["PC-PERSONA"],
    "modelo": ["md=iPhone14,2", "fn=Salón de Persona", "friendlyName=TV de Persona", "web=NAS de Persona"],
}


def test_sin_nombres_no_se_recogen(monkeypatch: pytest.MonkeyPatch) -> None:
    ni = _netinv(monkeypatch, "0")
    d = ni.dev("02:00:00:00:00:09")
    ni.add_name(d, "n_dhcp", "iPhone-de-Persona")
    ni.add_model(d, "fn=Salón de Persona")
    ni.add_model(d, "friendlyName=TV de Persona")
    ni.add_model(d, "md=iPhone14,2")
    assert "n_dhcp" not in d
    assert d["modelo"] == ["md=iPhone14,2"]


def test_con_nombres_se_recogen(monkeypatch: pytest.MonkeyPatch) -> None:
    ni = _netinv(monkeypatch, "1")
    d = ni.dev("02:00:00:00:00:09")
    ni.add_name(d, "n_dhcp", "iPhone-de-Persona")
    ni.add_model(d, "fn=Salón")
    assert d["n_dhcp"] == ["iPhone-de-Persona"] and d["modelo"] == ["fn=Salón"]


def test_purga_el_estado_guardado(monkeypatch: pytest.MonkeyPatch) -> None:
    ni = _netinv(monkeypatch, "0")
    ni.state["devices"] = {DEV["mac"]: dict(DEV)}
    ni.purge_names()
    d = ni.state["devices"][DEV["mac"]]
    assert not {"n_dhcp", "n_mdns", "n_netbios"} & d.keys()
    assert d["modelo"] == ["md=iPhone14,2"]


def test_metricas_sin_nombres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ni = _netinv(monkeypatch, "0")
    clas = tmp_path / "devices.yaml"
    clas.write_text("dispositivos:\n  - {nombre_dhcp: iPhone-de-Persona, nombre: Móvil, tipo: movil}\n")
    monkeypatch.setattr(ni, "CLASSIFICATION", str(clas))
    monkeypatch.setattr(ni.time, "time", lambda: 1000)
    ni.state["devices"] = {DEV["mac"]: {**DEV, "visto_ultima": 1000}}  # sin purgar: también filtra
    out = ni.metrics()
    assert "Persona" not in out and "Móvil" not in out  # ni por nombre_dhcp se cruza
    assert 'mostrar="(MAC aleatoria) ¿?"' in out


def test_site_nombres_anunciados_por_defecto() -> None:
    s = Site.model_validate(yaml.safe_load((EXAMPLE / "site.yaml").read_text(encoding="utf-8")))
    assert s.modulos.netinv.nombres_anunciados is True


def _monitor(data: dict[str, Any]) -> dict[str, Any]:
    out = build_site(Site.model_validate(data), EXAMPLE)
    monitor: dict[str, Any] = yaml.safe_load(next(v for k, v in out.items() if k.endswith("_monitor.yml")))
    return monitor


def test_compose_sin_nombres(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["netinv"]["nombres_anunciados"] = False
    env = _monitor(example_data)["services"]["netinv"]["environment"]
    assert "NAMES=0" in env


def test_compose_con_nombres(example_data: dict[str, Any]) -> None:
    env = _monitor(example_data)["services"]["netinv"]["environment"]
    assert "NAMES=0" not in env


def test_sin_nombres_rechaza_nombre_dhcp(example_data: dict[str, Any], tmp_path: Path) -> None:
    shutil.copytree(EXAMPLE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "devices.yaml").write_text("dispositivos:\n  - {nombre_dhcp: movil-x, nombre: Móvil}\n")
    example_data["modulos"]["netinv"]["nombres_anunciados"] = False
    with pytest.raises(ValueError, match="nombre_dhcp"):
        build_site(Site.model_validate(example_data), tmp_path)


def _prom_target(data: dict[str, Any]) -> list[str]:
    out = build_site(Site.model_validate(data), EXAMPLE)
    prom = yaml.safe_load(out["prometheus/prometheus.yml"])
    (job,) = [j for j in prom["scrape_configs"] if j["job_name"] == "netinv"]
    targets: list[str] = job["static_configs"][0]["targets"]
    return targets


def test_escucha_por_defecto_en_la_ip_del_monitor(example_data: dict[str, Any]) -> None:
    env = _monitor(example_data)["services"]["netinv"]["environment"]
    assert "LISTEN=10.99.0.10" in env
    assert _prom_target(example_data) == ["10.99.0.10:9877"]


def test_escucha_en_otra_ip(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["netinv"]["escucha"] = "10.99.0.200"
    env = _monitor(example_data)["services"]["netinv"]["environment"]
    assert "LISTEN=10.99.0.200" in env
    assert _prom_target(example_data) == ["10.99.0.200:9877"]


@pytest.mark.parametrize("ip", ["127.0.0.1", "0.0.0.0", "::1"])
def test_escucha_rechaza_loopback_y_todas(example_data: dict[str, Any], ip: str) -> None:
    example_data["modulos"]["netinv"]["escucha"] = ip
    with pytest.raises(ValidationError, match="escucha"):
        Site.model_validate(example_data)


def test_servidor_escucha_en_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LISTEN", "10.99.0.10")
    ni = _netinv(monkeypatch, "1")
    assert ni.LISTEN == "10.99.0.10"
