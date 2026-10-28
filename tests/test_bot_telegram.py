from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from vigia.bot.fuentes import FuenteError
from vigia.bot.telegram import Limitador, Telegram, clasificar

from .bot_fakes import AHORA, CHAT


class Grabadora:
    def __init__(self, respuesta: Any) -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[str, Any, float]] = []

    def __call__(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        self.llamadas.append((url, body, timeout))
        return self.respuesta


def test_actualizaciones() -> None:
    g = Grabadora({"ok": True, "result": [{"update_id": 7}]})
    assert Telegram("123:abc", g).actualizaciones(5) == [{"update_id": 7}]
    url, body, timeout = g.llamadas[0]
    assert url == "https://api.telegram.org/bot123:abc/getUpdates"
    assert body == {"timeout": 50, "allowed_updates": ["message"], "offset": 5}
    assert timeout == 60


def test_rechazo() -> None:
    with pytest.raises(FuenteError):
        Telegram("123:abc", Grabadora({"ok": False})).actualizaciones(None)


def test_enviar() -> None:
    g = Grabadora({"ok": True, "result": {}})
    Telegram("123:abc", g).enviar(CHAT, "<b>hola</b>")
    url, body, _ = g.llamadas[0]
    assert url.endswith("/sendMessage")
    assert body["chat_id"] == CHAT and body["parse_mode"] == "HTML" and body["text"] == "<b>hola</b>"


def test_registrar_comandos() -> None:
    g = Grabadora({"ok": True, "result": True})
    Telegram("123:abc", g).registrar_comandos([("estado", "resumen")])
    assert g.llamadas[0][1] == {"commands": [{"command": "estado", "description": "resumen"}]}


def test_repr_sin_token() -> None:
    assert "abc" not in repr(Telegram("123:abc", Grabadora({})))


def _msg(chat: int, date: float = AHORA, text: Any = "/estado") -> dict[str, Any]:
    return {"update_id": 1, "message": {"chat": {"id": chat}, "date": date, "text": text}}


def test_clasificar() -> None:
    desde = AHORA - 120
    assert clasificar(_msg(CHAT), CHAT, desde) == ("atender", "/estado")
    assert clasificar(_msg(42), CHAT, desde) == ("otro_chat", "42")
    assert clasificar(_msg(CHAT, date=AHORA - 600), CHAT, desde) == ("ignorar", "")
    assert clasificar(_msg(CHAT, text=None), CHAT, desde) == ("ignorar", "")
    assert clasificar({"update_id": 2, "edited_message": {}}, CHAT, desde) == ("ignorar", "")


class Reloj:
    def __init__(self) -> None:
        self.t = 0.0
        self.dormidas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.dormidas.append(s)
        self.t += s


def test_limitador_espacia_y_corta() -> None:
    r = Reloj()
    lim = Limitador(reloj=r, dormir=r.dormir)
    assert lim.permitir() and lim.permitir()
    assert r.dormidas == [1.0]
    for _ in range(18):
        assert lim.permitir()
    assert not lim.permitir()  # 20 en el último minuto
    r.t += 60
    assert lim.permitir()
