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
from .decisiones import OBSOLETA, VENCIDA, Decision, Juez
from .formato import esc
from .fuentes import FuenteError, Prometheus

AVISA = " ⚠"
PROXIMO = " · próximo"
DECIDIDO = "✔ Decidido (no hace falta hacer nada)"
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


def _motivo(d: Decision) -> str:
    txt = f" — {esc(d.motivo)}"
    if d.revisar:
        txt += f"; revisar el {d.revisar.strftime('%d-%m-%Y')}"
    return txt + (f" ({esc(d.ref)})" if d.ref else "")


def _calcular(cfg: Config, prom: Prometheus, ahora: float) -> tuple[list[str], list[str], Juez, Avisos]:
    """Secciones pendientes, líneas decididas (en el orden de las secciones), el juez y los avisos."""
    av = Avisos()
    juez = Juez(cfg.decisiones, datetime.fromtimestamp(ahora, ZoneInfo(cfg.zona)).date())
    decididas: list[str] = []  # soporte se ordena al final de su sección; el resto ya sale en orden
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
    filas_decididas = []
    for m, v in q(SOPORTE):
        txt = soporte(m, v, aviso.get(m.get("producto", ""), 0), cfg, ahora)
        if not txt:
            continue
        linea = f"{esc(m.get('nombre', ''))} · {esc(_producto(m))}: {txt}"
        d = juez.busca("soporte", m, m.get("ciclo"))
        if d and AVISA in txt:
            linea += f" (decidido: {esc(d.motivo)})"  # una decisión nunca oculta un aviso
        elif d:
            filas_decididas.append((orden(m.get("nombre", "")), v, linea + _motivo(d)))
            continue
        filas.append((orden(m.get("nombre", "")), v, linea))
    decididas += [t for *_, t in sorted(filas_decididas)]
    out += _seccion("🧭 Soporte", (t for *_, t in sorted(filas)))

    versiones = sorted(q(VERSIONES), key=lambda x: (orden(x[0].get("nombre", "")), _producto(x[0])))
    mayores = []
    for m, _ in versiones:
        linea = f"{esc(m.get('nombre', ''))} · {esc(_producto(m))} → {esc(m.get('ultimo', ''))}"
        d = juez.busca("versiones", m, m.get("ultimo"))
        if d:
            decididas.append(linea + _motivo(d))
        else:
            mayores.append(linea)
    out += _seccion("⬆ Versiones mayores", mayores)

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
    lineas = []
    for m in tags:
        linea = (
            f"{esc(m.get('nombre', ''))} · {esc(m.get('contenedor', ''))} {esc(m.get('local', ''))} → "
            f"{esc(m.get('remota', ''))}"
        )
        d = juez.busca("imagenes", m, m.get("remota"))
        if d:
            decididas.append(linea + _motivo(d))
        else:
            lineas.append(linea)
    digest: dict[str, list[str]] = {}
    for m, _ in sorted(imgs, key=lambda x: (orden(x[0].get("nombre", "")), x[0].get("contenedor", ""))):
        if m.get("tipo") == "digest":
            d = juez.busca("digest", m)
            if d:
                decididas.append(
                    f"{esc(m.get('nombre', ''))} · {esc(m.get('contenedor', ''))}: "
                    f"imagen nueva sin cambiar de etiqueta{_motivo(d)}"
                )
            else:
                digest.setdefault(m.get("nombre", ""), []).append(m.get("contenedor", ""))
    for n in sorted(digest, key=orden):
        cs = sorted(digest[n])
        lista = ", ".join(esc(c) for c in cs[:MAX_DIGEST]) + (" …" if len(cs) > MAX_DIGEST else "")
        lineas.append(f"{esc(n)}: {len(cs)} con imagen nueva sin cambiar de etiqueta ({lista})")
    out += _seccion("🐳 Imágenes", lineas)

    return out, decididas, juez, av


def pendientes(cfg: Config, prom: Prometheus, ahora: float) -> list[str]:
    """Líneas de /pendientes (sin recortar). `prom` es la fuente de Prometheus del bot."""
    out, decididas, juez, av = _calcular(cfg, prom, ahora)
    # sin datos (avisos) no se puede decir que no haya nada pendiente
    lineas = out or ([] if av.lineas else ["Nada pendiente ✅"])
    lineas += av.lineas + _seccion(DECIDIDO, decididas)
    # con datos parciales una decisión puede parecer obsoleta solo porque su consulta falló: solo las vencidas
    malas = {VENCIDA} if av.lineas else {VENCIDA, OBSOLETA}
    n = sum(1 for _, e in juez.estado() if e in malas)
    if n:
        que = "decisión obsoleta o vencida" if n == 1 else "decisiones obsoletas o vencidas"
        lineas.append(f"{n} {que}: vigia decisiones --limpiar")
    return lineas


def estado_decisiones(cfg: Config, prom: Prometheus, ahora: float) -> list[tuple[Decision, str]]:
    """Cada decisión con su estado (`vigia decisiones`). Si falta algún dato, FuenteError: sin datos, una
    decisión parecería obsoleta sin serlo."""
    _, _, juez, av = _calcular(cfg, prom, ahora)
    if av.lineas:
        raise FuenteError("; ".join(av.lineas))
    return juez.estado()


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
