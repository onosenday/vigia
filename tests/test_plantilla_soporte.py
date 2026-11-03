"""Las imágenes que fija la plantilla de sitio no caducan pronto (vigia-b9h): un tag las despliega."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from vigia.ciclos import catalogo
from vigia.model import load_site
from vigia.newsite import NewSite, create

from .test_newsite import BASE

UMBRAL_POR_DEFECTO = 90  # alertas.umbrales.soporte_dias


def test_imagenes_de_la_plantilla_con_soporte(tmp_path: Path) -> None:
    create(NewSite(**BASE), tmp_path)
    s = load_site(tmp_path / "site.yaml")
    fijadas = yaml.safe_load((tmp_path / "site.yaml").read_text(encoding="utf-8"))["monitor"]["imagenes"]
    assert fijadas, "la plantilla no fija imágenes"
    hoy = date.today()
    malas = []
    for nombre in fijadas:
        imagen = s.monitor.image(nombre)
        for p in catalogo().values():
            ciclo = p.ciclo_de_imagen(imagen)
            if ciclo is None:
                continue
            c = next(c for c in p.ciclos if c.ciclo == ciclo)
            fin = c.fin(p.fecha_aviso)
            dias = p.aviso_dias or UMBRAL_POR_DEFECTO
            if fin is not None and fin < hoy + timedelta(days=dias):
                malas.append(f"{imagen}: {p.nombre} {ciclo} pierde el soporte el {fin} (aviso: {dias} días)")
    assert not malas, "sube estas imágenes en site.yaml.j2 antes de publicar:\n" + "\n".join(malas)
