"""metrics.sh del updates-exporter: del updates.json agregado (scripts v1 y v2) a métricas de texto."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "src" / "vigia" / "images" / "updates_exporter" / "metrics.sh"

pytestmark = pytest.mark.skipif(not (shutil.which("sh") and shutil.which("jq")), reason="sin sh o jq")


def _metricas(tmp_path: Path, agregado: dict[str, object]) -> list[str]:
    f = tmp_path / "updates.json"
    f.write_text(json.dumps(agregado), encoding="utf-8")
    res = subprocess.run(["sh", str(SCRIPT), str(f)], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return [line for line in res.stdout.splitlines() if not line.startswith("#")]


def test_v1_v2_dsm_y_caido(tmp_path: Path) -> None:
    lineas = _metricas(
        tmp_path,
        {
            "_checked": "2026-10-29T10:00:00Z",
            "srv-1": {
                "v": 2,
                "updates": 4,
                "security": 1,
                "os_id": "debian",
                "os_version": "13",
                "productos": [{"producto": "openmediavault", "version": "7.7.24-7"}],
            },
            "srv-2": {"updates": 10, "security": 0},
            "nas": {
                "v": 2,
                "dsm_update": 1,
                "productos": [{"producto": "synology-dsm", "version": "7.4-81000"}],
            },
            "caido": {"error": "unreachable"},
        },
    )
    assert lineas == [
        'vigia_updexp_ok{host="srv-1"} 1',
        'vigia_updexp_ok{host="srv-2"} 1',
        'vigia_updexp_ok{host="nas"} 1',
        'vigia_updexp_ok{host="caido"} 0',
        'vigia_updexp_formato{host="srv-1"} 2',
        'vigia_updexp_formato{host="srv-2"} 1',
        'vigia_updexp_formato{host="nas"} 2',
        'vigia_actualizaciones_pendientes{host="srv-1"} 4',
        'vigia_actualizaciones_pendientes{host="srv-2"} 10',
        'vigia_actualizaciones_pendientes{host="nas"} 1',
        'vigia_actualizaciones_seguridad{host="srv-1"} 1',
        'vigia_actualizaciones_seguridad{host="srv-2"} 0',
        'vigia_producto_info{host="srv-1",producto="openmediavault",version="7.7.24-7"} 1',
        'vigia_producto_info{host="nas",producto="synology-dsm",version="7.4-81000"} 1',
    ]


def test_valores_raros_se_escapan_o_se_ignoran(tmp_path: Path) -> None:
    lineas = _metricas(
        tmp_path,
        {
            "srv": {
                "v": 2,
                "updates": "muchas",
                "productos": [{"producto": 'x"y', "version": "1\\2"}, {"producto": "sin-version"}, "basura"],
            },
            "lista": ["no", "es", "objeto"],
            "productos-raro": {"v": 2, "productos": "no es una lista"},
        },
    )
    assert 'vigia_producto_info{host="srv",producto="x\\"y",version="1\\\\2"} 1' in lineas
    assert not [x for x in lineas if "sin-version" in x or "lista" in x or "pendientes" in x]
    assert 'vigia_updexp_ok{host="productos-raro"} 1' in lineas
