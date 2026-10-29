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


LITERALES = Path(__file__).parents[1] / ".literales-prohibidos"
"""Fichero local (fuera de git) con una expresión regular de nombres de los sitios reales que no deben
aparecer en lo generado; también por la variable VIGIA_LITERALES_PROHIBIDOS."""


def _prohibidos() -> str:
    extra = os.environ.get("VIGIA_LITERALES_PROHIBIDOS", "")
    if not extra and LITERALES.exists():
        extra = LITERALES.read_text(encoding="utf-8").strip()
    return r"192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\." + (f"|{extra}" if extra else "")


def test_no_secrets_or_other_site_literals() -> None:
    # configuración generada (no el código de las imágenes, que lee sus variables por nombre)
    text = b"\n".join(v for k, v in _generated().items() if k.endswith((".yml", ".yaml", ".json"))).decode()
    assert not re.search(_prohibidos(), text)
    # las credenciales solo aparecen como referencia ${VAR}
    for var in ("SNMP_NAS_AUTH", "SNMP_NAS_PRIV", "SNMP_COMUNIDAD", "PIHOLE_PASSWORDS"):
        rest = text.replace(f"{var}=${{{var}}}", "").replace(f"${{{var}}}", "")
        assert var not in rest


def test_modulo_snmp_de_impresoras_valido() -> None:
    import yaml

    gen = _generated()
    mods = yaml.safe_load(gen["snmp/vigia-modulos.yml"])["modules"]
    err = mods["vigia_impresora"]["metrics"][0]
    assert (
        err["type"] == "Bits"
        and err["enum_values"][1] == "noPaper"
        and err["enum_values"][13] == "inputTrayEmpty"
    )
    assert b"--config.file=/etc/snmp_exporter/auths/vigia-modulos.yml" in gen["ejemplo_monitor.yml"]


def test_snmp_protocolos_v3() -> None:
    import yaml

    auths = yaml.safe_load(_generated()["snmp/auths.yml"])["auths"]
    assert (auths["nas"]["auth_protocol"], auths["nas"]["priv_protocol"]) == ("SHA256", "AES")
    assert (auths["nas-sha1"]["auth_protocol"], auths["nas-sha1"]["priv_protocol"]) == ("SHA", "AES256")
    assert "context_name" not in auths["nas"]
    assert auths["jetdirect"]["context_name"] == "Jetdirect"
