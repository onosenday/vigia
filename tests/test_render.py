from __future__ import annotations

import pytest
import yaml

from vigia.render import Crudo, escalar, plantilla


@pytest.mark.parametrize("valor", ["a: b", "x\n  inyectada: 1", '"; rm -rf /', "${SECRETO}", "{{ 7*7 }}"])
def test_escalar_no_rompe_yaml(valor: str) -> None:
    doc = yaml.safe_load(f"clave: {escalar(valor)}\notra: 1\n")
    assert doc == {"clave": valor, "otra": 1}


def test_crudo_sin_comillas() -> None:
    assert escalar(Crudo("# hola")) == "# hola"


def test_tipo_no_permitido() -> None:
    with pytest.raises(TypeError):
        escalar(object())


def test_plantilla_indefinida() -> None:
    import jinja2

    with pytest.raises(jinja2.UndefinedError):
        plantilla("grafana/dashboards.yml.j2")
