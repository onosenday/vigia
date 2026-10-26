from __future__ import annotations

import pytest
import yaml

from vigia.render import Raw, render_template, to_scalar


@pytest.mark.parametrize("value", ["a: b", "x\n  inyectada: 1", '"; rm -rf /', "${SECRETO}", "{{ 7*7 }}"])
def test_scalar_does_not_break_yaml(value: str) -> None:
    doc = yaml.safe_load(f"clave: {to_scalar(value)}\notra: 1\n")
    assert doc == {"clave": value, "otra": 1}


def test_raw_unquoted() -> None:
    assert to_scalar(Raw("# hola")) == "# hola"


def test_disallowed_type() -> None:
    with pytest.raises(TypeError):
        to_scalar(object())


def test_undefined_template_variable() -> None:
    import jinja2

    with pytest.raises(jinja2.UndefinedError):
        render_template("grafana/dashboards.yml.j2")
