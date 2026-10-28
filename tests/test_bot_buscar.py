from __future__ import annotations

from dataclasses import dataclass

from vigia.bot.buscar import buscar, normalizar


@dataclass(frozen=True)
class X:
    nombre: str
    ip: str
    mac: str


ITEMS = [
    X("Impresora Salón", "10.99.0.40", "aa:bb:cc:00:00:01"),
    X("Impresora Despacho", "10.99.0.41", "aa:bb:cc:00:00:02"),
    X("NAS", "10.99.0.20", "aa:bb:cc:00:00:03"),
    X("NAS 2", "10.99.0.21", "aa:bb:cc:00:00:04"),
]


def _claves(x: X) -> tuple[str, str, str]:
    return (x.nombre, x.ip, x.mac)


def test_normalizar() -> None:
    assert normalizar("  Salón ") == "salon"


def test_sin_acentos_ni_mayusculas() -> None:
    assert buscar("impresora salon", ITEMS, _claves) == [ITEMS[0]]


def test_ip_exacta() -> None:
    assert buscar("10.99.0.40", ITEMS, _claves) == [ITEMS[0]]


def test_mac_con_guiones() -> None:
    assert buscar("AA-BB-CC-00-00-03", ITEMS, _claves) == [ITEMS[2]]


def test_exacto_antes_que_contiene() -> None:
    assert buscar("nas", ITEMS, _claves) == [ITEMS[2]]


def test_ambiguo() -> None:
    assert buscar("impresora", ITEMS, _claves) == ITEMS[:2]


def test_vacio_y_sin_resultado() -> None:
    assert buscar("  ", ITEMS, _claves) == []
    assert buscar("tostadora", ITEMS, _claves) == []
