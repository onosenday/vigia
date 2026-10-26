from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from vigia.build import build_site
from vigia.model import load_site
from vigia.newsite import SKILL_REL, NewSite, create

BASE = dict(
    id="oficina",
    nombre="Red de la oficina",
    marca="Oficina",
    subred="10.98.0.0/24",
    dominio="oficina.lan",
    monitor_id="srv1",
    monitor_ip="10.98.0.10",
    usuario="admin",
)


def test_crea_sitio_valido_y_construible(tmp_path: Path) -> None:
    res = create(NewSite(**BASE, sensible=True), tmp_path)
    s = load_site(tmp_path / "site.yaml")
    assert s.branding.prefijo_titulo == "Oficina · "
    assert not s.modulos.netinv.activo
    assert (tmp_path / SKILL_REL).exists() and "CLAUDE.md" in res.files
    assert "datos sensibles" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "oficina_monitor.yml" in build_site(s, tmp_path)


def test_no_sobrescribe(tmp_path: Path) -> None:
    create(NewSite(**BASE), tmp_path)
    with pytest.raises(FileExistsError):
        create(NewSite(**BASE), tmp_path)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("nombre", "Red {{ x }}"), ("dominio", "a b"), ("subred", "10.0.0.0/33"), ("vigia_path", "x; rm -rf /")],
)
def test_parametros_peligrosos(campo: str, valor: str) -> None:
    with pytest.raises(ValidationError):
        NewSite(**{**BASE, campo: valor})
