"""Expresiones PromQL por tarea: cada término filtra por el host (`nombre`) y la tarea declarados."""

from __future__ import annotations

from typing import Any

from vigia.model import Site
from vigia.tareas import TEXTFILE_DIR, edad_horas, margen, resultado, retraso, sin_datos, textfile_activo


def _site(d: dict[str, Any]) -> Site:
    d["hosts"][1]["node_exporter"]["textfile"] = True  # nodo1 (nombre «Nodo 1»)
    d["hosts"][2]["node_exporter"]["textfile"] = True  # nodo2
    d["tareas"] = [
        {"nombre": "copias-bd", "host": "nodo2", "max_horas": 26},
        {"nombre": "informe", "host": "nodo1", "max_horas": 30},
    ]
    return Site.model_validate(d)


SEL_BD = 'nombre="nodo2", tarea="copias-bd"'
SEL_INF = 'nombre="Nodo 1", tarea="informe"'


def test_carpeta() -> None:
    assert TEXTFILE_DIR == "/var/lib/vigia/textfile"


def test_textfile_activo(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    assert textfile_activo(s.get_host("nodo2"))
    example_data["hosts"][2]["node_exporter"]["gestion"] = "externo"
    example_data["tareas"] = []
    assert not textfile_activo(Site.model_validate(example_data).get_host("nodo2"))


def test_edad_y_margen_por_tarea(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    ts_bd = f"max by (nombre, tarea) (vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_BD}}})"
    assert edad_horas(s) == (
        f"(time() - {ts_bd}) / 3600"
        " or (time() - max by (nombre, tarea) "
        f"(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_INF}}})) / 3600"
    )
    assert retraso(s).split(" or ")[0] == f"(time() - {ts_bd}) / 3600 - 26"
    assert margen(s).split(" or ")[0] == f"26 - (time() - {ts_bd}) / 3600"


def test_resultado_y_sin_datos(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    assert resultado(s).split(" or ")[:2] == [
        f"max by (nombre, tarea) (vigia_tarea_ultimo_resultado{{{SEL_BD}}})",
        f"2 * absent(vigia_tarea_ultimo_resultado{{{SEL_BD}}})",
    ]
    assert sin_datos(s) == (
        f"absent(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_BD}}})"
        f" or absent(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_INF}}})"
    )


def test_escapa_el_nombre_del_host(example_data: dict[str, Any]) -> None:
    example_data["hosts"][2]["nombre"] = 'Nodo "dos"'
    assert 'nombre="Nodo \\"dos\\""' in sin_datos(_site(example_data))
