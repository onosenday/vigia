"""Las reglas de ciclos y las alertas de soporte evaluadas por Prometheus de verdad (`promtool test rules`).

Lo esperado se calcula con el catálogo a fecha fija (HOY): si `vigia ciclos actualizar` cambia una fecha
que cruza un umbral, el test lo señala y hay que revisarlo. Se salta si no hay promtool. Con Docker:
VIGIA_PROMTOOL='docker run --rm -u {uid} -v {dir}:{dir} -w {dir} --entrypoint promtool prom/prometheus:latest'
uv run pytest tests/test_ciclos_promtool.py
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from vigia import alerting, ciclos
from vigia.model import Site

HOY = datetime(2026, 10, 29, tzinfo=UTC)
HORAS = int(HOY.timestamp()) // 3600


def _promtool(d: Path) -> list[str] | None:
    plantilla = os.environ.get("VIGIA_PROMTOOL")
    if plantilla:
        return shlex.split(plantilla.format(dir=d, uid=os.getuid()))
    exe = shutil.which("promtool")
    return [exe] if exe else None


def _dias(producto: str, ciclo: str) -> float:
    p = ciclos.catalogo()[producto]
    c = next(c for c in p.ciclos if c.ciclo == ciclo)
    fin = c.fin(p.fecha_aviso)
    assert fin is not None
    return (ciclos._epoch(fin) - HOY.timestamp()) / 86400


def _serie(nombre: str, os_id: str, version: str) -> dict[str, str]:
    return {
        "series": f'node_os_info{{nombre="{nombre}", id="{os_id}", version_id="{version}", job="node"}}',
        "values": "1 1",  # una muestra en 0 y otra en HOY (interval = HORAS)
    }


def _contenedor(nombre: str, imagen: str) -> dict[str, str]:
    return {
        "series": f'container_last_seen{{nombre="srv-1", name="{nombre}", image="{imagen}", job="cadvisor"}}',
        "values": "1 1",
    }


def _windows(nombre: str, producto: str, version: str) -> dict[str, str]:
    return {
        "series": f'windows_os_info{{nombre="{nombre}", product="{producto}", version="{version}", '
        f'build_number="{version.rsplit(".", 1)[-1]}", job="windows"}}',
        "values": "1 1",
    }


def _wud(contenedor: str, imagen: str, local: str, remota: str) -> dict[str, str]:
    """Imagen nueva con otra etiqueta según What's Up Docker (`imagen` sin etiqueta, como la publica)."""
    return {
        "series": f'wud_containers{{nombre="srv-1", contenedor="{contenedor}", imagen="{imagen}", '
        f'local="{local}", remota="{remota}", nueva="true", tipo="tag", job="imagenes"}}',
        "values": "1 1",
    }


def _etiquetas(labels: dict[str, str]) -> str:
    return "{" + ", ".join(f'{k}="{v}"' for k, v in labels.items()) + "}"


def _ultimo(producto: str) -> str:
    return ciclos.catalogo()[producto].ultimo.ciclo


def _muestras(expr: str, esperado: list[dict[str, Any]]) -> dict[str, Any]:
    return {"expr": expr, "eval_time": f"{HORAS}h", "exp_samples": esperado}


