"""Golden test: el sitio de ejemplo genera exactamente lo guardado en tests/golden/.

Para aceptar un cambio intencionado: VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from vigia.build import build_site, write_build
from vigia.model import load_site

from .conftest import EXAMPLE

GOLDEN = Path(__file__).parent / "golden" / "sitio-ejemplo"


def _generated() -> dict[str, bytes]:
    s = load_site(EXAMPLE / "site.yaml")
    return {k: v if isinstance(v, bytes) else v.encode() for k, v in build_site(s, EXAMPLE).items()}


def test_golden() -> None:
    gen = _generated()
    if os.environ.get("VIGIA_UPDATE_GOLDEN") == "1":
        write_build(dict(gen), GOLDEN)
    expected = {
        f.relative_to(GOLDEN).as_posix(): f.read_bytes()
        for f in GOLDEN.rglob("*")
        if f.is_file() and f.name != ".vigia-build"
    }
    assert sorted(gen) == sorted(expected)
    for path, data in gen.items():
        assert data == expected[path], f"{path} difiere del golden"


def test_deterministic() -> None:
    assert _generated() == _generated()


def test_no_secrets_or_other_site_literals() -> None:
    # configuración generada (no el código de las imágenes, que lee sus variables por nombre)
    text = b"\n".join(v for k, v in _generated().items() if k.endswith((".yml", ".yaml", ".json"))).decode()
    assert not re.search(r"192\.168\.|cuco|sol[0-9]|pimonitor|myNet", text)
    # las credenciales solo aparecen como referencia ${VAR}
    for var in ("SNMP_NAS_AUTH", "SNMP_NAS_PRIV", "SNMP_COMUNIDAD", "PIHOLE_PASSWORDS"):
        rest = text.replace(f"{var}=${{{var}}}", "").replace(f"${{{var}}}", "")
        assert var not in rest
