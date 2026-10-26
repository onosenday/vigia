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


def test_diff_listas_por_contenido() -> None:
    from vigia.diffing import _changes

    a = {"r": [{"regex": "x", "t": 1}, {"regex": "y", "t": 2}]}
    assert _changes(a, {"r": [{"regex": "y", "t": 2}, {"regex": "x", "t": 1}]}) == [
        "r: mismo contenido, otro orden"
    ]
    nuevo = {"r": [{"regex": "y", "t": 2}, {"regex": "z", "t": 3}, {"regex": "x", "t": 1}]}
    assert _changes(a, nuevo) == ["r[regex=z]: añadido"]
    sin_id = {"r": [{"t": 1}, {"t": 2}]}
    assert _changes(sin_id, {"r": [{"t": 1}, {"t": 3}]}) == ['r: - {"t": 2}', 'r: + {"t": 3}']
    assert _changes({"a": 1}, {"a": 2}) == ["a: 1 → 2"]
