"""Skill vigia-actualizar: novedades del CHANGELOG y clasificación del riesgo de las diferencias."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from vigia.newsite import install_skill

SCRIPT = Path(__file__).parents[1] / "src/vigia/claude/skills/vigia-actualizar/comprobar.py"


@pytest.fixture(scope="module")
def comp() -> ModuleType:
    spec = importlib.util.spec_from_file_location("comprobar", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["comprobar"] = mod  # las dataclasses lo buscan ahí
    spec.loader.exec_module(mod)
    return mod


CHANGELOG = """# Cambios

## 0.4.1 (2027-01-02)

- arreglo

## 0.4.0 (2027-01-01)

- novedad

## 0.3.0 (2026-10-28)

- ya instalada
"""


def test_novedades_entre_versiones(comp: ModuleType) -> None:
    txt = comp.novedades(CHANGELOG, (0, 3, 0), (0, 4, 0))
    assert "novedad" in txt and "arreglo" not in txt and "ya instalada" not in txt
    assert comp.rango((0, 4, 0)) == ">=0.4,<0.5"
    with pytest.raises(ValueError, match="versión no válida"):
        comp.version_tuple("latest")


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return root


COMPOSE = """# Monitor — generado por vigia {v} para «Ejemplo».
services:
  prometheus:
    image: prom/prometheus:{prom}
    command: ["--storage.tsdb.retention.time={ret}"]
    volumes: ["./prometheus:/etc/prometheus"]
  blackbox:
    image: prom/blackbox-exporter:{bb}
"""


def _dash(uid: str, title: str = "Panel") -> str:
    return json.dumps({"uid": uid, "title": title, "panels": []})


def _riesgos(hallazgos: list[Any]) -> dict[str, str]:
    return {f"{h.fichero}:{h.motivo.split(':')[0]}": h.riesgo for h in hallazgos}


def test_solo_cambia_la_cabecera_no_es_un_cambio(tmp_path: Path, comp: ModuleType) -> None:
    c = {"prom": "v3.0.0", "ret": "90d", "bb": "v0.29.1"}
    old = _tree(
        tmp_path / "a", {"monitor.yml": COMPOSE.format(v="0.3.0", **c), "dashboards/x.json": _dash("x")}
    )
    new = _tree(
        tmp_path / "b", {"monitor.yml": COMPOSE.format(v="0.4.0", **c), "dashboards/x.json": _dash("x")}
    )
    assert comp.clasificar(old, new) == []


def test_clasifica_por_riesgo(tmp_path: Path, comp: ModuleType) -> None:
    old = _tree(
        tmp_path / "a",
        {
            "monitor.yml": COMPOSE.format(v="0.3.0", prom="v3.0.0", ret="90d", bb="v0.29.1"),
            "dashboards/se-va.json": _dash("se-va"),
            "dashboards/uid.json": _dash("viejo"),
            "dashboards/cambia.json": _dash("c", "Antes"),
            "grafana-provisioning/alerting/vigia.yml": "groups: []\n",
        },
    )
    new = _tree(
        tmp_path / "b",
        {
            "monitor.yml": COMPOSE.format(v="0.4.0", prom="v3.1.0", ret="365d", bb="v0.30.0"),
            "dashboards/uid.json": _dash("nuevo"),
            "dashboards/cambia.json": _dash("c", "Después"),
            "dashboards/nuevo.json": _dash("n"),
            "grafana-provisioning/alerting/vigia.yml": "groups: [{name: x}]\n",
        },
    )
    r = comp.clasificar(old, new)
    by = {(h.fichero, h.riesgo) for h in r}
    assert ("dashboards/se-va.json", "ALTO") in by  # panel retirado
    assert ("dashboards/uid.json", "ALTO") in by  # uid cambiado
    assert ("dashboards/cambia.json", "BAJO") in by
    assert ("dashboards/nuevo.json", "BAJO") in by
    assert ("grafana-provisioning/alerting/vigia.yml", "MEDIO") in by
    motivos = [h.motivo for h in r if h.fichero == "monitor.yml"]
    assert any("prometheus: imagen" in m for m in motivos)  # guarda datos → ALTO
    assert any("almacenamiento" in m for m in motivos)
    assert any("blackbox: imagen" in m for m in motivos)
    riesgo = {
        h.motivo.split(":")[0] + h.motivo.split(":")[1][:7]: h.riesgo for h in r if h.fichero == "monitor.yml"
    }
    assert riesgo["prometheus imagen"] == "ALTO" and riesgo["blackbox imagen"] == "MEDIO"


def test_skill_instala_las_dos_skills(tmp_path: Path) -> None:
    written = {str(p.relative_to(tmp_path)) for p in install_skill(tmp_path)}
    assert {
        ".claude/skills/vigia/SKILL.md",
        ".claude/skills/vigia-actualizar/SKILL.md",
        ".claude/skills/vigia-actualizar/comprobar.py",
    } <= written
