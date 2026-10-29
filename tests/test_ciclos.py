from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from vigia import ciclos
from vigia.build import build_site
from vigia.ciclos import Ciclo, Producto
from vigia.cli import app
from vigia.model import Site

from .conftest import EXAMPLE


def _producto(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "producto": "nas-os",
        "nombre": "NAS OS",
        "fuente": "manual",
        "referencia": "notas del fabricante",
        "ciclo_regex": r"^(\d+)\.",
        "ejemplos": {"3.1.4": "3"},
        "comprobado": "2026-01-10",
        "ciclos": [
            {"ciclo": "3", "publicado": "2025-05-01"},
            {
                "ciclo": "2",
                "publicado": "2023-05-01",
                "fin_soporte": "2026-03-31",
                "fin_extendido": "2027-03-31",
            },
        ],
    }
    return base | cambios


def test_catalogo_del_paquete_es_valido() -> None:
    cat = ciclos.cargar()
    assert {"debian", "ubuntu", "openmediavault", "synology-dsm", "proxmox-ve", "truenas"} <= set(cat)
    for p in cat.values():
        assert p.ultimo.ciclo in {c.ciclo for c in p.ciclos}


@pytest.mark.parametrize(
    ("producto", "version", "ciclo"),
    [
        ("openmediavault", "7.7.24-7", "7"),
        ("debian", "12", "12"),
        ("ubuntu", "24.04", "24.04"),
        ("synology-dsm", "7.2.2-72806", "7.2"),
        ("proxmox-ve", "8.4.1", "8"),
        ("truenas", "25.04.2.6", "25.04"),
    ],
)
def test_ciclo_de_version(producto: str, version: str, ciclo: str) -> None:
    assert ciclos.catalogo()[producto].ciclo_de(version) == ciclo


