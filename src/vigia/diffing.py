"""Diff semántico entre lo generado y una referencia (lo desplegado o una línea base).

Compara el contenido cargado (YAML/JSON), no el texto: ignora comentarios, comillas y orden de claves.
Los ficheros de objetivos (listas de grupos con `targets`) se comparan como conjunto.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Diferencia:
    ruta: str
    tipo: str  # "solo-generado" | "solo-referencia" | "distinto"
    detalle: str = ""


def _cargar(datos: bytes, nombre: str) -> Any:
    if nombre.endswith((".yml", ".yaml")):
        return _normalizar(yaml.safe_load(datos.decode("utf-8")))
    if nombre.endswith(".json"):
        return _normalizar(json.loads(datos))
    return datos


def _normalizar(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _normalizar(x) for k, x in v.items()}
    if isinstance(v, list):
        xs = [_normalizar(x) for x in v]
        if xs and all(isinstance(x, dict) and "targets" in x for x in xs):
            # grupos de objetivos: se emparejan por objetivo, sin importar el orden
            return {",".join(map(str, x["targets"])): x.get("labels", {}) for x in xs}
        return xs
    return v


def _rutas(v: Any, pre: str = "") -> dict[str, Any]:
    """Aplana a {ruta: hoja} para describir las diferencias."""
    out: dict[str, Any] = {}
    if isinstance(v, dict):
        for k, x in v.items():
            out.update(_rutas(x, f"{pre}.{k}" if pre else k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out.update(_rutas(x, f"{pre}[{i}]"))
    else:
        out[pre] = v
    return out


def comparar(
    generado: dict[str, bytes],
    referencia: dict[str, bytes],
    equivalencias: dict[str, str] | None = None,
    max_detalle: int = 12,
) -> list[Diferencia]:
    eq = equivalencias or {}
    ref = {next((g for g, r in eq.items() if r == k), k): v for k, v in referencia.items()}
    out: list[Diferencia] = []
    for ruta in sorted(set(generado) | set(ref)):
        if ruta not in ref:
            out.append(Diferencia(ruta, "solo-generado"))
            continue
        if ruta not in generado:
            out.append(Diferencia(ruta, "solo-referencia"))
            continue
        a, b = _cargar(generado[ruta], ruta), _cargar(ref[ruta], ruta)
        if a == b:
            continue
        if isinstance(a, bytes) or isinstance(b, bytes):
            ta = a.decode("utf-8", "replace").splitlines() if isinstance(a, bytes) else []
            tb = b.decode("utf-8", "replace").splitlines() if isinstance(b, bytes) else []
            lineas = [
                x
                for x in difflib.unified_diff(tb, ta, "referencia", "generado", lineterm="", n=0)
                if not x.startswith(("---", "+++", "@@"))
            ]
            out.append(Diferencia(ruta, "distinto", "\n".join(lineas[:max_detalle])))
            continue
        pa, pb = _rutas(a), _rutas(b)
        lineas = []
        for k in sorted(set(pa) | set(pb)):
            if pa.get(k, "∅") != pb.get(k, "∅"):
                lineas.append(f"{k}: {pb.get(k, '∅')!r} → {pa.get(k, '∅')!r}")
        extra = f"\n… y {len(lineas) - max_detalle} más" if len(lineas) > max_detalle else ""
        out.append(Diferencia(ruta, "distinto", "\n".join(lineas[:max_detalle]) + extra))
    return out


def leer_carpeta(raiz: Path) -> dict[str, bytes]:
    return {
        f.relative_to(raiz).as_posix(): f.read_bytes()
        for f in sorted(raiz.rglob("*"))
        if f.is_file() and f.name != ".vigia-build"
    }