def test_reglas_y_alertas_en_prometheus(tmp_path: Path, example_data: dict[str, Any]) -> None:
    cmd = _promtool(tmp_path)
    if not cmd:
        pytest.skip("sin promtool (ver VIGIA_PROMTOOL)")
    example_data["alertas"].setdefault("umbrales", {})["soporte_dias"] = 700
    reglas = ciclos.reglas(ciclos.catalogo(), soporte_dias=700)
    (tmp_path / "ciclos.yml").write_text(yaml.safe_dump(reglas), encoding="utf-8")
    ops = {"gt": ">", "lt": "<"}
    exprs = {}  # cada expresión con el umbral que aplica Grafana: lo que queda es lo que avisa
    for r in alerting.support_rules(Site.model_validate(example_data)):
        cond = r["data"][1]["model"]["conditions"][0]["evaluator"]
        exprs[r["uid"]] = f"({r['data'][0]['model']['expr']}) {ops[cond['type']]} {cond['params'][0]}"

    def info(nombre: str, producto: str, ciclo: str, version: str, **extra: str) -> str:
        base = {"nombre": nombre, "producto": producto, "producto_nombre": ciclos.catalogo()[producto].nombre}
        labels = base | {"ciclo": ciclo, "version": version} | extra
        return "{" + ", ".join(f'{k}="{v}"' for k, v in labels.items()) + "}"

    pruebas = [
        # Debian 12: con soporte (610 días) y con versión mayor (13)
        _muestras(
            exprs["vigia-version-mayor"],
            [
                {"labels": info("srv-1", "debian", "12", "12", ultimo="13"), "value": 1},
                {"labels": info("pi-1", "debian", "11", "11", ultimo="13"), "value": 1},
                # Ubuntu: la referencia es la última LTS (26.04), no la 26.10
                {"labels": info("srv-3", "ubuntu", "24.04", "24.04", ultimo="26.04"), "value": 1},
                # Linux Mint 22.1: la referencia es la última Mint (no una LMDE)
                {
                    "labels": info("mint-1", "linuxmint", "22.1", "22.1", ultimo=_ultimo("linuxmint")),
                    "value": 1,
                },
                # Windows Server por el build: 2016, 2019 (el 17763 es también 1809-sac) y 2022
                {"labels": info("dc-1", "windows-server", "2022", "10.0.20348", ultimo="2025"), "value": 1},
                {"labels": info("dc-2", "windows-server", "2016", "10.0.14393", ultimo="2025"), "value": 1},
                {"labels": info("dc-3", "windows-server", "2019", "10.0.17763", ultimo="2025"), "value": 1},
                # OMV 7 por el updates-exporter: ya existe la 8
                {"labels": info("nas-omv", "openmediavault", "7", "7.7.24-7", ultimo="8"), "value": 1},
                # PostgreSQL 14 en un contenedor; Prometheus no avisa de versión (aviso_version: false)
                {
                    "labels": info(
                        "srv-1", "postgresql", "14", "14", contenedor="bd", ultimo=_ultimo("postgresql")
                    ),
                    "value": 1,
                },
            ],
        ),
        _muestras(
            ciclos.RESTANTE + '{nombre="srv-1", producto="debian"}',
            [
                {
                    "labels": "vigia_soporte_restante_dias"
                    + info("srv-1", "debian", "12", "12", fuente="sistema"),
                    "value": _dias("debian", "12"),
                }
            ],
        ),
        # Raspberry Pi OS 11 (raspbian): ya sin soporte; el aviso da los días desde el fin
        _muestras(
            exprs["vigia-soporte-caducado"],
            [
                {"labels": info("pi-1", "debian", "11", "11"), "value": -_dias("debian", "11")},
                # OMV 7 (fin el 30-06-2026)
                {
                    "labels": info("nas-omv", "openmediavault", "7", "7.7.24-7"),
                    "value": -_dias("openmediavault", "7"),
                },
            ],
        ),
        # con soporte_dias = 700, Debian 12 (610 días) y PostgreSQL 14; Prometheus 3.15 con su aviso propio
        # (14 días); Debian 13 y Ubuntu 24.04 tienen más margen
        _muestras(
            exprs["vigia-soporte-caduca"],
            [
                {"labels": info("srv-1", "debian", "12", "12"), "value": _dias("debian", "12")},
                {
                    "labels": info("srv-1", "postgresql", "14", "14", contenedor="bd"),
                    "value": _dias("postgresql", "14"),
                },
                {
                    "labels": info("srv-1", "prometheus", "3.15", "3.15", contenedor="prom"),
                    "value": _dias("prometheus", "3.15"),
                },
                # Windows Server 2016: fin el 12-01-2027
                {
                    "labels": info("dc-2", "windows-server", "2016", "10.0.14393"),
                    "value": _dias("windows-server", "2016"),
                },
            ],
        ),
        # una versión que el catálogo no conoce
        _muestras(
            exprs["vigia-ciclo-desconocido"],
            [
                {"labels": info("raro", "debian", "99", "99"), "value": 1},
                # un build de Windows Server que no está en el catálogo: el ciclo es la versión
                {"labels": info("dc-9", "windows-server", "10.0.99999", "10.0.99999"), "value": 1},
            ],
        ),
    ]
    prueba = {
        "rule_files": ["ciclos.yml"],
        "evaluation_interval": f"{HORAS}h",
        "tests": [
            {
                "interval": f"{HORAS}h",
                "input_series": [
                    _serie("srv-1", "debian", "12"),
                    _serie("srv-2", "debian", "13"),
                    _serie("srv-3", "ubuntu", "24.04"),
                    _serie("pi-1", "raspbian", "11"),
                    _serie("raro", "debian", "99"),
                    _serie("mint-1", "linuxmint", "22.1"),
                    _windows("dc-1", "Windows Server 2022 Standard", "10.0.20348"),
                    _windows("dc-2", "Windows Server 2016 Datacenter", "10.0.14393"),
                    _windows("dc-3", "Windows Server 2019 Standard", "10.0.17763"),
                    _windows("dc-9", "Windows Server Datacenter", "10.0.99999"),
                    _windows("pc-1", "Windows 10 Pro", "10.0.19045"),  # puesto: no es Windows Server
                    # OMV 7 que informa el updates-exporter (ya con `nombre` tras el relabel del job)
                    {
                        "series": 'vigia_producto_info{nombre="nas-omv", host="nas-omv", '
                        'producto="openmediavault", version="7.7.24-7", job="actualizaciones"}',
                        "values": "1 1",
                    },
                    _contenedor("bd", "ghcr.io/immich-app/postgres:14-vectorchord0.3.0-pgvectors0.2.0"),
                    _contenedor("prom", "prom/prometheus:v3.15.1"),
                    _contenedor("cache", "redis:8"),  # sin ciclo exacto: no cuenta
                ],
                "promql_expr_test": pruebas,
            }
        ],
    }
    (tmp_path / "prueba.yml").write_text(yaml.safe_dump(prueba, sort_keys=False), encoding="utf-8")
    res = subprocess.run([*cmd, "test", "rules", "prueba.yml"], cwd=tmp_path, capture_output=True, text=True)  # noqa: S603
    assert res.returncode == 0, res.stdout + res.stderr