def test_ubuntu_toma_como_referencia_la_ultima_lts() -> None:
    u = ciclos.catalogo()["ubuntu"]
    assert u.ultimo.lts
    assert u.ultimo.ciclo.endswith(".04")


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"ciclo_regex": r"^(\d+"}, "no compila"),
        ({"ciclo_regex": r"^\d+"}, "grupo"),
        ({"ejemplos": {"3.1.4": "2"}}, "ciclo_regex da"),
        ({"ejemplos": {"4.0": "4"}}, "no está en el catálogo"),
        ({"fuente": "endoflife"}, "endoflife"),
        ({"referencia": None}, "referencia"),
        ({"ultimo_lts": True}, "LTS"),
        (
            {
                "ciclos": [
                    {"ciclo": "2", "publicado": "2023-05-01"},
                    {"ciclo": "3", "publicado": "2025-05-01"},
                ]
            },
            "reciente",
        ),
        (
            {
                "ciclos": [
                    {"ciclo": "3", "publicado": "2025-05-01"},
                    {"ciclo": "3", "publicado": "2023-05-01"},
                ]
            },
            "repetidos",
        ),
        ({"nombre": "NAS {{ x }}"}, "nombre"),
    ],
)
def test_producto_invalido(cambios: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        Producto.model_validate(_producto(**cambios))


def test_fecha_que_cuenta() -> None:
    c = Ciclo(
        ciclo="2", publicado=date(2023, 5, 1), fin_soporte=date(2026, 3, 31), fin_extendido=date(2027, 3, 31)
    )
    assert c.fin("normal") == date(2026, 3, 31)
    assert c.fin("extendido") == date(2027, 3, 31)
    sin_extendido = Ciclo(ciclo="1", publicado=date(2020, 1, 1), fin_soporte=date(2022, 1, 31))
    assert sin_extendido.fin("extendido") == date(2022, 1, 31)


def _reglas(cat: ciclos.Catalogo, **kw: Any) -> list[dict[str, Any]]:
    out = ciclos.reglas(cat, **kw)["groups"]
    assert [g["name"] for g in out] == ["vigia-ciclos"]
    rules: list[dict[str, Any]] = out[0]["rules"]
    return rules


def test_reglas_constantes() -> None:
    p = Producto.model_validate(_producto())
    rules = _reglas({p.producto: p})
    fin = [r for r in rules if r["record"] == ciclos.FIN]
    # el ciclo 3 no tiene fecha: no hay serie de fin, solo la de info
    assert fin == [
        {"record": ciclos.FIN, "expr": "vector(1774915200)", "labels": {"producto": "nas-os", "ciclo": "2"}}
    ]
    info = [r["labels"] for r in rules if r["record"] == ciclos.INFO]
    assert info == [
        {"producto": "nas-os", "ciclo": "3", "ultimo": "3"},
        {"producto": "nas-os", "ciclo": "2", "ultimo": "3"},
    ]
    comprobado = [r for r in rules if r["record"] == ciclos.COMPROBADO]
    assert comprobado[0]["expr"] == "vector(1768003200)"


def test_reglas_con_fecha_extendida_del_sitio() -> None:
    p = Producto.model_validate(_producto())
    rules = _reglas({p.producto: p}, fecha_aviso={"nas-os": "extendido"})
    (fin,) = [r for r in rules if r["record"] == ciclos.FIN]
    assert fin["expr"] == "vector(1806451200)"  # 2027-03-31


def _respuesta() -> list[dict[str, Any]]:
    return [
        {"cycle": "2", "releaseDate": "2023-05-01", "eol": True, "extendedSupport": False, "latest": "2.9"},
        {
            "cycle": "3",
            "releaseDate": "2025-05-01",
            "eol": False,
            "extendedSupport": "2032-01-31",
            "lts": True,
        },
    ]


def test_desde_endoflife() -> None:
    p = Producto.model_validate(_producto(fuente="endoflife", endoflife="nas-os", referencia=None))
    urls: list[str] = []

    def fetch(url: str) -> Any:
        urls.append(url)
        return _respuesta()

    nuevo = ciclos.desde_endoflife(p, fetch=fetch, hoy=date(2026, 10, 1))
    assert urls == ["https://endoflife.date/api/nas-os.json"]
    assert nuevo.comprobado == date(2026, 10, 1)
    assert [c.ciclo for c in nuevo.ciclos] == ["3", "2"]  # del más reciente al más antiguo
    tres, dos = nuevo.ciclos
    assert (tres.fin_soporte, tres.fin_extendido, tres.lts) == (None, date(2032, 1, 31), True)
    assert (dos.fin_soporte, dos.fin_extendido, dos.ultima_version) == (date(2026, 10, 1), None, "2.9")
    assert nuevo.ciclo_regex == p.ciclo_regex


def test_desde_endoflife_respuesta_rara() -> None:
    p = Producto.model_validate(_producto(fuente="endoflife", endoflife="nas-os", referencia=None))
    with pytest.raises(ValueError, match="inesperada"):
        ciclos.desde_endoflife(p, fetch=lambda url: {"error": "no"})


def test_guardar_y_cargar(tmp_path: Path) -> None:
    p = Producto.model_validate(_producto())
    ciclos.guardar(p, tmp_path)
    assert ciclos.cargar(tmp_path) == {"nas-os": p}


def test_cargar_nombre_de_fichero_distinto(tmp_path: Path) -> None:
    (tmp_path / "otro.yaml").write_text(yaml.safe_dump(_producto()), encoding="utf-8")
    with pytest.raises(ValueError, match="se llama"):
        ciclos.cargar(tmp_path)


def test_cli_actualizar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eol = Producto.model_validate(
        _producto(producto="nas-os", fuente="endoflife", endoflife="nas-os", referencia=None)
    )
    manual = Producto.model_validate(_producto(producto="otro-os"))
    ciclos.guardar(eol, tmp_path)
    ciclos.guardar(manual, tmp_path)
    monkeypatch.setattr(ciclos, "_fetch", lambda url: _respuesta())
    res = CliRunner().invoke(app, ["ciclos", "actualizar", "--dir", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "nas-os: 2 ciclos" in res.output
    assert "otro-os: a mano" in res.output
    assert ciclos.cargar(tmp_path)["nas-os"].ciclos[0].lts


def test_cli_actualizar_producto_desconocido(tmp_path: Path) -> None:
    shutil.copy(ciclos.CATALOGO_DIR / "debian.yaml", tmp_path)
    res = CliRunner().invoke(app, ["ciclos", "actualizar", "no-existe", "--dir", str(tmp_path)])
    assert res.exit_code == 1


def test_sitio_con_producto_desconocido(example_data: dict[str, Any]) -> None:
    example_data["ciclos"] = {"fecha_aviso": {"no-existe": "extendido"}}
    with pytest.raises(ValidationError, match="no están en el catálogo"):
        Site.model_validate(example_data)


def test_build_genera_las_reglas(example_data: dict[str, Any]) -> None:
    example_data["ciclos"] = {"fecha_aviso": {"debian": "extendido"}}
    out = build_site(Site.model_validate(example_data), EXAMPLE)
    reglas = yaml.safe_load(str(out["prometheus/rules/ciclos.yml"]))
    debian13 = next(
        r
        for r in reglas["groups"][0]["rules"]
        if r["record"] == ciclos.FIN and r["labels"] == {"producto": "debian", "ciclo": "13"}
    )
    fin = ciclos.catalogo()["debian"].ciclos[0].fin_extendido
    assert fin is not None
    assert debian13["expr"] == f"vector({ciclos._epoch(fin)})"
    assert "/etc/prometheus/rules/*.yml" in str(out["prometheus/prometheus.yml"])


def test_regex_promql_equivale_a_la_de_python() -> None:
    import re

    for p in ciclos.catalogo().values():
        for version, ciclo in p.ejemplos.items():
            m = re.fullmatch(p.regex_promql, version)
            assert m and m.group(1) == ciclo, (p.producto, version)


@pytest.mark.parametrize("rx", [r"(\d+)", r"^(\d+)$", r"^(?P<c>\d+)"])
def test_regex_no_admitida(rx: str) -> None:
    with pytest.raises(ValidationError, match="ciclo_regex"):
        Producto.model_validate(_producto(ciclo_regex=rx))


def test_superados_y_derivadas() -> None:
    p = Producto.model_validate(_producto(os_ids=["nasos"]))
    (grupo,) = ciclos.reglas({p.producto: p})["groups"]
    tabla = grupo["rules"]
    fuentes = [r for r in tabla if r["record"] == ciclos.PRODUCTO_CICLO]
    derivadas = [r for r in tabla if r["record"] in (ciclos.RESTANTE, ciclos.MAYOR)]
    assert tabla[-4:] == fuentes + derivadas  # orden: tabla, fuentes y derivadas
    sup = [r["labels"] for r in tabla if r["record"] == ciclos.SUPERADO]
    assert sup == [{"producto": "nas-os", "ciclo": "2", "ultimo": "3"}]
    os, exporter = fuentes
    assert 'node_os_info{id=~"nasos"}' in os["expr"]
    assert '"ciclo", "$1", "version_id", "(\\\\d+)\\\\..*"' in os["expr"]
    assert 'vigia_producto_info{producto="nas-os"}' in exporter["expr"]
    assert '"ciclo", "$1", "version", "(\\\\d+)\\\\..*"' in exporter["expr"]
    assert [r["record"] for r in derivadas] == [ciclos.RESTANTE, ciclos.MAYOR]


def test_sin_os_ids_solo_la_fuente_del_exporter() -> None:
    p = Producto.model_validate(_producto())
    (grupo,) = ciclos.reglas({p.producto: p})["groups"]
    (fuente,) = [r for r in grupo["rules"] if r["record"] == ciclos.PRODUCTO_CICLO]
    assert "node_os_info" not in fuente["expr"]
