"""/pendientes: lo que pide una acción planificada (mantenimiento), no lo que falla ahora (eso es /alertas).

Todo sale de Prometheus con las mismas expresiones que las alertas. Cada línea va marcada con ⚠ si ya pasa el
umbral de su alerta, o con «próximo» si está dentro del margen de `modulos.bot.proximo`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config
from .consultas import (
    AVISO_DIAS,
    CERTIFICADOS,
    CONSUMIBLES,
    DISCOS,
    IMAGENES,
    PENDIENTES,
    PRODUCTOS,
    SEGURIDAD,
    SOPORTE,
    VERSIONES,
    Avisos,
    por,
    serie,
)
from .formato import esc
from .fuentes import Prometheus

AVISA = " ⚠"
PROXIMO = " · próximo"
MAX_DIGEST = 6
"""Contenedores con imagen nueva (mismo tag) que se nombran por host; del resto, solo cuántos."""

Serie = list[tuple[dict[str, str], float]]


def _orden(cfg: Config) -> Callable[[str], tuple[int, str]]:
    """Ordena por el orden de `hosts:` del sitio; lo que no es un host, al final y por nombre."""
    pos = {h.nombre: i for i, h in enumerate(cfg.hosts)}
    return lambda nombre: (pos.get(nombre, len(pos)), nombre)


def _dias(v: float) -> str:
    d = round(abs(v))
    return f"{d} día" if d == 1 else f"{d} días"


def _fecha(ts: float, zona: str) -> str:
    return datetime.fromtimestamp(ts, ZoneInfo(zona)).strftime("%d-%m-%Y")


def _producto(m: dict[str, str]) -> str:
    txt = f"{m.get('producto_nombre', '')} {m.get('ciclo', '')}".strip()
    return txt + (f" ({m['contenedor']})" if m.get("contenedor") else "")


def soporte(m: dict[str, str], restante: float, aviso: float, cfg: Config, ahora: float) -> str | None:
    """Texto del soporte de un producto: ⚠ si ya avisa, próximo si está en el margen, None si queda lejos."""
    if restante < 0:
        return f"sin soporte desde hace {_dias(restante)}{AVISA}"
    if restante < aviso:
        return f"pierde el soporte en {_dias(restante)}{AVISA}"
    if restante < cfg.proximo.soporte_dias:
        return f"soporte hasta {_fecha(ahora + restante * 86400, cfg.zona)}{PROXIMO}"
    return None


def _seccion(titulo: str, lineas: Iterable[str]) -> list[str]:
    ls = list(lineas)
    return [f"<b>{titulo}</b>", *ls] if ls else []


def pendientes(cfg: Config, prom: Prometheus, ahora: float) -> list[str]:
    """Líneas de /pendientes (sin recortar). `prom` es la fuente de Prometheus del bot."""
    av = Avisos()
    orden = _orden(cfg)

    def q(expr: str) -> Serie:
        return serie(prom, av, expr)

    out: list[str] = []

    certs = sorted(
        (
            (m.get("nombre") or m.get("instance", ""), v)
            for m, v in q(CERTIFICADOS)
            if v < cfg.proximo.certificado_dias
        ),
        key=lambda x: x[1],
    )
    out += _seccion(
        "🔐 Certificados",
        (
            f"{esc(n)}: "
            + ("caducado" if v < 0 else f"caduca en {_dias(v)}")
            + (AVISA if v < cfg.certificado_dias else PROXIMO)
            for n, v in certs
        ),
    )

    consumibles: dict[str, list[str]] = {}
    for m, v in sorted(q(CONSUMIBLES), key=lambda x: x[1]):
        if v < cfg.proximo.consumible_pct:
            desc = re.sub(r";.*", "", m.get("prtMarkerSuppliesDescription", "")).strip()
            marca = AVISA if v < cfg.consumible_pct else PROXIMO.replace(" · ", " ")
            consumibles.setdefault(m.get("nombre", ""), []).append(f"{esc(desc)} {v:.0f}%{marca}")
    out += _seccion(
        "🖨 Consumibles", (f"{esc(n)}: " + " · ".join(cs) for n, cs in sorted(consumibles.items()))
    )

    discos = sorted(
        (
            (m.get("nombre", ""), m.get("mountpoint", ""), v)
            for m, v in q(DISCOS)
            if v >= cfg.proximo.disco_pct
        ),
        key=lambda x: (orden(x[0]), -x[2]),
    )
    out += _seccion(
        "💽 Discos",
        (f"{esc(n)} {esc(mp)} {v:.0f}%" + (AVISA if v >= cfg.disco_pct else PROXIMO) for n, mp, v in discos),
    )

    aviso = por(prom, av, AVISO_DIAS, "producto")
    filas = []
    for m, v in q(SOPORTE):
        txt = soporte(m, v, aviso.get(m.get("producto", ""), 0), cfg, ahora)
        if txt:
            filas.append(
                (orden(m.get("nombre", "")), v, f"{esc(m.get('nombre', ''))} · {esc(_producto(m))}: {txt}")
            )
    out += _seccion("🧭 Soporte", (t for *_, t in sorted(filas)))

    versiones = sorted(q(VERSIONES), key=lambda x: (orden(x[0].get("nombre", "")), _producto(x[0])))
    out += _seccion(
        "⬆ Versiones mayores",
        (
            f"{esc(m.get('nombre', ''))} · {esc(_producto(m))} → {esc(m.get('ultimo', ''))}"
            for m, _ in versiones
        ),
    )

    seg = por(prom, av, SEGURIDAD)
    pend = sorted(((n, v) for n, v in por(prom, av, PENDIENTES).items() if v > 0), key=lambda x: orden(x[0]))
    out += _seccion(
        "🛡 Actualizaciones",
        (
            f"{esc(n)}: {v:.0f}" + (f" ({seg[n]:.0f} de seguridad){AVISA}" if seg.get(n, 0) > 0 else "")
            for n, v in pend
        ),
    )

    imgs = q(IMAGENES)
    tags = sorted(
        (m for m, _ in imgs if m.get("tipo") == "tag"),
        key=lambda m: (orden(m.get("nombre", "")), m.get("contenedor", "")),
    )
    digest: dict[str, list[str]] = {}
    for m, _ in imgs:
        if m.get("tipo") == "digest":
            digest.setdefault(m.get("nombre", ""), []).append(m.get("contenedor", ""))
    lineas = [
        f"{esc(m.get('nombre', ''))} · {esc(m.get('contenedor', ''))} {esc(m.get('local', ''))} → "
        f"{esc(m.get('remota', ''))}"
        for m in tags
    ]
    for n in sorted(digest, key=orden):
        cs = sorted(digest[n])
        lista = ", ".join(esc(c) for c in cs[:MAX_DIGEST]) + (" …" if len(cs) > MAX_DIGEST else "")
        lineas.append(f"{esc(n)}: {len(cs)} con imagen nueva sin cambiar de etiqueta ({lista})")
    out += _seccion("🐳 Imágenes", lineas)

    if not out and av.lineas:
        return av.lineas  # sin datos no se puede decir que no haya nada pendiente
    return (out or ["Nada pendiente ✅"]) + av.lineas


def versiones_host(cfg: Config, prom: Prometheus, av: Avisos, nombre: str, ahora: float) -> list[str]:
    """Líneas de /host con la versión y el soporte de su sistema y productos (no de sus contenedores)."""
    restante = {
        (m.get("producto", ""), m.get("ciclo", "")): v
        for m, v in serie(prom, av, SOPORTE)
        if m.get("nombre") == nombre and not m.get("contenedor")
    }
    mayor = {
        m.get("producto", ""): m.get("ultimo", "")
        for m, _ in serie(prom, av, VERSIONES)
        if m.get("nombre") == nombre and not m.get("contenedor")
    }
    aviso = por(prom, av, AVISO_DIAS, "producto")
    lineas = []
    for m, _ in sorted(serie(prom, av, PRODUCTOS), key=lambda x: x[0].get("producto", "")):
        if m.get("nombre") != nombre or m.get("contenedor"):
            continue
        prod = m.get("producto", "")
        txt = f"🧭 {esc(m.get('producto_nombre', ''))} {esc(m.get('version', ''))}"
        v = restante.get((prod, m.get("ciclo", "")))
        if v is None:
            txt += " · soporte sin fecha de fin"
        elif v < 0 or v < aviso.get(prod, 0):
            txt += f" · {soporte(m, v, aviso.get(prod, 0), cfg, ahora)}"
        else:
            txt += f" · soporte hasta {_fecha(ahora + v * 86400, cfg.zona)}"
        if prod in mayor:
            txt += f" · ya existe la {esc(mayor[prod])}"
        lineas.append(txt)
    return lineas
