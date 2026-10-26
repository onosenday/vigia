from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "sitio-ejemplo"


@pytest.fixture
def example_data() -> dict[str, Any]:
    """site.yaml del ejemplo como dict, para mutarlo en cada test."""
    return copy.deepcopy(yaml.safe_load((EXAMPLE / "site.yaml").read_text(encoding="utf-8")))
