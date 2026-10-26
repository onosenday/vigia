from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "examples" / "sitio-ejemplo"


@pytest.fixture
def datos_ejemplo() -> dict[str, Any]:
    """site.yaml del ejemplo como dict, para mutarlo en cada test."""
    return copy.deepcopy(yaml.safe_load((EJEMPLO / "site.yaml").read_text(encoding="utf-8")))