def test_configuracion_y_reglas_del_golden(tmp_path: Path) -> None:
    """`promtool check config` del Prometheus del ejemplo, reglas incluidas (lint: reglas duplicadas)."""
    cmd = _promtool(tmp_path)
    if not cmd:
        pytest.skip("sin promtool (ver VIGIA_PROMTOOL)")
    golden = Path(__file__).parent / "golden" / "sitio-ejemplo" / "prometheus"
    shutil.copytree(golden, tmp_path / "prometheus")
    conf = tmp_path / "prometheus" / "prometheus.yml"
    # rule_files apunta a /etc/prometheus: aquí, a la copia
    conf.write_text(conf.read_text(encoding="utf-8").replace("/etc/prometheus/", f"{tmp_path}/prometheus/"))
    res = subprocess.run([*cmd, "check", "config", str(conf)], cwd=tmp_path, capture_output=True, text=True)  # noqa: S603
    assert res.returncode == 0, res.stdout + res.stderr


def test_imagenes_descartadas_por_la_politica(tmp_path: Path, example_data: dict[str, Any]) -> None:
    """La alerta de imágenes nuevas no ofrece a quien está en la LTS de Prometheus un tag de rama corta."""
    cmd = _promtool(tmp_path)
    if not cmd:
        pytest.skip("sin promtool (ver VIGIA_PROMTOOL)")
    reglas = ciclos.reglas(ciclos.catalogo())
    (tmp_path / "ciclos.yml").write_text(yaml.safe_dump(reglas), encoding="utf-8")
    politica = ciclos.catalogo()["prometheus"].politica
    assert politica is not None
    (alerta,) = [
        r
        for r in alerting.image_rules(Site.model_validate(example_data))
        if r["uid"] == "vigia-imagen-version"
    ]
    expr = f"({alerta['data'][0]['model']['expr']}) > 0"

    def img(contenedor: str, imagen: str, local: str, remota: str) -> dict[str, str]:
        return {"contenedor": contenedor, "imagen": imagen, "local": local, "remota": remota}

    descartada = img("prom-lts", "prom/prometheus", "v3.13.5", "v3.15.1")  # de la LTS a una rama corta
    # igual, con sufijo
    sufijo = img("prom-sufijo", "prom/prometheus", "v3.13.5-distroless", "v3.15.1-distroless")
    avisan = [
        img("prom-parche", "prom/prometheus", "v3.13.5", "v3.13.6"),  # misma LTS
        img("prom-corta", "prom/prometheus", "v3.14.0", "v3.15.1"),  # la local no es LTS: debe moverse
        img("prom-nueva", "prom/prometheus", "v3.13.5", "v9.9.0"),  # ciclo que el catálogo no conoce
        img("grafana", "grafana/grafana-oss", "13.0.2", "13.3.0"),  # producto sin política
        img("prom-latest", "prom/prometheus", "v3.13.5", "latest"),  # sin ciclo que juzgar: avisa
    ]
    grabadas = [
        {"nombre": "srv-1"}
        | {k: v for k, v in d.items() if k != "imagen"}
        | {"producto": "prometheus", "motivo": politica.motivo}
        for d in (descartada, sufijo)
    ]
    pruebas = [
        _muestras(
            ciclos.DESCARTADA, [{"labels": ciclos.DESCARTADA + _etiquetas(g), "value": 1} for g in grabadas]
        ),
        _muestras(expr, [{"labels": _etiquetas({"nombre": "srv-1"} | m), "value": 1} for m in avisan]),
    ]
    prueba = {
        "rule_files": ["ciclos.yml"],
        "evaluation_interval": f"{HORAS}h",
        "tests": [
            {
                "interval": f"{HORAS}h",
                "input_series": [_wud(**m) for m in [descartada, sufijo, *avisan]],
                "promql_expr_test": pruebas,
            }
        ],
    }
    (tmp_path / "prueba.yml").write_text(yaml.safe_dump(prueba, sort_keys=False), encoding="utf-8")
    res = subprocess.run([*cmd, "test", "rules", "prueba.yml"], cwd=tmp_path, capture_output=True, text=True)  # noqa: S603
    assert res.returncode == 0, res.stdout + res.stderr
