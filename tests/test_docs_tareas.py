"""Los envoltorios de bash y PowerShell de docs/tareas.md funcionan de verdad."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DOC = Path(__file__).parent.parent / "docs" / "tareas.md"


def _envoltorio(tmp_path: Path) -> Path:
    texto = DOC.read_text(encoding="utf-8")
    ini = texto.index("#!/usr/bin/env bash")
    fin = texto.index('\nexit "$rc"\n', ini) + len('\nexit "$rc"')
    script = tmp_path / "vigia-tarea.sh"
    script.write_text(texto[ini:fin] + "\n", encoding="utf-8")
    return script


def _valores(f: Path) -> dict[str, str]:
    out = {}
    for linea in f.read_text(encoding="utf-8").splitlines():
        nombre, valor = linea.rsplit(" ", 1)
        out[nombre.split("{")[0]] = valor
    return out


def test_envoltorio_conserva_exito_y_no_deja_temporales(tmp_path: Path) -> None:
    script = _envoltorio(tmp_path)
    textfile = tmp_path / "textfile"
    textfile.mkdir()
    env = {"PATH": "/usr/bin:/bin", "VIGIA_TEXTFILE_DIR": str(textfile)}

    assert subprocess.run(["bash", str(script), "prueba", "true"], env=env).returncode == 0
    bien = _valores(textfile / "prueba.prom")
    assert bien["vigia_tarea_ultimo_resultado"] == "0"
    assert int(bien["vigia_tarea_ultimo_exito_timestamp_seconds"]) > 0

    assert subprocess.run(["bash", str(script), "prueba", "false"], env=env).returncode == 1
    mal = _valores(textfile / "prueba.prom")
    assert mal["vigia_tarea_ultimo_resultado"] == "1"
    assert (
        mal["vigia_tarea_ultimo_exito_timestamp_seconds"]
        == bien["vigia_tarea_ultimo_exito_timestamp_seconds"]
    )

    assert [p.name for p in textfile.iterdir()] == ["prueba.prom"]


def _envoltorio_ps(tmp_path: Path) -> Path:
    texto = DOC.read_text(encoding="utf-8")
    ini = texto.index("# vigia-tarea.ps1.")
    fin = texto.index("\nexit $rc\n", ini) + len("\nexit $rc")
    script = tmp_path / "vigia-tarea.ps1"
    script.write_text(texto[ini:fin] + "\n", encoding="utf-8")
    return script


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="sin PowerShell (pwsh)")
def test_envoltorio_powershell(tmp_path: Path) -> None:
    script = _envoltorio_ps(tmp_path)
    textfile = tmp_path / "textfile"
    textfile.mkdir()
    for nombre, cuerpo in (("bien", "exit 0"), ("mal", "exit 3"), ("lanza", 'throw "fallo"')):
        (tmp_path / f"{nombre}.ps1").write_text(cuerpo + "\n", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin:/snap/bin", "HOME": str(tmp_path), "VIGIA_TEXTFILE_DIR": str(textfile)}

    def tarea(nombre: str, orden: str) -> int:
        cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script), nombre, orden]
        return subprocess.run(cmd, env=env, capture_output=True).returncode

    assert tarea("prueba", str(tmp_path / "bien.ps1")) == 0
    bien = _valores(textfile / "prueba.prom")
    assert bien["vigia_tarea_ultimo_resultado"] == "0"
    assert int(bien["vigia_tarea_ultimo_exito_timestamp_seconds"]) > 0
    assert not (textfile / "prueba.prom").read_bytes().startswith(b"\xef\xbb\xbf")  # sin BOM

    for orden, rc in (("mal.ps1", 3), ("lanza.ps1", 1)):
        assert tarea("prueba", str(tmp_path / orden)) == rc
        mal = _valores(textfile / "prueba.prom")
        assert mal["vigia_tarea_ultimo_resultado"] == "1"
        assert (
            mal["vigia_tarea_ultimo_exito_timestamp_seconds"]
            == bien["vigia_tarea_ultimo_exito_timestamp_seconds"]
        )

    assert tarea("nueva", str(tmp_path / "mal.ps1")) == 3
    assert _valores(textfile / "nueva.prom") == {"vigia_tarea_ultimo_resultado": "1"}
    assert sorted(p.name for p in textfile.iterdir()) == ["nueva.prom", "prueba.prom"]
