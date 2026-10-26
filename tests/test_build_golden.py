"""Golden test: el sitio de ejemplo genera exactamente lo guardado en tests/golden/.

Para aceptar un cambio intencionado: VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from vigia.build import construir, escribir
from vigia.model import cargar

from .conftest import EJEMPLO

GOLDEN = Path(__file__).parent / "golden" / "sitio-ejemplo"


def _generado() -> dict[str, bytes]:
    s = cargar(EJEMPLO / "site.yaml")
    return {k: v if isinstance(v, bytes) else v.encode() for k, v in construir(s, EJEMPLO).items()}


def test_golden() -> None:
    gen = _generado()
    if os.environ.get("VIGIA_UPDATE_GOLDEN") == "1":
        escribir(dict(gen), GOLDEN)
    esperado = {
        f.relative_to(GOLDEN).as_posix(): f.read_bytes()
        for f in GOLDEN.rglob("*")
        if f.is_file() and f.name != ".vigia-build"
    }
    assert sorted(gen) == sorted(esperado)
    for ruta, datos in gen.items():
        assert datos == esperado[ruta], f"{ruta} difiere del golden"


def test_determinista() -> None:
    assert _generado() == _generado()


def test_sin_secretos_ni_literales_de_otros_sitios() -> None:
    # configuración generada (no el código de las imágenes, que lee sus variables por nombre)
    texto = b"\n".join(v for k, v in _generado().items() if k.endswith((".yml", ".yaml", ".json"))).decode()
    assert not re.search(r"192\.168\.|cuco|sol[0-9]|pimonitor|myNet", texto)
    # las credenciales solo aparecen como referencia ${VAR}
    for var in ("SNMP_NAS_AUTH", "SNMP_NAS_PRIV", "SNMP_COMUNIDAD", "PIHOLE_PASSWORDS"):
        resto = texto.replace(f"{var}=${{{var}}}", "").replace(f"${{{var}}}", "")
        assert var not in resto
