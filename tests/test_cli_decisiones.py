"""vigia decisiones contra un Prometheus falso (datos sintéticos)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from vigia import cli
from vigia.bot import consultas as c

from .bot_fakes import fake_http
from .conftest import EXAMPLE


@pytest.fixture
def sitio(tmp_path: Path) -> Path:
    shutil.copytree(EXAMPLE, tmp_path / "s")
    (tmp_path / "s" / "decisiones.yaml").write_text(
        "# cabecera\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: prometheus, ofrecido: v3.15.1, motivo: LTS}\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: grafana, ofrecido: 13.3.0, motivo: vieja}\n",
        encoding="utf-8",
    )
    return tmp_path / "s" / "site.yaml"


def _prom(monkeypatch: pytest.MonkeyPatch, caido: bool = False) -> None:
    datos = {
        c.IMAGENES: [
            (
                {
                    "nombre": "Nodo 1",
                    "contenedor": "prometheus",
                    "tipo": "tag",
                    "local": "v3.13.5",
                    "remota": "v3.15.1",
                },
                1,
            )
        ]
    }
    http = fake_http(datos, prom_caido=caido)

    def falso(url: str, **kw: Any) -> Any:
        assert url.startswith("http://10.99.0.10:9390/")  # monitor del ejemplo
        return http(url.replace("http://10.99.0.10:9390/", "http://prometheus:9090/"), **kw)

    monkeypatch.setattr(cli, "http_json", falso)


def test_estado(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch)
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio)])
    assert r.exit_code == 0, r.output
    assert "[vigente] imagenes · Nodo 1 · prometheus v3.15.1" in r.output
    assert "[obsoleta] imagenes · Nodo 1 · grafana 13.3.0" in r.output


def test_limpiar(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch)
    f = sitio.parent / "decisiones.yaml"
    antes = f.read_text(encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio), "--limpiar"])
    assert r.exit_code == 0 and "-- {seccion: imagenes, host: Nodo 1, objeto: grafana" in r.output
    assert f.read_text(encoding="utf-8") == antes  # sin --yes, solo diff
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio), "--limpiar", "--yes"])
    assert r.exit_code == 0
    assert f.read_text(encoding="utf-8") == antes.replace(antes.splitlines(keepends=True)[2], "")


def test_prometheus_caido(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch, caido=True)
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio)])
    assert r.exit_code == 1 and "no responde" in r.output


def test_decisiones_rotas_sin_traceback(sitio: Path) -> None:
    (sitio.parent / "decisiones.yaml").write_text("- {seccion: discos}\n", encoding="utf-8")
    for orden in (["build", "-s", str(sitio), "-o", str(sitio.parent / "b")], ["validate", "-s", str(sitio)]):
        r = CliRunner().invoke(cli.app, orden)
        assert r.exit_code == 1, r.output  # mensaje limpio, sin traceback
        assert "decisiones.yaml" in r.output
