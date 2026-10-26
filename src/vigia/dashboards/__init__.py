"""Paneles de Grafana generados a partir del sitio (fase F2)."""

from __future__ import annotations

from pathlib import Path

from vigia.model import Site


def paneles(s: Site, raiz_sitio: Path) -> dict[str, str]:
    """{nombre de fichero: JSON} de los paneles del sitio."""
    return {}
