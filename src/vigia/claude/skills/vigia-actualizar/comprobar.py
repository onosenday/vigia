"""¿Es seguro subir este sitio a otra versión de vigia? Comprobación en seco: no cambia el tag ni despliega.

Uso, desde la raíz del repo del sitio:  uv run python .claude/skills/vigia-actualizar/comprobar.py --a v0.4.0

1. Lo desplegado coincide con el repo (`vigia deploy <unidad>` sin diferencias), salvo con --sin-desplegado.
2. Novedades del CHANGELOG entre la versión actual y la nueva.
3. La versión nueva (copia temporal del tag, ejecutada con uvx) valida el site.yaml y genera lo desplegable.
4. Diferencias entre lo que genera la versión actual y la nueva, clasificadas por riesgo.

Solo usa comandos estables de vigia (version, list-units, deploy sin --yes, validate, build): sirve para
cualquier versión de destino.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ALTO, MEDIO, BAJO = "ALTO", "MEDIO", "BAJO"
ORDEN = {BAJO: 0, MEDIO: 1, ALTO: 2}
VERSION_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
CABECERA_RE = re.compile(r"generado por vigia [0-9]+\.[0-9]+\.[0-9]+")
DATOS_IMAGENES = ("prometheus", "grafana")
"""Servicios cuyo cambio de imagen puede migrar o perder datos (TSDB, base de datos de Grafana)."""


@dataclass(frozen=True)
class Hallazgo:
    riesgo: str
    fichero: str
    motivo: str


def version_tuple(v: str) -> tuple[int, int, int]:
    m = VERSION_RE.match(v.strip())
    if not m:
        raise ValueError(f"versión no válida: {v!r} (p. ej. v0.4.0)")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def rango(v: tuple[int, int, int]) -> str:
    return f">={v[0]}.{v[1]},<{v[0]}.{v[1] + 1}"


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603


# --- novedades --------------------------------------------------------------------------------------


def novedades(changelog: str, actual: tuple[int, int, int], nueva: tuple[int, int, int]) -> str:
    """Secciones `## X.Y.Z` del CHANGELOG con actual < versión <= nueva."""
    out, dentro = [], False
    for linea in changelog.splitlines():
        m = re.match(r"^## ([0-9]+\.[0-9]+\.[0-9]+)\b", linea)
        if m:
            dentro = actual < version_tuple(m.group(1)) <= nueva
        if dentro:
            out.append(linea)
    return "\n".join(out).strip()


# --- clasificación de diferencias -------------------------------------------------------------------


def _leer(p: Path) -> str:
    return CABECERA_RE.sub("generado por vigia", p.read_text(encoding="utf-8", errors="replace"))


def _yaml(texto: str) -> Any:
    try:
        return yaml.safe_load(texto)
    except yaml.YAMLError:
        return None


def _compose(old: Any, new: Any, rel: str) -> list[Hallazgo]:
    out: list[Hallazgo] = []
    so, sn = old.get("services") or {}, new.get("services") or {}
    for name in sorted(set(so) - set(sn)):
        out.append(Hallazgo(MEDIO, rel, f"desaparece el servicio {name}"))
    for name in sorted(set(sn) - set(so)):
        out.append(Hallazgo(MEDIO, rel, f"servicio nuevo {name}"))
    for name in sorted(set(so) & set(sn)):
        a, b = so[name] or {}, sn[name] or {}
        if a == b:
            continue
        if a.get("image") != b.get("image"):
            datos = any(x in name for x in DATOS_IMAGENES)
            out.append(
                Hallazgo(
                    ALTO if datos else MEDIO,
                    rel,
                    f"{name}: imagen {a.get('image')} → {b.get('image')}"
                    + (" (guarda datos: puede migrarlos)" if datos else ""),
                )
            )
        if a.get("volumes") != b.get("volumes"):
            out.append(Hallazgo(ALTO, rel, f"{name}: cambian los volúmenes (dónde están los datos)"))
        ca, cb = a.get("command") or [], b.get("command") or []
        if ca != cb:
            tsdb = [x for x in [*ca, *cb] if "storage." in str(x) and (x in ca) != (x in cb)]
            if tsdb:
                out.append(
                    Hallazgo(ALTO, rel, f"{name}: cambia el almacenamiento: {', '.join(map(str, tsdb))}")
                )
            else:
                out.append(Hallazgo(MEDIO, rel, f"{name}: cambian los parámetros (se reinicia)"))
        resto = {k for k in set(a) | set(b) if a.get(k) != b.get(k)} - {"image", "volumes", "command"}
        if resto:
            out.append(Hallazgo(MEDIO, rel, f"{name}: cambia {', '.join(sorted(resto))} (se reinicia)"))
    return out


def _dashboard(old: str, new: str, rel: str) -> list[Hallazgo]:
    try:
        a, b = json.loads(old), json.loads(new)
    except json.JSONDecodeError:
        return [Hallazgo(BAJO, rel, "panel distinto")]
    if a.get("uid") != b.get("uid"):
        return [
            Hallazgo(
                ALTO, rel, f"cambia el uid {a.get('uid')} → {b.get('uid')} (se rompen enlaces y favoritos)"
            )
        ]
    return [Hallazgo(BAJO, rel, "panel distinto")]


def clasificar(viejo: Path, nuevo: Path) -> list[Hallazgo]:
    fo = {str(p.relative_to(viejo)) for p in viejo.rglob("*") if p.is_file()}
    fn = {str(p.relative_to(nuevo)) for p in nuevo.rglob("*") if p.is_file()}
    out: list[Hallazgo] = []
    for rel in sorted(fo - fn):
        riesgo = ALTO if rel.startswith("dashboards/") else MEDIO
        motivo = "desaparece el panel (se rompen enlaces)" if riesgo == ALTO else "deja de generarse"
        out.append(Hallazgo(riesgo, rel, motivo))
    for rel in sorted(fn - fo):
        out.append(Hallazgo(BAJO, rel, "fichero nuevo"))
    for rel in sorted(fo & fn):
        a, b = _leer(viejo / rel), _leer(nuevo / rel)
        if a == b:
            continue
        ya, yb = (_yaml(a), _yaml(b)) if rel.endswith((".yml", ".yaml")) else (None, None)
        if isinstance(ya, dict) and isinstance(yb, dict) and "services" in ya and "services" in yb:
            out += _compose(ya, yb, rel) or [Hallazgo(BAJO, rel, "solo cambia el formato")]
        elif rel.startswith("dashboards/") and rel.endswith(".json"):
            out += _dashboard(a, b, rel)
        elif "alerting/" in rel:
            out.append(Hallazgo(MEDIO, rel, "cambian las reglas o el destino de las alertas"))
        elif rel.endswith("prometheus.yml"):
            out.append(Hallazgo(MEDIO, rel, "cambia la configuración de Prometheus (trabajos de recogida)"))
        elif rel.endswith(("Dockerfile", ".py", ".sh")):
            out.append(Hallazgo(MEDIO, rel, "cambia una imagen propia (se reconstruye)"))
        else:
            out.append(Hallazgo(BAJO, rel, "contenido distinto"))
    return out


# --- pasos ------------------------------------------------------------------------------------------


def origen(sitio: Path, repo: str | None) -> str:
    if repo:
        return repo
    fuentes = tomllib.loads((sitio / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["uv"]["sources"]
    v = fuentes["vigia"]
    if "git" in v:
        return str(v["git"])
    return str((sitio / v["path"]).resolve())


def desplegado(sitio: Path) -> tuple[list[str], list[str]]:
    """(unidades con diferencias, unidades que no se pudieron comprobar)."""
    r = run(["uv", "run", "vigia", "list-units"], sitio)
    unidades = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    con, sin = [], []
    for u in unidades:
        d = run(["uv", "run", "vigia", "deploy", u], sitio)
        m = re.search(r": ([0-9]+) diferencias", d.stdout)
        if d.returncode != 0 or not m:
            sin.append(u)
        elif int(m.group(1)):
            con.append(f"{u} ({m.group(1)})")
    return con, sin


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", required=True, dest="destino", help="tag de destino, p. ej. v0.4.0")
    ap.add_argument("--sitio", type=Path, default=Path("."), help="raíz del repo del sitio")
    ap.add_argument("--repo", help="repo de vigia (por defecto, el de pyproject.toml)")
    ap.add_argument("--sin-desplegado", action="store_true", help="no compara con lo desplegado (sin SSH)")
    a = ap.parse_args()
    sitio = a.sitio.resolve()
    nueva = version_tuple(a.destino)
    tag = "v{}.{}.{}".format(*nueva)
    actual = version_tuple(run(["uv", "run", "vigia", "version"], sitio).stdout.strip().splitlines()[-1])
    hallazgos: list[Hallazgo] = []
    print(f"vigia {'.'.join(map(str, actual))} → {tag} en {sitio.name}\n")
    if nueva <= actual:
        print("La versión de destino no es posterior a la instalada: nada que comprobar.")
        return 0

    if a.sin_desplegado:
        print("1. Desplegado: no comprobado (--sin-desplegado).")
        hallazgos.append(Hallazgo(MEDIO, "(hosts)", "no se comprobó que lo desplegado coincida con el repo"))
    else:
        con, sin = desplegado(sitio)
        print("1. Desplegado:", "coincide con el repo" if not (con or sin) else "")
        for u in con:
            hallazgos.append(
                Hallazgo(ALTO, u, "lo desplegado no coincide con el repo: resolverlo antes de subir")
            )
        for u in sin:
            hallazgos.append(Hallazgo(MEDIO, u, "no se pudo comparar con lo desplegado"))

    tmp = Path(tempfile.mkdtemp(prefix="vigia-actualizar-"))
    site_tmp = sitio / f".site.vigia-actualizar-{tag}.yaml"
    try:
        src = tmp / "vigia"
        c = run(
            ["git", "clone", "-q", "--depth", "1", "--branch", tag, origen(sitio, a.repo), str(src)], sitio
        )
        if c.returncode != 0:
            print(f"No se pudo obtener {tag}: {c.stderr.strip()[:300]}")
            return 2
        cl = src / "CHANGELOG.md"
        texto = novedades(cl.read_text(encoding="utf-8"), actual, nueva) if cl.exists() else ""
        print("\n2. Novedades:\n" + (texto or "(sin CHANGELOG)") + "\n")

        original = (sitio / "site.yaml").read_text(encoding="utf-8")
        site_tmp.write_text(
            re.sub(r'(?m)^vigia:\s*["\']?[^"\'\n]*["\']?', f'vigia: "{rango(nueva)}"', original, count=1),
            encoding="utf-8",
        )
        uvx = ["uvx", "--isolated", "--from", str(src), "vigia"]
        v = run([*uvx, "validate", "--site", str(site_tmp)], sitio)
        print("3. Validación con la versión nueva:", "válido" if v.returncode == 0 else "NO VÁLIDO")
        if v.returncode != 0:
            print(
                "   "
                + (v.stderr or v.stdout).strip().replace(str(site_tmp), "site.yaml").replace("\n", "\n   ")
            )
            hallazgos.append(Hallazgo(ALTO, "site.yaml", "no valida con la versión nueva: hay que adaptarlo"))
        else:
            old, new = tmp / "actual", tmp / "nueva"
            b1 = run(["uv", "run", "vigia", "build", "-o", str(old)], sitio)
            b2 = run([*uvx, "build", "--site", str(site_tmp), "-o", str(new)], sitio)
            if b1.returncode or b2.returncode:
                cual = "la instalada" if b1.returncode else "la nueva"
                print(f"   {cual} no genera el sitio:", (b1.stderr or b2.stderr).strip()[:300])
                hallazgos.append(Hallazgo(ALTO, "build", f"la versión {cual} no genera el sitio"))
            else:
                hallazgos += clasificar(old, new)
        if not re.search(rf'(?m)^vigia:\s*["\']?{re.escape(rango(nueva))}', original):
            hallazgos.append(Hallazgo(BAJO, "site.yaml", f'al subir, poner vigia: "{rango(nueva)}"'))
    finally:
        site_tmp.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n4. Cambios en lo que se despliega:")
    for h in sorted(hallazgos, key=lambda x: -ORDEN[x.riesgo]):
        print(f"   [{h.riesgo:5}] {h.fichero}: {h.motivo}")
    if not hallazgos:
        print("   ninguno")
    veredicto = max((h.riesgo for h in hallazgos), key=ORDEN.__getitem__, default=BAJO)
    consejo = {
        BAJO: "seguro: solo paneles o textos.",
        MEDIO: "con cuidado: hay reinicios o cambios en alertas o recogida; revisar la lista.",
        ALTO: "riesgo: resolver o entender cada punto ALTO antes de subir.",
    }[veredicto]
    print(f"\nVEREDICTO: {veredicto} — {consejo}")
    print(
        f'Para subir: tag {tag} en pyproject.toml, vigia: "{rango(nueva)}" en site.yaml, uv sync, '
        "uv run vigia skill ., validate, deploy <unidad> (diff) y --yes con OK.\n"
        "Rollback: volver al tag anterior, uv sync y uv run vigia rollback <unidad> --yes."
    )
    return {BAJO: 0, MEDIO: 0, ALTO: 1}[veredicto]


if __name__ == "__main__":
    sys.exit(main())
