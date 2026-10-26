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
class Difference:
    path: str
    kind: str  # "solo-generado" | "solo-referencia" | "distinto"
    detail: str = ""


def _parse(data: bytes, name: str) -> Any:
    if name.endswith((".yml", ".yaml")):
        return _normalize(yaml.safe_load(data.decode("utf-8")))
    if name.endswith(".json"):
        return _normalize(json.loads(data))
    return data


def _normalize(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _normalize(x) for k, x in v.items()}
    if isinstance(v, list):
        xs = [_normalize(x) for x in v]
        if xs and all(isinstance(x, dict) and "targets" in x for x in xs):
            # grupos de objetivos: se emparejan por objetivo, sin importar el orden
            return {",".join(map(str, x["targets"])): x.get("labels", {}) for x in xs}
        return xs
    return v


def _flatten(v: Any, prefix: str = "") -> dict[str, Any]:
    """Aplana a {ruta: hoja} para describir las diferencias."""
    out: dict[str, Any] = {}
    if isinstance(v, dict):
        for k, x in v.items():
            out.update(_flatten(x, f"{prefix}.{k}" if prefix else k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out.update(_flatten(x, f"{prefix}[{i}]"))
    else:
        out[prefix] = v
    return out


def compare(
    generated: dict[str, bytes],
    reference: dict[str, bytes],
    mapping: dict[str, str] | None = None,
    max_detail: int = 12,
) -> list[Difference]:
    eq = mapping or {}
    ref = {next((g for g, r in eq.items() if r == k), k): v for k, v in reference.items()}
    out: list[Difference] = []
    for path in sorted(set(generated) | set(ref)):
        if path not in ref:
            out.append(Difference(path, "solo-generado"))
            continue
        if path not in generated:
            out.append(Difference(path, "solo-referencia"))
            continue
        a, b = _parse(generated[path], path), _parse(ref[path], path)
        if a == b:
            continue
        if isinstance(a, bytes) or isinstance(b, bytes):
            ta = a.decode("utf-8", "replace").splitlines() if isinstance(a, bytes) else []
            tb = b.decode("utf-8", "replace").splitlines() if isinstance(b, bytes) else []
            lines = [
                x
                for x in difflib.unified_diff(tb, ta, "referencia", "generado", lineterm="", n=0)
                if not x.startswith(("---", "+++", "@@"))
            ]
            out.append(Difference(path, "distinto", "\n".join(lines[:max_detail])))
            continue
        pa, pb = _flatten(a), _flatten(b)
        lines = []
        for k in sorted(set(pa) | set(pb)):
            if pa.get(k, "∅") != pb.get(k, "∅"):
                lines.append(f"{k}: {pb.get(k, '∅')!r} → {pa.get(k, '∅')!r}")
        extra = f"\n… y {len(lines) - max_detail} más" if len(lines) > max_detail else ""
        out.append(Difference(path, "distinto", "\n".join(lines[:max_detail]) + extra))
    return out


def read_dir(root: Path) -> dict[str, bytes]:
    return {
        f.relative_to(root).as_posix(): f.read_bytes()
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.name != ".vigia-build"
    }
