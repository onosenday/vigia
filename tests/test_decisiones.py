"""decisiones.yaml: validación y lectura (datos sintéticos)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from vigia.decisiones import a_json, load_decisiones, quitar_entradas

HOSTS = ["Nodo 1", "NAS"]


def _f(tmp_path: Path, texto: str) -> Path:
    p = tmp_path / "decisiones.yaml"
    p.write_text(texto, encoding="utf-8")
    return p


def test_lee_y_normaliza(tmp_path: Path) -> None:
    p = _f(
        tmp_path,
        "- {seccion: imagenes, host: Nodo 1, objeto: prometheus, ofrecido: v3.15.1, motivo: LTS, ref: T-1}\n"
        "- {seccion: versiones, host: NAS, objeto: postgresql, ofrecido: 18, motivo: espera}\n"
        "- {seccion: soporte, host: NAS, objeto: grafana, revisar: 2027-01-15, motivo: lejos}\n",
    )
    ds = load_decisiones(p, HOSTS)
    assert [d.ofrecido for d in ds] == ["v3.15.1", "18", None]  # 18 llega como int de YAML
    assert ds[2].revisar == dt.date(2027, 1, 15)
    assert a_json(ds)[2] == {
        "seccion": "soporte", "host": "NAS", "objeto": "grafana", "motivo": "lejos", "revisar": "2027-01-15"
    }


def test_fichero_vacio(tmp_path: Path) -> None:
    assert load_decisiones(_f(tmp_path, "# nada decidido\n"), HOSTS) == []


@pytest.mark.parametrize(
    ("texto", "error"),
    [
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, motivo: m}\n", "ofrecido` o `revisar"),
        ("- {seccion: digest, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m}\n", "digest"),
        ("- {seccion: discos, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m}\n", "seccion"),
        ("- {seccion: imagenes, host: Otro, objeto: x, ofrecido: v2, motivo: m}\n", "Otro"),
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m, otro: 1}\n", "otro"),
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, ofrecido: v2, motivo: ''}\n", "motivo"),
        ("{seccion: imagenes}\n", "list"),
    ],
)
def test_errores(tmp_path: Path, texto: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        load_decisiones(_f(tmp_path, texto), HOSTS)


TEXTO = (
    "# Cabecera: se conserva\n"
    "- {seccion: imagenes, host: Nodo 1, objeto: a, ofrecido: v2, motivo: uno}\n"
    "# comentario de primer nivel: se conserva\n"
    "- seccion: imagenes\n"
    "  host: Nodo 1\n"
    "  objeto: b   # comentario de la entrada: se va con ella\n"
    "  ofrecido: v2\n"
    "  motivo: dos\n"
    "- {seccion: imagenes, host: Nodo 1, objeto: c, ofrecido: v2, motivo: tres}\n"
)


def test_quitar_entradas() -> None:
    assert quitar_entradas(TEXTO, {1}) == (
        "# Cabecera: se conserva\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: a, ofrecido: v2, motivo: uno}\n"
        "# comentario de primer nivel: se conserva\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: c, ofrecido: v2, motivo: tres}\n"
    )
    assert quitar_entradas(TEXTO, {0, 2}).count("- ") == 1
    assert quitar_entradas(TEXTO, set()) == TEXTO


def test_quitar_entradas_formato_raro() -> None:
    with pytest.raises(ValueError, match="a mano"):
        quitar_entradas("[{seccion: imagenes}]\n", {0})
