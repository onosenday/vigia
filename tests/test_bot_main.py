from __future__ import annotations

import itertools
import urllib.error
import urllib.request
from typing import Any

import pytest

from vigia.bot import __main__ as bot_main
from vigia.bot.__main__ import AVISO_LIMITE, ERROR_INTERNO, Bucle, Salud, servir_salud
from vigia.bot.comandos import Contexto, responder
from vigia.bot.fuentes import FuenteError, http_json
from vigia.bot.telegram import Limitador, Telegram

from .bot_fakes import AHORA, CHAT, cfg, contexto


class FakeTg:
    def __init__(self, lotes: list[list[dict[str, Any]] | Exception]) -> None:
        self.lotes = lotes
        self.offsets: list[int | None] = []
        self.enviados: list[tuple[int, str]] = []

    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        lote = self.lotes.pop(0)
        if isinstance(lote, Exception):
            raise lote
        return lote

    def enviar(self, chat_id: int, texto: str) -> None:
        self.enviados.append((chat_id, texto))


def _msg(uid: int, chat: int = CHAT, text: str = "/ayuda") -> dict[str, Any]:
    return {"update_id": uid, "message": {"chat": {"id": chat}, "date": AHORA, "text": text}}


def _bucle(tg: FakeTg, dormidas: list[float] | None = None, **kw: Any) -> tuple[Bucle, Salud]:
    c, salud = contexto(), Salud(AHORA)
    sin_espera = Limitador(reloj=itertools.count(0.0, 2.0).__next__)
    destino = dormidas if dormidas is not None else []
    b = Bucle(c.cfg, tg, c, salud, sin_espera, reloj=lambda: AHORA, dormir=destino.append, **kw)
    return b, salud


def test_atiende_el_chat_y_avanza_el_offset() -> None:
    tg = FakeTg([[_msg(10)], []])
    b, salud = _bucle(tg)
    b.paso()
    b.paso()
    assert tg.enviados[0][0] == CHAT and tg.enviados[0][1].startswith("<b>Comandos</b>")
    assert tg.offsets == [None, 11]
    assert 'vigia_bot_mensajes_total{resultado="atendido"} 1' in salud.texto()


def test_descarta_otro_chat() -> None:
    tg = FakeTg([[_msg(10, chat=42)]])
    b, salud = _bucle(tg)
    b.paso()
    assert tg.enviados == []
    assert 'vigia_bot_mensajes_total{resultado="descartado"} 1' in salud.texto()


def test_reintenta_con_espera_creciente() -> None:
    tg = FakeTg([FuenteError("HTTP 502"), FuenteError("URLError"), [_msg(1)], FuenteError("URLError")])
    dormidas: list[float] = []
    b, _ = _bucle(tg, dormidas)
    for _ in range(4):
        b.paso()
    assert dormidas == [1.0, 2.0, 1.0]
    assert len(tg.enviados) == 1


def test_error_interno_no_tumba_el_bucle() -> None:
    def roto(texto: str, ctx: Contexto) -> str | None:
        raise RuntimeError("fallo")

    tg = FakeTg([[_msg(1)]])
    b, salud = _bucle(tg, responder=roto)
    b.paso()
    assert tg.enviados == [(CHAT, ERROR_INTERNO)]
    assert 'vigia_bot_mensajes_total{resultado="error"} 1' in salud.texto()


def test_responder_por_defecto() -> None:
    b, _ = _bucle(FakeTg([]))
    assert b.responder is responder


def test_metrics_http() -> None:
    srv = servir_salud(Salud(AHORA), 0)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/metrics"
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310
            assert "vigia_bot_up 1" in r.read().decode()
    finally:
        srv.shutdown()
        srv.server_close()


def test_ruta_desconocida_404() -> None:
    srv = servir_salud(Salud(AHORA), 0)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/otra"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=5)  # noqa: S310
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_update_sin_id_valido_se_salta() -> None:
    sin_id = {"message": {"chat": {"id": CHAT}, "date": AHORA, "text": "/ayuda"}}
    tg = FakeTg([[sin_id, _msg("x"), _msg(4)]])  # type: ignore[arg-type]
    b, _ = _bucle(tg)
    b.paso()
    assert b.offset == 5
    assert len(tg.enviados) == 1


def test_offset_no_retrocede() -> None:
    tg = FakeTg([[_msg(10), _msg(3, text="otro")]])
    b, _ = _bucle(tg)
    b.paso()
    assert b.offset == 11


def test_excepcion_inesperada_en_actualizaciones() -> None:
    tg = FakeTg([RuntimeError("raro"), [_msg(1)]])
    dormidas: list[float] = []
    b, _ = _bucle(tg, dormidas)
    b.paso()
    b.paso()
    assert dormidas == [1.0]
    assert len(tg.enviados) == 1


def test_excepcion_inesperada_al_procesar_avanza_offset() -> None:
    class Rota(FakeTg):
        def enviar(self, chat_id: int, texto: str) -> None:
            raise RuntimeError("raro")

    tg = Rota([[_msg(7)]])
    dormidas: list[float] = []
    b, _ = _bucle(tg, dormidas)
    b.paso()
    assert b.offset == 8
    assert dormidas == [1.0]
    assert b.espera == 2.0


