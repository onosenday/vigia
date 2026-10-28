"""API de bots de Telegram: long polling, envío, filtro del chat autorizado y límite de respuestas."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from .fuentes import FuenteError, Http

API = "https://api.telegram.org"
ESPERA = 50
"""Segundos que Telegram retiene getUpdates si no hay mensajes."""


class Mensajeria(Protocol):
    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]: ...

    def enviar(self, chat_id: int, texto: str) -> None: ...


class Telegram:
    def __init__(self, token: str, http: Http, api: str = API) -> None:
        self._token = token
        self.http = http
        self.api = api

    def __repr__(self) -> str:
        return "Telegram(<token oculto>)"

    def _llamar(self, metodo: str, body: dict[str, Any], timeout: float = 10.0) -> Any:
        d = self.http(f"{self.api}/bot{self._token}/{metodo}", body=body, timeout=timeout)
        if not isinstance(d, dict) or not d.get("ok"):
            raise FuenteError(f"{metodo} rechazado")
        return d.get("result")

    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"timeout": ESPERA, "allowed_updates": ["message"]}
        if offset is not None:
            body["offset"] = offset
        r = self._llamar("getUpdates", body, timeout=ESPERA + 10)
        return [u for u in r if isinstance(u, dict)] if isinstance(r, list) else []

    def enviar(self, chat_id: int, texto: str) -> None:
        self._llamar(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": texto,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )

    def registrar_comandos(self, comandos: Iterable[tuple[str, str]]) -> None:
        self._llamar("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in comandos]})


def clasificar(update: dict[str, Any], chat_id: int, desde: float) -> tuple[str, str]:
    """("atender", texto), ("otro_chat", id del chat) o ("ignorar", "")."""
    m = update.get("message")
    if not isinstance(m, dict):
        return "ignorar", ""
    chat = m.get("chat")
    cid = chat.get("id") if isinstance(chat, dict) else None
    if cid != chat_id:
        return "otro_chat", str(cid)
    texto = m.get("text")
    fecha = m.get("date", 0)
    fecha_ok = isinstance(fecha, int | float) and not isinstance(fecha, bool)
    if not isinstance(texto, str) or not fecha_ok or fecha < desde:
        return "ignorar", ""
    return "atender", texto


class Limitador:
    """Como mucho `por_minuto` respuestas por minuto y una cada `intervalo` segundos (si no, espera)."""

    def __init__(
        self,
        por_minuto: int = 20,
        intervalo: float = 1.0,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.por_minuto = por_minuto
        self.intervalo = intervalo
        self.reloj = reloj
        self.dormir = dormir
        self._envios: deque[float] = deque()

    def permitir(self) -> bool:
        now = self.reloj()
        while self._envios and now - self._envios[0] >= 60:
            self._envios.popleft()
        if len(self._envios) >= self.por_minuto:
            return False
        if self._envios and now - self._envios[-1] < self.intervalo:
            self.dormir(self.intervalo - (now - self._envios[-1]))
            now = self.reloj()
        self._envios.append(now)
        return True
