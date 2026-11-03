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
        ("linuxmint", "22.1", "22.1"),
        ("windows-server", "10.0.20348", "2022"),
        ("windows-server", "10.0.17763", "2019"),  # también es la de 1809-sac: cuenta el LTSC
        ("windows-server", "10.0.99999", None),
    ],
)
def test_ciclo_de_version(producto: str, version: str, ciclo: str | None) -> None:
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
        ({"ciclo_regex": None}, "uno de los dos"),
        ({"windows_producto": "NAS OS"}, "uno de los dos"),
        ({"ciclo_regex": None, "windows_producto": "NAS OS", "os_ids": ["nasos"]}, "no va con"),
        ({"ciclo_regex": None, "windows_producto": "NAS {OS}"}, "windows_producto"),
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
    # terminado sin fecha (true): conserva la que ya tenía el catálogo (31-03), no la del refresco
    assert (dos.fin_soporte, dos.fin_extendido, dos.ultima_version) == (date(2026, 3, 31), None, "2.9")
    assert nuevo.ciclo_regex == p.ciclo_regex


def test_terminado_sin_fecha_y_sin_fecha_previa_cuenta_hoy() -> None:
    previo = [{"ciclo": "3", "publicado": "2025-05-01"}, {"ciclo": "2", "publicado": "2023-05-01"}]
    p = Producto.model_validate(
        _producto(fuente="endoflife", endoflife="nas-os", referencia=None, ciclos=previo)
    )
    nuevo = ciclos.desde_endoflife(p, fetch=lambda url: _respuesta(), hoy=date(2026, 10, 1))
    assert nuevo.ciclos[1].fin_soporte == date(2026, 10, 1)


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
        if p.ciclo_regex is None:  # Windows: por versión exacta, sin expresión
            continue
        for version, ciclo in p.ejemplos.items():
            m = re.fullmatch(p.regex_promql, version)
            assert m and m.group(1) == ciclo, (p.producto, version)


@pytest.mark.parametrize("rx", [r"(\d+)", r"^(\d+)$", r"^(?=1)(\d+)", r"^(\d)\1"])
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
    assert 'node_os_info{id=~"nasos", version_id!=""}' in os["expr"]
    rx = ciclos._q(p.regex_promql)  # (?:(\d+)\.) seguido de cualquier cosa
    assert f'"ciclo", "$1", "version_id", {rx}' in os["expr"]
    assert 'vigia_producto_info{producto="nas-os"}' in exporter["expr"]
    assert f'"ciclo", "$1", "version", {rx}' in exporter["expr"]
    assert [r["record"] for r in derivadas] == [ciclos.RESTANTE, ciclos.MAYOR]


def _windows() -> Producto:
    return Producto.model_validate(
        _producto(
            producto="win-srv",
            ciclo_regex=None,
            windows_producto="Windows Server",
            ejemplos={"10.0.300": "30", "10.0.200": "20"},
            ciclos=[
                {"ciclo": "30", "publicado": "2025-05-01", "ultima_version": "10.0.300", "lts": True},
                {"ciclo": "20", "publicado": "2023-06-01", "ultima_version": "10.0.200", "lts": True},
                {"ciclo": "20-sac", "publicado": "2023-05-01", "ultima_version": "10.0.200"},
            ],
        )
    )


def test_windows_por_version_exacta() -> None:
    p = _windows()
    assert p.por_version == {"10.0.300": "30", "10.0.200": "20"}  # el LTS gana al semestral
    (grupo,) = ciclos.reglas({p.producto: p})["groups"]
    tabla = [r["labels"] for r in grupo["rules"] if r["record"] == ciclos.VERSION]
    assert {"producto": "win-srv", "ciclo": "20", "version": "10.0.200"} in tabla and len(tabla) == 2
    (fuente,) = [r for r in grupo["rules"] if r["record"] == ciclos.PRODUCTO_CICLO]
    assert fuente["labels"] == {"producto": "win-srv", "fuente": "windows"}  # sin updates-exporter
    assert 'windows_os_info{product=~"Windows Server' in fuente["expr"]
    assert 'group_left (producto, ciclo) vigia_ciclo_version{producto="win-srv"}' in fuente["expr"]
    assert " or on (nombre) " in fuente["expr"]  # la versión desconocida, como ciclo


def test_hay_versiones_con_solo_windows(example_data: dict[str, Any]) -> None:
    for h in example_data["hosts"]:
        for clave in ("node_exporter", "cadvisor", "imagenes", "actualizaciones"):
            h.pop(clave, None)
    example_data.pop("tareas", None)
    example_data["modulos"]["updates_exporter"] = {"activo": False}
    s = Site.model_validate(example_data)
    assert ciclos.hay_versiones(s)
    assert not ciclos.hay_versiones(
        s.model_copy(update={"hosts": [h for h in s.hosts if not h.windows_exporter]})
    )


