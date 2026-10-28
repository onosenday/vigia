"""Arranque del bot (`python -m vigia_bot` en su contenedor): /metrics, comandos de Telegram y bucle."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import comandos
from .comandos import AYUDA, Contexto
from .config import Config, load
from .fuentes import FuenteError, Grafana, Prometheus, http_json
from .telegram import Limitador, Mensajeria, Telegram, clasificar

CONFIG = Path("/etc/vigia-bot/config.json")
ANTIGUEDAD = 120
"""Al arrancar se ignoran los mensajes de más de 2 min: no se contesta a destiempo."""
ESPERA_MAX = 60.0
ERROR_INTERNO = "⚠ Error interno; mira el log del bot"


def log(*partes: object) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *partes, flush=True)


class Salud:
    RESULTADOS = ("atendido", "descartado", "limitado", "error")

    def __init__(self) -> None:
        self._n = dict.fromkeys(self.RESULTADOS, 0)
        self._lock = threading.Lock()

    def contar(self, resultado: str) -> None:
        with self._lock:
            self._n[resultado] += 1

    def texto(self) -> str:
        with self._lock:
            n = dict(self._n)
        lineas = [
            "# HELP vigia_bot_up El bot está en marcha.",
            "# TYPE vigia_bot_up gauge",
            "vigia_bot_up 1",
            "# HELP vigia_bot_mensajes_total Mensajes recibidos por resultado.",
            "# TYPE vigia_bot_mensajes_total counter",
        ]
        lineas += [f'vigia_bot_mensajes_total{{resultado="{r}"}} {v}' for r, v in n.items()]
        return "\n".join(lineas) + "\n"


def servir_salud(salud: Salud, puerto: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # nombre fijado por http.server
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            body = salud.texto().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    # todas las interfaces del contenedor: solo la red interna del stack, sin puerto publicado
    srv = ThreadingHTTPServer(("", puerto), Handler)  # noqa: S104
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Bucle:
    def __init__(
        self,
        cfg: Config,
        tg: Mensajeria,
        ctx: Contexto,
        salud: Salud,
        limitador: Limitador,
        responder: Callable[[str, Contexto], str | None] = comandos.responder,
        reloj: Callable[[], float] = time.time,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg, self.tg, self.ctx, self.salud, self.limitador = cfg, tg, ctx, salud, limitador
        self.responder, self.dormir = responder, dormir
        self.offset: int | None = None
        self.desde = reloj() - ANTIGUEDAD
        self.espera = 1.0

    def _fallo(self, e: Exception) -> None:
        detalle = e if isinstance(e, FuenteError) else type(e).__name__
        log("telegram:", detalle, f"(reintento en {self.espera:.0f} s)")
        self.dormir(self.espera)
        self.espera = min(self.espera * 2, ESPERA_MAX)

    def paso(self) -> None:
        try:
            updates = self.tg.actualizaciones(self.offset)
        except Exception as e:  # nada debe tumbar el bucle
            self._fallo(e)
            return
        self.espera = 1.0
        for u in updates:
            uid = u.get("update_id")
            if not isinstance(uid, int) or isinstance(uid, bool):
                continue
            self.offset = max(self.offset or 0, uid + 1)  # consumido aunque falle el procesado
            try:
                tipo, valor = clasificar(u, self.cfg.chat_id, self.desde)
                if tipo == "otro_chat":
                    self.salud.contar("descartado")
                    log("descartado un mensaje del chat", valor)
                elif tipo == "atender":
                    self._atender(valor)
            except Exception as e:  # un update raro no puede parar el bot
                self._fallo(e)

    def _atender(self, texto: str) -> None:
        try:
            respuesta = self.responder(texto, self.ctx)
        except Exception as e:  # un comando roto no puede parar el bot
            log("error en el comando:", type(e).__name__)
            self.salud.contar("error")
            respuesta = ERROR_INTERNO
        if respuesta is None:
            return
        if not self.limitador.permitir():
            self.salud.contar("limitado")
            return
        try:
            self.tg.enviar(self.cfg.chat_id, respuesta)
            if respuesta != ERROR_INTERNO:
                self.salud.contar("atendido")
        except FuenteError as e:
            log("telegram:", e)


def main() -> None:
    cfg = load(CONFIG, os.environ)
    tg = Telegram(cfg.telegram_token, http_json)
    prom = Prometheus(cfg.prometheus, http_json)
    ctx = Contexto(cfg, prom, Grafana(cfg.grafana, cfg.grafana_token, http_json))
    salud = Salud()
    servir_salud(salud, cfg.puerto)
    try:
        tg.registrar_comandos((c, d) for c, _, d in AYUDA)
    except FuenteError as e:
        log("setMyCommands:", e)
    log("bot en marcha:", cfg.sitio, "·", len(cfg.hosts), "hosts")
    bucle = Bucle(cfg, tg, ctx, salud, Limitador())
    while True:
        bucle.paso()


if __name__ == "__main__":
    main()
