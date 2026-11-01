"""Scripts de host del updates-exporter: lo que ejecutan con sudo es lo que su línea de sudoers permite.

En sudoers, una orden con argumentos solo permite exactamente esos argumentos; sin argumentos, cualquiera.
Un argumento de más (`apt-get update -qq` con `NOPASSWD: /usr/bin/apt-get update`) hace que sudo lo rechace.
"""

from __future__ import annotations

import re
import shlex
from importlib.resources import files
from pathlib import Path

import pytest

SCRIPTS = Path(str(files("vigia") / "images" / "updates_exporter" / "host-scripts"))
DOC = Path(__file__).parent.parent / "docs" / "actualizaciones.md"


def _permitido(script: Path) -> list[str]:
    """La orden de la línea `NOPASSWD:` de la cabecera del script."""
    m = re.search(r"^#.*NOPASSWD: (.+)$", script.read_text(encoding="utf-8"), re.M)
    assert m, f"{script.name}: sin línea de sudoers en la cabecera"
    return shlex.split(m.group(1))


def _llamadas(script: Path) -> list[list[str]]:
    """Cada `sudo …` del código (no de los comentarios), hasta la primera redirección o tubería."""
    out = []
    for linea in script.read_text(encoding="utf-8").splitlines():
        if linea.lstrip().startswith("#"):
            continue
        for m in re.finditer(r"\bsudo ([^>|&;)]+)", linea):
            out.append(shlex.split(m.group(1)))
    return out


@pytest.mark.parametrize("script", sorted(SCRIPTS.glob("*.sh")), ids=lambda p: p.name)
def test_sudo_casa_con_sudoers(script: Path) -> None:
    permitido = _permitido(script)
    llamadas = _llamadas(script)
    assert llamadas, f"{script.name}: no llama a sudo"
    for llamada in llamadas:
        assert llamada[0] == "-n", f"{script.name}: sudo sin -n esperaría una contraseña: {llamada}"
        orden = llamada[1:]
        assert Path(orden[0]).name == Path(permitido[0]).name, (script.name, orden)
        if len(permitido) > 1:  # con argumentos en sudoers, han de coincidir exactamente
            assert orden == permitido, (script.name, orden)


def test_la_guia_da_la_misma_linea_de_sudoers() -> None:
    texto = DOC.read_text(encoding="utf-8")
    apt = _permitido(SCRIPTS / "apt-updates-json.sh")
    assert f"NOPASSWD: {shlex.join(apt)}'" in texto