def test_sin_os_ids_solo_la_fuente_del_exporter() -> None:
    p = Producto.model_validate(_producto())
    (grupo,) = ciclos.reglas({p.producto: p})["groups"]
    (fuente,) = [r for r in grupo["rules"] if r["record"] == ciclos.PRODUCTO_CICLO]
    assert "node_os_info" not in fuente["expr"]


IMAGEN = r"^(?:.*/)?nasos:(\d+\.\d+)"


def test_ciclo_de_imagen_del_catalogo() -> None:
    cat = ciclos.catalogo()
    assert cat["postgresql"].ciclo_de_imagen("ghcr.io/immich-app/postgres:14-vectorchord0.3.0") == "14"
    assert cat["postgresql"].ciclo_de_imagen("postgres:latest") is None
    assert cat["prometheus"].ciclo_de_imagen("prom/prometheus:v3.15.1") == "3.15"
    assert cat["redis"].ciclo_de_imagen("redis:8") is None  # etiqueta sin el ciclo exacto: se ignora
    assert cat["debian"].ciclo_de_imagen("debian:12") is None  # sin imagen_regex


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"imagen_regex": IMAGEN}, "van juntos"),
        ({"ejemplos_imagen": {"nasos:3.1": "3"}}, "van juntos"),
        ({"imagen_regex": IMAGEN, "ejemplos_imagen": {"nasos:3.1": "2"}}, "da el ciclo"),
        ({"imagen_regex": r"^nasos:(?!x)(\d+)", "ejemplos_imagen": {"nasos:3": "3"}}, "lookarounds"),
    ],
)
def test_imagen_invalida(cambios: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        Producto.model_validate(_producto(**cambios))


def test_aviso_por_producto_y_sin_aviso_de_version() -> None:
    rapido = Producto.model_validate(_producto(producto="rapido", aviso_dias=14, aviso_version=False))
    normal = Producto.model_validate(_producto())
    (grupo,) = ciclos.reglas({"rapido": rapido, "nas-os": normal}, soporte_dias=60)["groups"]
    avisos = {r["labels"]["producto"]: r["expr"] for r in grupo["rules"] if r["record"] == ciclos.AVISO}
    assert avisos == {"rapido": "vector(14)", "nas-os": "vector(60)"}
    superados = {r["labels"]["producto"] for r in grupo["rules"] if r["record"] == ciclos.SUPERADO}
    assert superados == {"nas-os"}


def test_fuente_de_contenedores() -> None:
    p = Producto.model_validate(
        _producto(imagen_regex=IMAGEN, ejemplos_imagen={"x/nasos:3.1": "3", "nasos:3": None})
    )
    (grupo,) = ciclos.reglas({p.producto: p})["groups"]
    (fuente,) = [r for r in grupo["rules"] if "container_last_seen" in r["expr"]]
    assert fuente["record"] == ciclos.PRODUCTO_CICLO
    assert fuente["expr"].startswith(
        "group by (nombre, contenedor, producto, producto_nombre, ciclo, version)"
    )
    selector = 'container_last_seen{image=~"' + ciclos._promql(IMAGEN).replace("\\", "\\\\") + '", name!=""}'
    assert selector in fuente["expr"]


def test_promql_agrupa_las_alternativas() -> None:
    import re

    rx = ciclos._promql(r"^(\d+)|v(\d+)")
    assert rx.startswith("(?:") and re.fullmatch(rx, "v3-extra")  # el resto cuelga de las dos alternativas


POLITICA = {"rama": "lts", "motivo": "seguimos la LTS"}


def _con_politica(**cambios: Any) -> dict[str, Any]:
    base = _producto(
        imagen_regex=IMAGEN, ejemplos_imagen={"x/nasos:3.1": "3", "nasos:3": None}, politica=POLITICA
    )
    base["ciclos"][1]["lts"] = True  # el ciclo 2 es la LTS
    return base | cambios


def test_politica_de_rama() -> None:
    p = Producto.model_validate(_con_politica())
    assert p.politica is not None and p.politica.rama == "lts"
    assert ciclos.catalogo()["prometheus"].politica is not None


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"ciclos": [{"ciclo": "3", "publicado": "2025-05-01"}]}, "ningún ciclo LTS"),
        ({"imagen_regex": None, "ejemplos_imagen": {}}, "imagen_regex"),
        ({"politica": {"rama": "lts", "motivo": 'con "comillas"'}}, "motivo"),
        ({"politica": {"rama": "estable", "motivo": "x"}}, "rama"),
    ],
)
def test_politica_invalida(cambios: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        Producto.model_validate(_con_politica(**cambios))


def test_actualizar_conserva_la_politica() -> None:
    p = Producto.model_validate(_con_politica(fuente="endoflife", endoflife="nas-os", referencia=None))
    nuevo = ciclos.desde_endoflife(p, fetch=lambda _url: _respuesta(), hoy=date(2026, 10, 1))
    assert nuevo.politica == p.politica
