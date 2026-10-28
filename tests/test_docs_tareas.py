"""El envoltorio de bash de docs/tareas.md funciona de verdad."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
