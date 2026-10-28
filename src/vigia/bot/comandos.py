"""Comandos del bot: parseo, despacho y respuestas en HTML de Telegram (todo dato pasa por `esc`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .buscar import buscar
from .config import Config, HostCfg
from .consultas import (
    CARGA,
    CONTENEDORES,
    CPU,
    DISCO_MAX,
    DISCOS,
    GRAFANA_CAIDO,
    PING,
    RAM,
    SERVIDORES,
    TEMP,
    UPTIME,
    WIN_DISCOS,
    Avisos,
    estado_host,
    por,
    serie,
)
from .formato import duracion, esc, hora, pct, recortar
from .fuentes import FuenteError, Grafana, Prometheus

MAX_ARG = 64
MAX_OPCIONES = 8
MAX_ALERTAS_ESTADO = 5

AYUDA: tuple[tuple[str, str, str], ...] = (
    ("estado", "", "servidores y alertas de un vistazo"),
    ("alertas", "", "alertas activas"),
    ("host", "<nombre o IP>", "ficha de un servidor"),
    ("dispositivo", "<nombre, IP o MAC>", "¿está conectado?"),
    ("info", "<nombre, IP o MAC>", "ficha de un dispositivo"),
    ("lista", "[tipo]", "dispositivos encendidos"),
    ("ayuda", "", "esta ayuda"),
)


@dataclass
class Contexto:
    cfg: Config
    prom: Prometheus
    grafana: Grafana
    ahora: Callable[[], float] = field(default=time.time)


Comando = Callable[[Contexto, str], str]


def parsear(texto: str) -> tuple[str, str] | None:
    """`/cmd@bot args` → ("cmd", "args"), con los argumentos acotados a MAX_ARG; None si no es comando."""
    texto = texto.strip()
    if not texto.startswith("/"):
        return None
    cabeza, _, resto = texto.partition(" ")
    return cabeza[1:].split("@", 1)[0].lower(), resto.strip()[:MAX_ARG]


def responder(texto: str, ctx: Contexto) -> str | None:
    p = parsear(texto)
    if p is None:
        return None
    cmd, arg = p
    return COMANDOS.get(cmd, ayuda)(ctx, arg)


def ayuda(ctx: Contexto, arg: str) -> str:
    lineas = ["<b>Comandos</b>"]
    lineas += [esc(f"/{c} {a}".strip() + f" — {d}") for c, a, d in AYUDA]
    return "\n".join(lineas)


def _varios(nombres: Sequence[str]) -> str:
    lista = ", ".join(esc(n) for n in nombres[:MAX_OPCIONES])
    mas = " …" if len(nombres) > MAX_OPCIONES else ""
    return f"Varios coinciden: {lista}{mas}. Afina un poco."


def _disco(v: float | None, umbral: int) -> str:
    return pct(v) + (" ⚠" if v is not None and v >= umbral else "")


def estado(ctx: Contexto, arg: str) -> str:
    av = Avisos()
    up, ping = por(ctx.prom, av, SERVIDORES), por(ctx.prom, av, PING)
    cpu, ram, disco = por(ctx.prom, av, CPU), por(ctx.prom, av, RAM), por(ctx.prom, av, DISCO_MAX)
    lineas = [f"<b>{esc(ctx.cfg.sitio)}</b>"]
    for h in ctx.cfg.hosts:
        n = h.nombre
        linea = f"{estado_host(n, up, ping)} {esc(n)}"
        if n in cpu:
            linea += (
                f" · CPU {pct(cpu[n])} · RAM {pct(ram.get(n))}"
                f" · disco {_disco(disco.get(n), ctx.cfg.disco_pct)}"
            )
        lineas.append(linea)
    try:
        al = ctx.grafana.alertas()
    except FuenteError:
        av.add(GRAFANA_CAIDO)
    else:
        if al:
            txt = ", ".join(
                esc(a.regla) + (f" ({esc(a.objeto)})" if a.objeto else "") for a in al[:MAX_ALERTAS_ESTADO]
            )
            lineas.append(f"Alertas ({len(al)}): {txt}" + (" …" if len(al) > MAX_ALERTAS_ESTADO else ""))
        else:
            lineas.append("Sin alertas")
    return recortar(lineas + av.lineas)


def alertas(ctx: Contexto, arg: str) -> str:
    try:
        al = ctx.grafana.alertas()
    except FuenteError:
        return GRAFANA_CAIDO
    if not al:
        return "Sin alertas"
    now, z = ctx.ahora(), ctx.cfg.zona
    return recortar(
        [
            f"❌ {esc(a.regla)}"
            + (f" · {esc(a.objeto)}" if a.objeto else "")
            + (f" · desde {hora(a.desde, now, z)} ({duracion(now - a.desde)})" if a.desde else " · desde ?")
            for a in al
        ]
    )


def host(ctx: Contexto, arg: str) -> str:
    if not arg:
        return esc("Uso: /host <nombre o IP>")
    hs = buscar(arg, ctx.cfg.hosts, lambda h: (h.id, h.nombre, h.ip))
    if not hs:
        return f"No conozco {esc(arg)}. Hosts: " + ", ".join(esc(h.nombre) for h in ctx.cfg.hosts)
    if len(hs) > 1:
        return _varios([h.nombre for h in hs])
    return _ficha_host(ctx, hs[0])


def _discos(ctx: Contexto, av: Avisos, expr: str, etiqueta: str, nombre: str) -> list[str]:
    filas = sorted(
        (m.get(etiqueta, ""), v) for m, v in serie(ctx.prom, av, expr) if m.get("nombre") == nombre
    )
    return [f"💾 {esc(m)} {_disco(v, ctx.cfg.disco_pct)}" for m, v in filas]


def _ficha_host(ctx: Contexto, h: HostCfg) -> str:
    av, n = Avisos(), h.nombre
    up, ping = por(ctx.prom, av, SERVIDORES), por(ctx.prom, av, PING)
    lineas = [f"{estado_host(n, up, ping)} <b>{esc(n)}</b> · {esc(h.ip)} · {esc(h.tipo)}"]
    cpu = por(ctx.prom, av, CPU)
    if n in cpu:
        ram, carga = por(ctx.prom, av, RAM), por(ctx.prom, av, CARGA)
        temp, upt = por(ctx.prom, av, TEMP), por(ctx.prom, av, UPTIME)
        partes = [f"CPU {pct(cpu[n])}", f"RAM {pct(ram.get(n))}"]
        if n in carga:
            partes.append(f"carga {carga[n]:.2f}")
        if n in temp:
            partes.append(f"{temp[n]:.0f} °C")
        lineas.append(" · ".join(partes))
        if n in upt:
            lineas.append(f"Encendido hace {duracion(upt[n])}")
        lineas += _discos(ctx, av, DISCOS, "mountpoint", n)
    if h.tipo == "windows":
        lineas += _discos(ctx, av, WIN_DISCOS, "volume", n)
    cont = por(ctx.prom, av, CONTENEDORES)
    if n in cont:
        lineas.append(f"Contenedores en marcha: {cont[n]:.0f}")
    return recortar(lineas + av.lineas)


COMANDOS: dict[str, Comando] = {
    "estado": estado,
    "alertas": alertas,
    "host": host,
    "ayuda": ayuda,
    "start": ayuda,
}
