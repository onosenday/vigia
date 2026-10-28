from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vigia.bot.formato import MAX_CARACTERES, duracion, esc, hora, pct, recortar

Z = "Europe/Madrid"
TZ = ZoneInfo(Z)


def _ts(y: int, mo: int, d: int, h: int, mi: int) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_esc() -> None:
    assert esc("<b>&") == "&lt;b&gt;&amp;"


def test_recortar_lineas() -> None:
    t = recortar([str(i) for i in range(35)])
    assert len(t.splitlines()) == 30
    assert t.splitlines()[-1] == "… y 6 más"


def test_recortar_corto_sin_cambios() -> None:
    assert recortar(["a", "b"]) == "a\nb"


def test_recortar_caracteres_por_una_coma() -> None:
    t = recortar([", ".join(["nombre"] * 1000)])
    assert len(t) <= MAX_CARACTERES
    assert t.endswith("nombre …")


def test_duracion() -> None:
    assert duracion(42) == "42 s"
    assert duracion(23 * 60 + 5) == "23 min"
    assert duracion(3 * 3600 + 5 * 60) == "3 h 5 min"
    assert duracion(2 * 86400 + 3600) == "2 d 1 h"
    assert duracion(-5) == "0 s"


def test_hora() -> None:
    ahora = _ts(2026, 10, 28, 18, 0)
    assert hora(_ts(2026, 10, 28, 14, 5), ahora, Z) == "14:05"
    assert hora(_ts(2026, 10, 27, 23, 10), ahora, Z) == "ayer 23:10"
    assert hora(_ts(2026, 10, 20, 9, 0), ahora, Z) == "20-10 09:00"


def test_pct() -> None:
    assert pct(12.4) == "12%"
    assert pct(None) == "—"


def test_recortar_no_parte_entidades() -> None:
    linea = "a" * (MAX_CARACTERES - 4) + "&amp;" + "b" * 50
    t = recortar([linea])
    assert len(t) <= MAX_CARACTERES
    assert t.endswith(" …")
    assert "&" not in t


def test_recortar_no_deja_etiquetas_abiertas() -> None:
    linea = "a" * (MAX_CARACTERES - 4) + "<b>x</b>" + "b" * 50
    t = recortar([linea])
    assert len(t) <= MAX_CARACTERES
    assert "<" not in t


def test_recortar_multilinea_quita_lineas_enteras() -> None:
    lineas = ["x" * 99 for _ in range(60)]
    t = recortar(lineas, maximo=100)
    assert len(t) <= MAX_CARACTERES
    partes = t.splitlines()
    assert partes[-1].startswith("… y ") and partes[-1].endswith(" más")
    assert all(p == "x" * 99 for p in partes[:-1])
    assert int(partes[-1].split()[2]) == 60 - len(partes) + 1
