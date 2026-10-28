"""Comandos del bot: parseo, despacho y respuestas en HTML de Telegram (todo dato pasa por `esc`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .buscar import buscar, normalizar
from .config import Config, HostCfg
from .consultas import (
    CARGA,
    CONTENEDORES,
    CPU,
    DISCO_MAX,
    DISCOS,
    GRAFANA_CAIDO,
    PING,
    PROM_CAIDO,
    RAM,
    SERVIDORES,
    TEMP,
    UPTIME,
    WIN_DISCOS,
    Avisos,
    Dispositivo,
    dispositivos,
    estado_host,
    por,
    serie,
)
from .formato import duracion, esc, hora, pct, recortar
from .fuentes import FuenteError, Grafana, Prometheus

MAX_ARG = 64
MAX_OPCIONES = 8
MAX_ALERTAS_ESTADO = 5
SIN_NETINV = "Este sitio no tiene netinv: no hay inventario de dispositivos."
SIN_TIPO = "sin clasificar"

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


def _un_dispositivo(ctx: Contexto, arg: str, uso: str) -> Dispositivo | str:
    """El dispositivo que busca `arg` o el texto de respuesta si no hay uno solo."""
    if not ctx.cfg.netinv:
        return SIN_NETINV
    if not arg:
        return esc(uso)
    try:
        ds = dispositivos(ctx.prom)
    except FuenteError:
        return PROM_CAIDO
    r = buscar(arg, ds, lambda d: (d.nombre, d.ip, d.mac))
    if not r:
        return f"No conozco {esc(arg)}. Prueba /lista"
    if len(r) > 1:
        return _varios([d.nombre for d in r])
    return r[0]


def dispositivo(ctx: Contexto, arg: str) -> str:
    d = _un_dispositivo(ctx, arg, "Uso: /dispositivo <nombre, IP o MAC>")
    if isinstance(d, str):
        return d
    now = ctx.ahora()
    if d.encendido and not d.ultima:
        return f"🟢 {esc(d.nombre)} · {esc(d.ip)} · conectado"
    if d.encendido:
        return f"🟢 {esc(d.nombre)} · {esc(d.ip)} · visto hace {duracion(now - d.ultima)}"
    cuando = hora(d.ultima, now, ctx.cfg.zona) if d.ultima else "desconocida"
    return f"⚪ {esc(d.nombre)} · {esc(d.ip)} · última vez {cuando}"


def info(ctx: Contexto, arg: str) -> str:
    d = _un_dispositivo(ctx, arg, "Uso: /info <nombre, IP o MAC>")
    if isinstance(d, str):
        return d
    now, z = ctx.ahora(), ctx.cfg.zona
    lineas = [f"{'🟢' if d.encendido else '⚪'} <b>{esc(d.nombre)}</b>"]
    campos = (
        ("Tipo", d.tipo),
        ("Ubicación", d.ubicacion),
        ("Fabricante", d.fabricante),
        ("Modelo", d.modelo),
        ("IP", d.ip),
        ("MAC", d.mac),
    )
    lineas += [f"{k}: {esc(v)}" for k, v in campos if v]
    if d.primera:
        lineas.append(f"Primera vez: {hora(d.primera, now, z)}")
    if d.ultima:
        lineas.append(f"Última vez: {hora(d.ultima, now, z)}")
    return recortar(lineas)


def lista(ctx: Contexto, arg: str) -> str:
    if not ctx.cfg.netinv:
        return SIN_NETINV
    try:
        ds = dispositivos(ctx.prom)
    except FuenteError:
        return PROM_CAIDO
    enc = [d for d in ds if d.encendido]
    if arg:
        enc = [d for d in enc if normalizar(d.tipo or SIN_TIPO) == normalizar(arg)]
    if not enc:
        return "Nada encendido" + (f" de tipo {esc(arg)}" if arg else "")
    grupos: dict[str, list[str]] = {}
    for d in sorted(enc, key=lambda d: normalizar(d.nombre)):
        grupos.setdefault(d.tipo or SIN_TIPO, []).append(d.nombre)
    lineas = [f"<b>Encendidos: {len(enc)}</b>"]
    lineas += [
        f"{esc(t)} ({len(ns)}): " + ", ".join(esc(n) for n in ns) for t, ns in sorted(grupos.items())
    ]
    return recortar(lineas)


COMANDOS: dict[str, Comando] = {
    "estado": estado,
    "alertas": alertas,
    "host": host,
    "dispositivo": dispositivo,
    "info": info,
    "lista": lista,
    "ayuda": ayuda,
    "start": ayuda,
}
