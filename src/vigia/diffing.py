"""Diff semántico entre lo generado y una referencia (lo desplegado o una línea base).

Compara el contenido cargado (YAML/JSON), no el texto: ignora comentarios, comillas y orden de claves.
Los ficheros de objetivos (listas de grupos con `targets`) se comparan como conjunto.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_SECRET_KEY = re.compile(r"(pass|pwd|token|secret|key|clave|community|comunidad|auth|priv)", re.I)


def mask(line: str) -> str:
    """Oculta valores de claves con pinta de secreto y quita caracteres de control (salida a terminal)."""
    line = "".join(c for c in line if c.isprintable() or c == "\t")
    if _SECRET_KEY.search(line):
        return re.split(r"[:=]", line, maxsplit=1)[0] + ": ***"
    return line


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


def _identity(old: list[Any], new: list[Any]) -> str | None:
    """Clave que identifica cada elemento de una lista de mapas (única en cada lado)."""
    for k in ("job_name", "uid", "id", "refId", "name", "regex"):
        if (
            all(isinstance(x.get(k), str | int) for x in old + new)
            and len({x[k] for x in old}) == len(old)
            and len({x[k] for x in new}) == len(new)
        ):
            return k
    return None


def _key(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _changes(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Líneas legibles con lo que cambia de `old` a `new`.

    Las listas de mapas (reglas, paneles, objetivos) se comparan por contenido: lo añadido y lo quitado,
    y un aviso si solo cambia el orden, en vez de una diferencia por cada posición desplazada.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[str] = []
        for k in list(old) + [k for k in new if k not in old]:
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in new:
                out.append(f"{p}: quitado")
            elif k not in old:
                out.append(f"{p}: añadido {_short(new[k])}")
            elif old[k] != new[k]:
                out += _changes(old[k], new[k], p)
        return out
    if (
        isinstance(old, list)
        and isinstance(new, list)
        and len(old) + len(new) > 0
        and all(isinstance(x, dict) for x in old + new)
    ):
        ko, kn = [_key(x) for x in old], [_key(x) for x in new]
        if sorted(ko) == sorted(kn):
            return [f"{prefix}: mismo contenido, otro orden"]
        ident = _identity(old, new)
        if ident:
            mo, mn = {x[ident]: x for x in old}, {x[ident]: x for x in new}
            out = []
            for k in list(mo) + [k for k in mn if k not in mo]:
                p = f"{prefix}[{ident}={k}]"
                if k not in mn:
                    out.append(f"{p}: quitado")
                elif k not in mo:
                    out.append(f"{p}: añadido")
                elif mo[k] != mn[k]:
                    out += _changes(mo[k], mn[k], p)
            return out or [f"{prefix}: mismo contenido, otro orden"]
        if len(old) == len(new) and not any(x in kn for x in ko):
            pass  # todo distinto: mejor por posición
        else:
            out = [f"{prefix}: - {_short(x)}" for x, k in zip(old, ko, strict=True) if k not in kn]
            out += [f"{prefix}: + {_short(x)}" for x, k in zip(new, kn, strict=True) if k not in ko]
            if not out:
                out = [f"{prefix}: mismo contenido, otro orden (con repetidos)"]
            return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        out = []
        for i, (x, y) in enumerate(zip(old, new, strict=True)):
            if x != y:
                out += _changes(x, y, f"{prefix}[{i}]")
        return out
    po, pn = _flatten(old, prefix), _flatten(new, prefix)
    return [
        f"{k}: {po.get(k, '∅')!r} → {pn.get(k, '∅')!r}"
        for k in sorted(set(po) | set(pn))
        if po.get(k, "∅") != pn.get(k, "∅")
    ]


def _short(v: Any, n: int = 140) -> str:
    t = _key(v) if isinstance(v, dict | list) else repr(v)
    return t if len(t) <= n else t[: n - 1] + "…"


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
            out.append(Difference(path, "distinto", "\n".join(mask(x) for x in lines[:max_detail])))
            continue
        lines = _changes(b, a)
        extra = f"\n… y {len(lines) - max_detail} más" if len(lines) > max_detail else ""
        out.append(Difference(path, "distinto", "\n".join(mask(x) for x in lines[:max_detail]) + extra))
    return out


def read_dir(root: Path) -> dict[str, bytes]:
    return {
        f.relative_to(root).as_posix(): f.read_bytes()
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.name != ".vigia-build"
    }