def test_limitado_avisa_una_vez_por_racha() -> None:
    tg = FakeTg([[_msg(1), _msg(2), _msg(3)]])
    c, salud = contexto(), Salud(AHORA)
    lim = Limitador(por_minuto=1, reloj=itertools.count(0.0, 2.0).__next__)
    b = Bucle(c.cfg, tg, c, salud, lim, reloj=lambda: AHORA, dormir=lambda s: None)
    b.paso()
    assert [txt for _, txt in tg.enviados][1:] == [AVISO_LIMITE]  # la respuesta y un solo aviso
    assert 'vigia_bot_mensajes_total{resultado="limitado"} 2' in salud.texto()


def test_enviar_con_fuenteerror_no_rompe() -> None:
    class Falla(FakeTg):
        def enviar(self, chat_id: int, texto: str) -> None:
            raise FuenteError("HTTP 500")

    b, salud = _bucle(Falla([[_msg(1)]]))
    b.paso()
    assert b.offset == 2
    assert 'vigia_bot_mensajes_total{resultado="fallo_envio"} 1' in salud.texto()
    assert 'vigia_bot_mensajes_total{resultado="atendido"} 0' in salud.texto()


def test_ultimo_contacto_con_telegram() -> None:
    tg = FakeTg([FuenteError("HTTP 502"), []])
    b, salud = _bucle(tg)
    b.reloj = lambda: AHORA + 300
    b.paso()  # falla: el último contacto sigue siendo el arranque
    assert f"vigia_bot_telegram_ultimo_ok_timestamp_seconds {AHORA:.0f}" in salud.texto()
    b.paso()
    assert f"vigia_bot_telegram_ultimo_ok_timestamp_seconds {AHORA + 300:.0f}" in salud.texto()


def test_cuenta_ignorados_y_sin_respuesta() -> None:
    sin_texto = {"update_id": 2, "message": {"chat": {"id": CHAT}, "date": AHORA}}
    tg = FakeTg([[_msg(1, text="hola"), sin_texto]])
    b, salud = _bucle(tg)
    b.paso()
    assert tg.enviados == []
    assert 'vigia_bot_mensajes_total{resultado="sin_respuesta"} 1' in salud.texto()
    assert 'vigia_bot_mensajes_total{resultado="ignorado"} 1' in salud.texto()


TOKEN = cfg().telegram_token


def test_el_token_no_sale_en_errores_de_red() -> None:
    # nada escucha en el puerto 9: la URL (con el token) no debe aparecer en el error
    with pytest.raises(FuenteError) as e:
        http_json(f"http://127.0.0.1:9/bot{TOKEN}/getUpdates", body={}, timeout=2)
    assert TOKEN not in str(e.value) and TOKEN not in repr(e.value)


def test_el_token_no_sale_en_el_log(capsys: pytest.CaptureFixture[str]) -> None:
    def http(url: str, **kw: Any) -> Any:
        raise RuntimeError(f"fallo en {url}")  # una excepción que sí lleva la URL

    c = contexto()
    b = Bucle(c.cfg, Telegram(TOKEN, http), c, Salud(AHORA), Limitador(), dormir=lambda s: None)
    b.paso()
    salida = capsys.readouterr().out
    assert "RuntimeError" in salida and TOKEN not in salida


class _Fin(Exception):
    pass


def _main(monkeypatch: pytest.MonkeyPatch, tg: Any) -> list[str]:
    c = contexto()
    lineas: list[str] = []
    monkeypatch.setattr(bot_main, "load", lambda *a: c.cfg)
    monkeypatch.setattr(bot_main, "Telegram", lambda *a: tg)
    monkeypatch.setattr(bot_main, "servir_salud", lambda *a: None)
    monkeypatch.setattr(bot_main, "log", lambda *a: lineas.append(" ".join(map(str, a))))

    def paso(self: Bucle) -> None:
        raise _Fin

    monkeypatch.setattr(Bucle, "paso", paso)
    with pytest.raises(_Fin):
        bot_main.main()
    return lineas


def test_main_registra_comandos_y_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    class Tg(FakeTg):
        registrados: list[str] = []

        def registrar_comandos(self, chat_id: int, comandos: Any) -> None:
            self.registrados = [c for c, _ in comandos]

    tg = Tg([])
    lineas = _main(monkeypatch, tg)
    assert "ayuda" in tg.registrados
    assert any(x.startswith("bot en marcha: Ejemplo") for x in lineas)


def test_main_sigue_si_falla_registrar_comandos(monkeypatch: pytest.MonkeyPatch) -> None:
    class Tg(FakeTg):
        def registrar_comandos(self, chat_id: int, comandos: Any) -> None:
            raise FuenteError("setMyCommands rechazado")

    lineas = _main(monkeypatch, Tg([]))
    assert lineas[0] == "setMyCommands: setMyCommands rechazado"
    assert any(x.startswith("bot en marcha") for x in lineas)
