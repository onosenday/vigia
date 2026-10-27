"""vigia descubrir: clasificación, filtrado y propuesta (sin red: fuentes y sondeo simulados)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from vigia.cli import app
from vigia.discover import Seen, classify, discover, render
from vigia.model import DeviceType, Host, Site

from .conftest import EXAMPLE


@pytest.mark.parametrize(
    ("seen", "tipo"),
    [
        (Seen("x", {8006, 22}), DeviceType.proxmox),
        (Seen("x", {5000, 5001}, vendor="Synology Incorporated"), DeviceType.synology),
        (Seen("x", {9182, 3389}), DeviceType.windows),
        (Seen("x", {3493}), DeviceType.sai),
        (Seen("x", {80}, vendor="APC by Schneider Electric"), DeviceType.sai),
        (Seen("x", {9100, 80}), DeviceType.impresora),
        (Seen("x", {631}), DeviceType.impresora),
        (Seen("x", {22, 9100}, node_metrics=True), DeviceType.linux),
        (Seen("x", {22, 9100}, vendor="Raspberry Pi Trading", node_metrics=True), DeviceType.raspbian),
        (Seen("x", {80, 443}, vendor="Sagemcom Broadband"), DeviceType.router),
        (Seen("x", {22, 443}, vendor="Ubiquiti Inc"), DeviceType.switch),
        (Seen("x", {80}, hints="web=openmediavault control panel"), DeviceType.omv),
        (Seen("x", {22}), DeviceType.linux),
    ],
)
def test_clasifica_infraestructura(seen: Seen, tipo: DeviceType) -> None:
    c = classify(seen)
    assert c is not None
    assert c[0] is tipo


@pytest.mark.parametrize(
    "seen",
    [
        Seen("x", set()),  # móvil, tele: sin puertos de infraestructura
        Seen("x", {445, 3389}),  # puesto Windows sin windows_exporter
        Seen("x", {22, 445, 3389}),
        Seen("x", {80}, vendor="Espressif Inc."),  # IoT
    ],
)
def test_clientes_no_se_proponen(seen: Seen) -> None:
    assert classify(seen) is None


def _netinv_site(example_data: dict[str, Any]) -> Site:
    return Site.model_validate(example_data)


def _fake_netinv(_: str) -> list[Seen]:
    return [
        Seen("10.99.0.10", vendor="ya en el sitio"),
        Seen("10.99.0.50", names=["Proxmox-1"]),
        Seen("10.99.0.51", names=["Movil de alguien"]),
        Seen("10.99.0.52", vendor="Synology Incorporated"),
        Seen("192.0.2.9"),  # fuera de la subred
    ]


def _fake_probe(devices: list[Seen], _: float) -> None:
    ports = {"10.99.0.50": {22, 8006}, "10.99.0.52": {5000, 5001}}
    for d in devices:
        d.ports = ports.get(d.ip, set())


def test_descubre_desde_netinv(example_data: dict[str, Any]) -> None:
    s = _netinv_site(example_data)
    r = discover(s, "auto", fetch=_fake_netinv, prober=_fake_probe)
    assert r.source == "netinv"
    assert [(p.seen.ip, p.tipo) for p in r.proposals] == [
        ("10.99.0.50", DeviceType.proxmox),
        ("10.99.0.52", DeviceType.synology),
    ]
    assert (r.clients, r.known) == (1, 1)


def test_propuesta_valida_y_sin_ids_repetidos(example_data: dict[str, Any]) -> None:
    s = _netinv_site(example_data)
    text = render(s, discover(s, "netinv", fetch=_fake_netinv, prober=_fake_probe))
    doc = yaml.safe_load(text)
    hosts = [Host.model_validate(h) for h in doc["hosts"]]
    assert [h.id for h in hosts] == ["proxmox-1", "synology-1"]
    assert doc["ping"] == [{"host": "proxmox-1"}, {"host": "synology-1"}]
    assert "Movil de alguien" not in text  # los clientes no aparecen ni en comentarios
    # la propuesta se puede pegar en el sitio y sigue siendo válido
    example_data["hosts"] += doc["hosts"]
    Site.model_validate(example_data)


def test_nombres_vistos_saneados(example_data: dict[str, Any]) -> None:
    s = _netinv_site(example_data)

    def fetch(_: str) -> list[Seen]:
        return [Seen("10.99.0.60", names=["x\n  - id: inyectado\n{{ $x }}"])]

    def prober(devices: list[Seen], _: float) -> None:
        devices[0].ports = {8006}

    text = render(s, discover(s, "netinv", fetch=fetch, prober=prober))
    assert [h["id"] for h in yaml.safe_load(text)["hosts"]] == ["proxmox-1"]
    assert "{{" not in text and "$" not in text


def test_local_sin_netinv(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["netinv"]["activo"] = False
    s = _netinv_site(example_data)
    r = discover(s, "auto", scan=lambda _s, _t: [Seen("10.99.0.70")], prober=lambda d, _t: None)
    assert r.source == "local"
    assert r.clients == 1


def test_netinv_inactivo_y_fuente_netinv_falla(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["netinv"]["activo"] = False
    with pytest.raises(ValueError, match="netinv activo"):
        discover(_netinv_site(example_data), "netinv")


def _site_copy(tmp_path: Path, example_data: dict[str, Any], ignore: bool) -> Path:
    for f in EXAMPLE.rglob("*"):
        if f.is_file():
            dest = tmp_path / f.relative_to(EXAMPLE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read_bytes())
    (tmp_path / "site.yaml").write_text(yaml.safe_dump(example_data, allow_unicode=True), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if ignore:
        (tmp_path / ".gitignore").write_text("propuesta.yaml\n", encoding="utf-8")
    return tmp_path / "site.yaml"


def test_cli_sin_yes_solo_explica(tmp_path: Path, example_data: dict[str, Any]) -> None:
    site = _site_copy(tmp_path, example_data, ignore=True)
    r = CliRunner().invoke(app, ["descubrir", "--site", str(site)])
    assert r.exit_code == 0, r.output
    assert "--yes" in r.output
    assert not (tmp_path / "propuesta.yaml").exists()


def test_cli_exige_autorizacion(tmp_path: Path, example_data: dict[str, Any]) -> None:
    example_data["modulos"]["netinv"] = {"activo": False}
    site = _site_copy(tmp_path, example_data, ignore=True)
    r = CliRunner().invoke(app, ["descubrir", "--site", str(site), "--yes"])
    assert r.exit_code == 1
    assert "autorizacion" in r.output


def test_cli_exige_propuesta_fuera_de_git(tmp_path: Path, example_data: dict[str, Any]) -> None:
    site = _site_copy(tmp_path, example_data, ignore=False)
    r = CliRunner().invoke(app, ["descubrir", "--site", str(site), "--yes"])
    assert r.exit_code == 1
    assert ".gitignore" in r.output


def test_netinv_aporta_puertos_y_deduplica(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json
    import urllib.request

    from vigia import discover as disc

    data = {
        "aa:00:00:00:00:01": {
            "ip": "10.99.0.5",
            "puertos": ["9100/tcp jetdirect", "137/udp nb"],
            "visto_ultima": 2,
        },
        "aa:00:00:00:00:02": {"ip": "10.99.0.5", "puertos": [], "visto_ultima": 1},
        "aa:00:00:00:00:03": {"ip": "10.99.0.6", "aleatoria": True},
    }
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout=0: io.BytesIO(json.dumps(data).encode())
    )
    seen = disc.from_netinv("http://10.99.0.10:9877/devices.json")
    assert [(d.ip, d.ports) for d in seen] == [("10.99.0.5", {9100})]


def test_sin_respuesta_conserva_puertos_de_netinv(monkeypatch: pytest.MonkeyPatch) -> None:
    from vigia import discover as disc

    monkeypatch.setattr(disc, "_tcp_open", lambda ip, port, timeout: False)
    d = Seen("10.99.0.5", {9100}, vendor="Hewlett Packard")
    disc.probe([d], 0.1)
    assert (d.live, d.ports, d.node_metrics) == (False, {9100}, False)
    c = classify(d)
    assert c is not None
    assert c[0] is DeviceType.impresora
