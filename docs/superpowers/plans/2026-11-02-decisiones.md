# Decisiones en /pendientes: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que `/pendientes` saque lo ya decidido en un bloque final «Decidido», con el motivo, a partir de un `decisiones.yaml` del sitio con caducidad, y que `vigia decisiones [--limpiar]` diga cuáles siguen vigentes.

**Architecture:** `vigia/decisiones.py` (pydantic) valida el fichero y quita entradas sin tocar el resto del texto. `build` mete la lista validada en `bot/config.json`. En el bot, `vigia/bot/decisiones.py` (sin pydantic: el contenedor no tiene vigia) decide qué línea cubre cada decisión, y `pendientes.py` reparte las líneas entre lo pendiente y el bloque «Decidido». La CLI reutiliza ese cálculo contra el Prometheus del sitio.

**Tech Stack:** Python 3.12, pydantic 2, PyYAML, typer, pytest; `uv run pytest`, `uv run ruff check`, `uv run mypy src`.

Spec: `docs/superpowers/specs/2026-11-02-decisiones-design.md`. Issue: `vigia-3j2`. Todos los comandos, desde la raíz del repo de vigia.

## Ficheros

| Fichero | Qué cambia |
|---------|------------|
| `src/vigia/decisiones.py` (nuevo) | Modelo `Decision`, `load_decisiones()`, `a_json()`, `quitar_entradas()` |
| `src/vigia/model.py` | `Bot.decisiones: SitePath \| None` |
| `src/vigia/build.py` | `_bot(s, site_root)` y `bot_config(s, decisiones)` |
| `src/vigia/bot/decisiones.py` (nuevo) | `Decision` (dataclass), `desde_json()`, `Juez` |
| `src/vigia/bot/config.py` | `Config.decisiones`; `desde_dict()` |
| `src/vigia/bot/pendientes.py` | `_calcular()`, bloque «Decidido», `estado_decisiones()` |
| `src/vigia/cli.py` | `validate` comprueba el fichero; comando `decisiones` |
| `examples/sitio-ejemplo/decisiones.yaml` (nuevo) y su `site.yaml` | Ejemplo; golden actualizado |
| `tests/test_decisiones.py`, `tests/test_bot_decisiones.py` (nuevos), `tests/test_bot_pendientes.py`, `tests/test_bot_build.py`, `tests/test_cli_decisiones.py` (nuevo) | Pruebas |
| `docs/bot.md`, `src/vigia/claude/skills/vigia/SKILL.md`, la spec | Documentación |

---

### Task 1: Ajustar la spec

**Files:** Modify: `docs/superpowers/specs/2026-11-02-decisiones-design.md`

- [ ] **Step 1: El fichero se declara en `site.yaml`.** En «## Fichero `decisiones.yaml`», sustituir el primer párrafo por:

```markdown
Es opcional y va en la carpeta del sitio. Se declara en `site.yaml` igual que `netinv.dispositivos`:
`modulos.bot.decisiones: decisiones.yaml` (ruta relativa al sitio). Es una lista:
```

- [ ] **Step 2: El separador es « — ».** En «## Salida del bot», cambiar «con la línea original, `: <motivo>`» por «con la línea original, ` — <motivo>`» (las líneas de soporte ya llevan `:`).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-11-02-decisiones-design.md
git commit -m "docs: decisiones declaradas en site.yaml y separador del motivo"
```

### Task 2: Modelo y lectura de `decisiones.yaml`

**Files:** Create: `src/vigia/decisiones.py`, `tests/test_decisiones.py`

- [ ] **Step 1: Tests que fallan** (`tests/test_decisiones.py`):

```python
"""decisiones.yaml: validación y lectura (datos sintéticos)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from vigia.decisiones import a_json, load_decisiones

HOSTS = ["Nodo 1", "NAS"]


def _f(tmp_path: Path, texto: str) -> Path:
    p = tmp_path / "decisiones.yaml"
    p.write_text(texto, encoding="utf-8")
    return p


def test_lee_y_normaliza(tmp_path: Path) -> None:
    p = _f(
        tmp_path,
        "- {seccion: imagenes, host: Nodo 1, objeto: prometheus, ofrecido: v3.15.1, motivo: LTS, ref: T-1}\n"
        "- {seccion: versiones, host: NAS, objeto: postgresql, ofrecido: 18, motivo: espera}\n"
        "- {seccion: soporte, host: NAS, objeto: grafana, revisar: 2027-01-15, motivo: lejos}\n",
    )
    ds = load_decisiones(p, HOSTS)
    assert [d.ofrecido for d in ds] == ["v3.15.1", "18", None]  # 18 llega como int de YAML
    assert ds[2].revisar == dt.date(2027, 1, 15)
    assert a_json(ds)[2] == {
        "seccion": "soporte", "host": "NAS", "objeto": "grafana", "motivo": "lejos", "revisar": "2027-01-15"
    }


def test_fichero_vacio(tmp_path: Path) -> None:
    assert load_decisiones(_f(tmp_path, "# nada decidido\n"), HOSTS) == []


@pytest.mark.parametrize(
    ("texto", "error"),
    [
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, motivo: m}\n", "ofrecido` o `revisar"),
        ("- {seccion: digest, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m}\n", "digest"),
        ("- {seccion: discos, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m}\n", "seccion"),
        ("- {seccion: imagenes, host: Otro, objeto: x, ofrecido: v2, motivo: m}\n", "Otro"),
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, ofrecido: v2, motivo: m, otro: 1}\n", "otro"),
        ("- {seccion: imagenes, host: Nodo 1, objeto: x, ofrecido: v2, motivo: ''}\n", "motivo"),
        ("{seccion: imagenes}\n", "list"),
    ],
)
def test_errores(tmp_path: Path, texto: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        load_decisiones(_f(tmp_path, texto), HOSTS)
```

- [ ] **Step 2: Comprobar que fallan.** Run: `uv run pytest tests/test_decisiones.py -q`. Expected: FAIL (`ModuleNotFoundError: vigia.decisiones`).

- [ ] **Step 3: Implementación** (`src/vigia/decisiones.py`):

```python
"""Decisiones del sitio sobre /pendientes (`modulos.bot.decisiones`, docs/bot.md).

Lo que ya está decidido y no pide acción, con el motivo. Toda decisión caduca: cuando lo ofrecido cambia
(`ofrecido`) o en una fecha (`revisar`), así el fichero solo guarda lo vigente.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

Seccion = Literal["soporte", "versiones", "imagenes", "digest"]
"""Las secciones de /pendientes donde decidir tiene sentido (las demás siempre piden acción)."""


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seccion: Seccion
    host: str = Field(min_length=1, max_length=100)
    """Nombre visible del host (la etiqueta `nombre`)."""
    objeto: str = Field(min_length=1, max_length=100)
    """Contenedor (imagenes, digest) o producto (soporte, versiones)."""
    motivo: str = Field(min_length=1, max_length=200)
    ofrecido: str | None = Field(default=None, min_length=1, max_length=100)
    """Lo que se descarta: ciclo (soporte), versión (versiones) o etiqueta remota (imagenes)."""
    revisar: dt.date | None = None
    ref: str | None = Field(default=None, min_length=1, max_length=60)

    @field_validator("host", "objeto", "ofrecido", "ref", mode="before")
    @classmethod
    def _texto(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v

    @model_validator(mode="after")
    def _caduca(self) -> Decision:
        if self.ofrecido is None and self.revisar is None:
            raise ValueError("toda decisión necesita `ofrecido` o `revisar` (si no, no caduca nunca)")
        if self.seccion == "digest" and self.ofrecido is not None:
            raise ValueError("en `digest` no hay versión ofrecida: usa `revisar`")
        return self


_LISTA = TypeAdapter(list[Decision])


def load_decisiones(path: Path, hosts: Iterable[str]) -> list[Decision]:
    """Lee y valida el fichero (solo `yaml.safe_load`); `hosts`, los nombres visibles del sitio."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    lista = _LISTA.validate_python(data if data is not None else [])
    malos = sorted({d.host for d in lista} - set(hosts))
    if malos:
        raise ValueError(f"{path.name}: hosts que no están en site.yaml: {malos}")
    return lista


def a_json(decisiones: Sequence[Decision]) -> list[dict[str, Any]]:
    """Para el config.json del bot (sin los campos vacíos)."""
    return [d.model_dump(mode="json", exclude_none=True) for d in decisiones]
```

- [ ] **Step 4: Comprobar que pasan.** Run: `uv run pytest tests/test_decisiones.py -q`. Expected: PASS. Run: `uv run ruff check src/vigia/decisiones.py tests/test_decisiones.py && uv run mypy src/vigia/decisiones.py`. Expected: sin errores.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/decisiones.py tests/test_decisiones.py
git commit -m "feat: modelo y lectura de decisiones.yaml (vigia-3j2)"
```

### Task 3: Quitar entradas sin tocar el resto del fichero

**Files:** Modify: `src/vigia/decisiones.py`, `tests/test_decisiones.py`

- [ ] **Step 1: Tests que fallan** (añadir a `tests/test_decisiones.py`):

```python
from vigia.decisiones import quitar_entradas

TEXTO = (
    "# Cabecera: se conserva\n"
    "- {seccion: imagenes, host: Nodo 1, objeto: a, ofrecido: v2, motivo: uno}\n"
    "# comentario de primer nivel: se conserva\n"
    "- seccion: imagenes\n"
    "  host: Nodo 1\n"
    "  objeto: b   # comentario de la entrada: se va con ella\n"
    "  ofrecido: v2\n"
    "  motivo: dos\n"
    "- {seccion: imagenes, host: Nodo 1, objeto: c, ofrecido: v2, motivo: tres}\n"
)


def test_quitar_entradas() -> None:
    assert quitar_entradas(TEXTO, {1}) == (
        "# Cabecera: se conserva\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: a, ofrecido: v2, motivo: uno}\n"
        "# comentario de primer nivel: se conserva\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: c, ofrecido: v2, motivo: tres}\n"
    )
    assert quitar_entradas(TEXTO, {0, 2}).count("- ") == 1
    assert quitar_entradas(TEXTO, set()) == TEXTO


def test_quitar_entradas_formato_raro() -> None:
    with pytest.raises(ValueError, match="a mano"):
        quitar_entradas("[{seccion: imagenes}]\n", {0})
```

- [ ] **Step 2: Comprobar que fallan.** Run: `uv run pytest tests/test_decisiones.py -q -k quitar`. Expected: FAIL (`ImportError: quitar_entradas`).

- [ ] **Step 3: Implementación** (añadir a `src/vigia/decisiones.py`):

```python
def quitar_entradas(texto: str, indices: set[int]) -> str:
    """Quita las entradas `indices` (posición en la lista) sin tocar el resto del texto.

    Cada entrada es su línea `- ` de la columna 0 más las líneas sangradas que la siguen. Los comentarios y
    líneas en blanco de primer nivel se conservan. Si el fichero no tiene esa forma, no se toca.
    """
    lineas = texto.splitlines(keepends=True)
    inicios = [i for i, linea in enumerate(lineas) if linea.startswith("- ")]
    data = yaml.safe_load(texto)
    if not isinstance(data, list) or len(data) != len(inicios):
        raise ValueError("formato que --limpiar no sabe editar (una entrada por `- ` en la columna 0): hazlo a mano")
    fuera: set[int] = set()
    for k, ini in enumerate(inicios):
        if k not in indices:
            continue
        fin = ini + 1
        while fin < len(lineas) and lineas[fin].startswith((" ", "\t")):
            fin += 1
        fuera.update(range(ini, fin))
    return "".join(linea for i, linea in enumerate(lineas) if i not in fuera)
```

- [ ] **Step 4: Comprobar que pasan.** Run: `uv run pytest tests/test_decisiones.py -q && uv run ruff check src/vigia/decisiones.py`. Expected: PASS y sin errores.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/decisiones.py tests/test_decisiones.py
git commit -m "feat: quitar decisiones del fichero conservando los comentarios (vigia-3j2)"
```

### Task 4: `modulos.bot.decisiones`, `validate` y el config.json del bot

**Files:** Modify: `src/vigia/model.py` (clase `Bot`), `src/vigia/build.py` (`bot_config`, `_bot`, `build_site`), `src/vigia/cli.py` (`validate`), `tests/test_bot_build.py`; Create: `examples/sitio-ejemplo/decisiones.yaml`; Modify: `examples/sitio-ejemplo/site.yaml`, `tests/golden/sitio-ejemplo/bot/config.json` (regenerado)

- [ ] **Step 1: Ejemplo.** Crear `examples/sitio-ejemplo/decisiones.yaml`:

```yaml
# Lo ya decidido sobre /pendientes (docs/bot.md): sale al final, en «Decidido», con el motivo.
# Toda decisión caduca: cuando cambia lo ofrecido (`ofrecido`) o en la fecha `revisar`.
- {seccion: imagenes, host: Nodo 1, objeto: prometheus, ofrecido: v3.15.1, motivo: "seguimos en la LTS 3.13", ref: EJ-1}
```

y en `examples/sitio-ejemplo/site.yaml` cambiar la línea del bot por:

```yaml
  bot: {activo: true, grafana_token: BOT_GRAFANA_TOKEN, decisiones: decisiones.yaml}
```

- [ ] **Step 2: Tests que fallan** (añadir a `tests/test_bot_build.py`):

```python
def test_decisiones_en_el_config_del_bot(example_data: dict[str, Any]) -> None:
    _, out = _out(example_data)
    cfg = json.loads(out["bot/config.json"])
    assert cfg["decisiones"] == [
        {
            "seccion": "imagenes",
            "host": "Nodo 1",
            "objeto": "prometheus",
            "motivo": "seguimos en la LTS 3.13",
            "ofrecido": "v3.15.1",
            "ref": "EJ-1",
        }
    ]


def test_sin_decisiones(example_data: dict[str, Any]) -> None:
    del example_data["modulos"]["bot"]["decisiones"]
    _, out = _out(example_data)
    assert json.loads(out["bot/config.json"])["decisiones"] == []
```

- [ ] **Step 3: Comprobar que fallan.** Run: `uv run pytest tests/test_bot_build.py -q`. Expected: FAIL (`decisiones` no es un campo de `Bot`, o falta la clave en el JSON).

- [ ] **Step 4: Modelo** (`src/vigia/model.py`, clase `Bot`, después de `proximo`):

```python
    decisiones: SitePath | None = None
    """decisiones.yaml del sitio: lo ya decidido sobre /pendientes (vigia.decisiones, docs/bot.md)."""
```

- [ ] **Step 5: Build** (`src/vigia/build.py`). Importar arriba `from .decisiones import Decision, a_json, load_decisiones` y `from collections.abc import Sequence` (si no está). Cambiar:

```python
def bot_config(s: Site, decisiones: Sequence[Decision] = ()) -> str:
    """config.json del bot: sin secretos (los tokens llegan por el entorno del contenedor)."""
    ...  # el dict actual, con una clave más al final:
        "decisiones": a_json(decisiones),
```

```python
def _decisiones(s: Site, site_root: Path) -> list[Decision]:
    rel = s.modulos.bot.decisiones
    return load_decisiones(site_root / rel, [h.display_name for h in s.hosts]) if rel else []


def _bot(s: Site, site_root: Path) -> dict[str, str | bytes]:
    """Dockerfile, código de `vigia.bot` (será el paquete `vigia_bot` del contenedor) y config.json."""
    out = _bundled_image("bot", "bot")
    with as_file(files("vigia").joinpath("bot")) as path:
        for f in sorted(Path(path).glob("*.py")):
            out[f"bot/{f.name}"] = f.read_bytes()
    out["bot/config.json"] = bot_config(s, _decisiones(s, site_root))
    return out
```

y en `build_site`, `out.update(_bot(s, site_root))`. Buscar otros usos: `grep -rn "_bot(\|bot_config(" src tests` y adaptarlos.

- [ ] **Step 6: `validate`** (`src/vigia/cli.py`). Importar `from .decisiones import load_decisiones`. Tras `s = _load(site)` en `validate`:

```python
    n_dec = 0
    if s.modulos.bot.decisiones:
        try:
            n_dec = len(load_decisiones(site.parent / s.modulos.bot.decisiones, [h.display_name for h in s.hosts]))
        except (OSError, ValueError) as e:
            typer.echo(f"{s.modulos.bot.decisiones}: {e}", err=True)
            raise typer.Exit(1) from None
```

y añadir `f", {n_dec} decisiones"` al final del mensaje de «válido» solo si `s.modulos.bot.decisiones` (ver el `typer.echo` actual y añadirlo dentro del paréntesis).

- [ ] **Step 7: Golden y tests.** Run: `VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py -q`, luego `git diff --stat tests/golden` (Expected: solo `bot/config.json`). Run: `uv run pytest -q`. Expected: todo PASS.

- [ ] **Step 8: Commit**

```bash
git add src/vigia/model.py src/vigia/build.py src/vigia/cli.py tests/test_bot_build.py examples/sitio-ejemplo tests/golden
git commit -m "feat: decisiones del sitio en el config.json del bot (vigia-3j2)"
```

### Task 5: Decisiones en el bot (`Juez`)

**Files:** Create: `src/vigia/bot/decisiones.py`, `tests/test_bot_decisiones.py`; Modify: `src/vigia/bot/config.py`

- [ ] **Step 1: Tests que fallan** (`tests/test_bot_decisiones.py`):

```python
"""Qué línea de /pendientes cubre cada decisión (datos sintéticos)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from vigia.bot.config import desde_dict, load
from vigia.bot.decisiones import OBSOLETA, VENCIDA, VIGENTE, Decision, Juez, desde_json

HOY = date(2026, 10, 28)
M = {"nombre": "Nodo 1", "contenedor": "prometheus", "producto": "prometheus"}


def _j(*ds: Decision) -> Juez:
    return Juez(ds, HOY)


def test_coincide_por_host_objeto_y_ofrecido() -> None:
    d = Decision("imagenes", "Nodo 1", "prometheus", "LTS", ofrecido="v3.15.1")
    j = _j(d)
    assert j.busca("imagenes", M, "v3.15.1") is d
    assert j.busca("imagenes", M, "v3.16.0") is None  # otra oferta: decisión nueva
    assert j.busca("versiones", M, "v3.15.1") is None
    assert j.busca("imagenes", M | {"nombre": "NAS"}, "v3.15.1") is None
    assert j.estado() == [(d, VIGENTE)]


def test_objeto_por_producto_o_contenedor() -> None:
    d = Decision("soporte", "Nodo 1", "grafana", "lejos", revisar=date(2026, 12, 1))
    assert _j(d).busca("soporte", {"nombre": "Nodo 1", "producto": "grafana"}, "13.0") is d
    assert _j(d).busca("soporte", {"nombre": "Nodo 1", "contenedor": "grafana", "producto": "x"}, "1") is d


def test_obsoleta_y_vencida() -> None:
    sin_uso = Decision("imagenes", "Nodo 1", "a", "m", ofrecido="2")
    vencida = Decision("digest", "Nodo 1", "prometheus", "m", revisar=HOY)  # el mismo día ya vence
    j = _j(sin_uso, vencida)
    assert j.busca("digest", M) is None
    assert j.estado() == [(sin_uso, OBSOLETA), (vencida, VENCIDA)]


def test_desde_json_y_config(tmp_path: Path) -> None:
    lista = [{"seccion": "soporte", "host": "NAS", "objeto": "g", "motivo": "m", "revisar": "2027-01-15"}]
    assert desde_json(lista) == (Decision("soporte", "NAS", "g", "m", revisar=date(2027, 1, 15)),)
    base = {
        "sitio": "S", "chat_id": -1, "zona": "Europe/Madrid", "puerto": 9466, "prometheus": "http://p:9090",
        "grafana": "http://g:3000", "netinv": False, "disco_pct": 90, "hosts": [],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(base | {"decisiones": lista}), encoding="utf-8")
    assert load(p, {"TELEGRAM_TOKEN": "t"}).decisiones == desde_json(lista)
    assert desde_dict(base, {}, sin_telegram=True).decisiones == ()  # config.json anterior, sin la clave
```

- [ ] **Step 2: Comprobar que fallan.** Run: `uv run pytest tests/test_bot_decisiones.py -q`. Expected: FAIL (`ModuleNotFoundError: vigia.bot.decisiones`).

- [ ] **Step 3: Implementación** (`src/vigia/bot/decisiones.py`):

```python
"""Decisiones del sitio en /pendientes (vigia.decisiones, docs/bot.md): qué línea cubre cada una.

Sin pydantic ni vigia: el bot corre en su contenedor solo con la biblioteca estándar.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

VIGENTE, OBSOLETA, VENCIDA = "vigente", "obsoleta", "vencida"


@dataclass(frozen=True)
class Decision:
    seccion: str
    host: str
    objeto: str
    motivo: str
    ofrecido: str | None = None
    revisar: date | None = None
    ref: str | None = None


def desde_json(lista: Iterable[Mapping[str, Any]]) -> tuple[Decision, ...]:
    return tuple(
        Decision(
            seccion=str(d["seccion"]),
            host=str(d["host"]),
            objeto=str(d["objeto"]),
            motivo=str(d["motivo"]),
            ofrecido=None if d.get("ofrecido") is None else str(d["ofrecido"]),
            revisar=date.fromisoformat(d["revisar"]) if d.get("revisar") else None,
            ref=None if d.get("ref") is None else str(d["ref"]),
        )
        for d in lista
    )


@dataclass
class Juez:
    """Reparte las líneas de /pendientes entre las decisiones y recuerda cuáles se han usado."""

    decisiones: tuple[Decision, ...]
    hoy: date
    _usadas: set[int] = field(default_factory=set)

    def vencida(self, d: Decision) -> bool:
        return d.revisar is not None and d.revisar <= self.hoy

    def busca(self, seccion: str, m: Mapping[str, str], ofrecido: str | None = None) -> Decision | None:
        """La primera decisión vigente que cubre esta línea (etiquetas `m` de Prometheus), o None."""
        objetos = {m.get("contenedor"), m.get("producto")} - {None, ""}
        for i, d in enumerate(self.decisiones):
            if (
                d.seccion == seccion
                and d.host == m.get("nombre")
                and d.objeto in objetos
                and (d.ofrecido is None or d.ofrecido == ofrecido)
                and not self.vencida(d)
            ):
                self._usadas.add(i)
                return d
        return None

    def estado(self) -> list[tuple[Decision, str]]:
        """Cada decisión con su estado, en el orden del fichero (tras repartir todas las líneas)."""
        return [
            (d, VENCIDA if self.vencida(d) else VIGENTE if i in self._usadas else OBSOLETA)
            for i, d in enumerate(self.decisiones)
        ]
```

- [ ] **Step 4: Config** (`src/vigia/bot/config.py`). Importar `from typing import Any` y `from .decisiones import Decision, desde_json`. Añadir a `Config`, al final: `decisiones: tuple[Decision, ...] = ()`. Sustituir `load` por:

```python
def load(path: Path, env: Mapping[str, str]) -> Config:
    return desde_dict(json.loads(path.read_text(encoding="utf-8")), env)


def desde_dict(d: Mapping[str, Any], env: Mapping[str, str], *, sin_telegram: bool = False) -> Config:
    """`sin_telegram`: para la CLI (`vigia decisiones`), que solo consulta Prometheus."""
    token = env.get("TELEGRAM_TOKEN", "")
    if not token and not sin_telegram:
        raise ValueError("falta TELEGRAM_TOKEN en el entorno del contenedor")
    return Config(
        ...  # los mismos campos que ahora, leídos de `d`
        decisiones=desde_json(d.get("decisiones", [])),
    )
```

(El cuerpo de `Config(...)` es el actual de `load`, sin cambios salvo la línea de `decisiones`.)

- [ ] **Step 5: Comprobar que pasan.** Run: `uv run pytest tests/test_bot_decisiones.py tests/test_bot_main.py -q && uv run mypy src/vigia/bot`. Expected: PASS y sin errores.

- [ ] **Step 6: Commit**

```bash
git add src/vigia/bot/decisiones.py src/vigia/bot/config.py tests/test_bot_decisiones.py
git commit -m "feat: el bot sabe qué línea cubre cada decisión (vigia-3j2)"
```

### Task 6: Bloque «Decidido» en /pendientes

**Files:** Modify: `src/vigia/bot/pendientes.py`, `tests/test_bot_pendientes.py`

- [ ] **Step 1: Tests que fallan** (añadir a `tests/test_bot_pendientes.py`; `PROM` y `contexto` son los del fichero):

```python
from datetime import date

from vigia.bot.decisiones import Decision

DEC = (
    Decision("imagenes", "Nodo 1", "grafana", "esperamos a la 13.4", ofrecido="13.3.0", ref="T-1"),
    Decision("soporte", "NAS", "debian", "se retira el NAS", revisar=date(2026, 12, 1)),
    Decision("soporte", "Nodo 2", "debian", "lo sabemos", ofrecido="11"),  # con ⚠: no se oculta
    Decision("digest", "Nodo 1", "pihole", "la actualiza watchtower", revisar=date(2027, 1, 1)),
    Decision("imagenes", "Nodo 1", "grafana", "oferta vieja", ofrecido="13.2.0"),  # obsoleta
)


def test_pendientes_con_decisiones() -> None:
    lineas = (responder("/pendientes", contexto(PROM, decisiones=DEC)) or "").splitlines()
    assert "NAS · Debian 12: soporte hasta 25-02-2027 · próximo" not in lineas
    assert "Nodo 2 · Debian 11: sin soporte desde hace 59 días ⚠ (decidido: lo sabemos)" in lineas
    assert "Nodo 1: 1 con imagen nueva sin cambiar de etiqueta (homepage)" in lineas
    i = lineas.index("<b>✔ Decidido (no hace falta hacer nada)</b>")
    assert lineas[i + 1 :] == [
        "NAS · Debian 12: soporte hasta 25-02-2027 · próximo — se retira el NAS; revisar el 01-12-2026",
        "Nodo 1 · grafana 13.0.2 → 13.3.0 — esperamos a la 13.4 (T-1)",
        "Nodo 1 · pihole: imagen nueva sin cambiar de etiqueta — la actualiza watchtower; revisar el 01-01-2027",
        "1 decisión obsoleta o vencida: vigia decisiones --limpiar",
    ]
    assert not any(x.startswith("Nodo 1 · grafana") for x in lineas[:i])


def test_todo_decidido() -> None:
    prom = {c.IMAGENES: PROM[c.IMAGENES][:1]}
    texto = responder("/pendientes", contexto(prom, decisiones=DEC[:1])) or ""
    assert texto.splitlines() == [
        "Nada pendiente ✅",
        "<b>✔ Decidido (no hace falta hacer nada)</b>",
        "Nodo 1 · grafana 13.0.2 → 13.3.0 — esperamos a la 13.4 (T-1)",
    ]


def test_estado_decisiones() -> None:
    from vigia.bot.decisiones import OBSOLETA, VIGENTE
    from vigia.bot.pendientes import estado_decisiones

    ctx = contexto(PROM, decisiones=DEC)
    assert [e for _, e in estado_decisiones(ctx.cfg, ctx.prom, ctx.ahora())] == [
        VIGENTE, VIGENTE, VIGENTE, VIGENTE, OBSOLETA
    ]


def test_estado_decisiones_sin_prometheus() -> None:
    import pytest

    from vigia.bot.fuentes import FuenteError
    from vigia.bot.pendientes import estado_decisiones

    ctx = contexto(prom_caido=True, decisiones=DEC)
    with pytest.raises(FuenteError):
        estado_decisiones(ctx.cfg, ctx.prom, ctx.ahora())
```

(`contexto(..., decisiones=DEC)` llega a `cfg(**cambios)` de `tests/bot_fakes.py`, que ya acepta cualquier campo de `Config`. El test `test_pendientes` existente, sin decisiones, no debe cambiar.)

- [ ] **Step 2: Comprobar que fallan.** Run: `uv run pytest tests/test_bot_pendientes.py -q`. Expected: los 4 nuevos FAIL; los demás PASS.

- [ ] **Step 3: Implementación** (`src/vigia/bot/pendientes.py`):

Importar `from .decisiones import VIGENTE, Decision, Juez` y `from .fuentes import FuenteError, Prometheus`. Añadir constantes y ayudantes:

```python
DECIDIDO = "✔ Decidido (no hace falta hacer nada)"


def _motivo(d: Decision) -> str:
    txt = f" — {esc(d.motivo)}"
    if d.revisar:
        txt += f"; revisar el {d.revisar.strftime('%d-%m-%Y')}"
    return txt + (f" ({esc(d.ref)})" if d.ref else "")
```

Renombrar el cuerpo actual de `pendientes()` a `_calcular(cfg, prom, ahora) -> tuple[list[str], list[str], Juez, Avisos]` que devuelve `(out, decididas, juez, av)` en vez de las líneas finales, con estos cambios:

1. Al principio: `juez = Juez(cfg.decisiones, datetime.fromtimestamp(ahora, ZoneInfo(cfg.zona)).date())` y `decididas: list[str] = []`.
2. Soporte, dentro del bucle, en vez de añadir directamente:

```python
        txt = soporte(m, v, aviso.get(m.get("producto", ""), 0), cfg, ahora)
        if not txt:
            continue
        linea = f"{esc(m.get('nombre', ''))} · {esc(_producto(m))}: {txt}"
        d = juez.busca("soporte", m, m.get("ciclo"))
        if d and AVISA in txt:
            linea += f" (decidido: {esc(d.motivo)})"  # una decisión nunca oculta un aviso
        elif d:
            decididas.append(linea + _motivo(d))
            continue
        filas.append((orden(m.get("nombre", "")), v, linea))
```

3. Versiones mayores: filtrar antes de `_seccion` con un bucle que, para cada `m`, haga `d = juez.busca("versiones", m, m.get("ultimo"))`; si hay `d`, la línea (la misma que ahora) + `_motivo(d)` va a `decididas`; si no, a la sección.
4. Imágenes por etiqueta: igual, con `juez.busca("imagenes", m, m.get("remota"))`.
5. Digest: al agrupar, `d = juez.busca("digest", m)`; si hay `d`, `decididas.append(f"{esc(m.get('nombre', ''))} · {esc(m.get('contenedor', ''))}: imagen nueva sin cambiar de etiqueta{_motivo(d)}")` y no se añade a `digest`.
6. Quitar del final el `if not out and av.lineas` y el `return`: `_calcular` termina con `return out, decididas, juez, av`.

Y las dos funciones públicas:

```python
def pendientes(cfg: Config, prom: Prometheus, ahora: float) -> list[str]:
    """Líneas de /pendientes (sin recortar). `prom` es la fuente de Prometheus del bot."""
    out, decididas, juez, av = _calcular(cfg, prom, ahora)
    if not out and not decididas and av.lineas:
        return av.lineas  # sin datos no se puede decir que no haya nada pendiente
    lineas = (out or ["Nada pendiente ✅"]) + _seccion(DECIDIDO, decididas)
    n = sum(1 for _, e in juez.estado() if e != VIGENTE)
    if n:
        que = "decisión obsoleta o vencida" if n == 1 else "decisiones obsoletas o vencidas"
        lineas.append(f"{n} {que}: vigia decisiones --limpiar")
    return lineas + av.lineas


def estado_decisiones(cfg: Config, prom: Prometheus, ahora: float) -> list[tuple[Decision, str]]:
    """Cada decisión con su estado (`vigia decisiones`). Si falta algún dato, FuenteError: sin datos, una
    decisión parecería obsoleta sin serlo."""
    _, _, juez, av = _calcular(cfg, prom, ahora)
    if av.lineas:
        raise FuenteError("; ".join(av.lineas))
    return juez.estado()
```

(`_seccion` ya pone el título en negrita y no devuelve nada si la lista está vacía. El bloque va después de las secciones, así que `recortar` lo quita antes que lo pendiente.)

- [ ] **Step 4: Comprobar que pasan.** Run: `uv run pytest tests/test_bot_pendientes.py tests/test_bot_comandos.py -q && uv run ruff check src/vigia/bot && uv run mypy src/vigia/bot`. Expected: PASS y sin errores. Si `test_pendientes_con_decisiones` falla solo por el orden de las líneas decididas, el orden correcto es el de las secciones (soporte, versiones, imágenes, digest): ajustar el código, no el test.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/pendientes.py tests/test_bot_pendientes.py
git commit -m "feat: /pendientes saca lo decidido en un bloque con el motivo (vigia-3j2)"
```

### Task 7: `vigia decisiones [--limpiar] [--yes]`

**Files:** Modify: `src/vigia/cli.py`; Create: `tests/test_cli_decisiones.py`

- [ ] **Step 1: Tests que fallan** (`tests/test_cli_decisiones.py`):

```python
"""vigia decisiones contra un Prometheus falso (datos sintéticos)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from vigia import cli
from vigia.bot import consultas as c
from vigia.bot.fuentes import FuenteError

from .bot_fakes import fake_http
from .conftest import EXAMPLE


@pytest.fixture
def sitio(tmp_path: Path) -> Path:
    shutil.copytree(EXAMPLE, tmp_path / "s")
    (tmp_path / "s" / "decisiones.yaml").write_text(
        "# cabecera\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: prometheus, ofrecido: v3.15.1, motivo: LTS}\n"
        "- {seccion: imagenes, host: Nodo 1, objeto: grafana, ofrecido: 13.3.0, motivo: vieja}\n",
        encoding="utf-8",
    )
    return tmp_path / "s" / "site.yaml"


def _prom(monkeypatch: pytest.MonkeyPatch, caido: bool = False) -> None:
    datos = {c.IMAGENES: [({"nombre": "Nodo 1", "contenedor": "prometheus", "tipo": "tag",
                            "local": "v3.13.5", "remota": "v3.15.1"}, 1)]}
    http = fake_http(datos, prom_caido=caido)

    def falso(url: str, **kw: Any) -> Any:
        assert url.startswith("http://10.99.0.10:9390/")  # monitor del ejemplo
        return http(url.replace("http://10.99.0.10:9390/", "http://prometheus:9090/"), **kw)

    monkeypatch.setattr(cli, "http_json", falso)


def test_estado(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch)
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio)])
    assert r.exit_code == 0, r.output
    assert "[vigente] imagenes · Nodo 1 · prometheus v3.15.1" in r.output
    assert "[obsoleta] imagenes · Nodo 1 · grafana 13.3.0" in r.output


def test_limpiar(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch)
    f = sitio.parent / "decisiones.yaml"
    antes = f.read_text(encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio), "--limpiar"])
    assert r.exit_code == 0 and "-- {seccion: imagenes, host: Nodo 1, objeto: grafana" in r.output
    assert f.read_text(encoding="utf-8") == antes  # sin --yes, solo diff
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio), "--limpiar", "--yes"])
    assert r.exit_code == 0
    assert f.read_text(encoding="utf-8") == antes.replace(antes.splitlines(keepends=True)[2], "")


def test_prometheus_caido(sitio: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prom(monkeypatch, caido=True)
    r = CliRunner().invoke(cli.app, ["decisiones", "-s", str(sitio)])
    assert r.exit_code == 1 and "no responde" in r.output
```

- [ ] **Step 2: Comprobar que fallan.** Run: `uv run pytest tests/test_cli_decisiones.py -q`. Expected: FAIL (no existe el comando `decisiones`).

- [ ] **Step 3: Implementación** (`src/vigia/cli.py`). Importar arriba:

```python
import dataclasses
import difflib
import json
import time

from .bot import config as bot_cfg
from .bot.decisiones import VIGENTE
from .bot.fuentes import FuenteError, Prometheus, http_json
from .bot.pendientes import estado_decisiones
from .build import bot_config
from .decisiones import load_decisiones, quitar_entradas
```

(Si alguno ya está importado, no duplicarlo.) Y el comando:

```python
@app.command()
def decisiones(
    site: SiteOpt = Path("site.yaml"),
    limpiar: Annotated[bool, typer.Option("--limpiar", help="quita las obsoletas y vencidas (diff)")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="con --limpiar, escribe el fichero")] = False,
) -> None:
    """Estado de las decisiones de /pendientes contra el Prometheus del sitio."""
    s = _load(site)
    rel = s.modulos.bot.decisiones
    if not rel:
        typer.echo("el sitio no declara `modulos.bot.decisiones`", err=True)
        raise typer.Exit(1)
    path = site.parent / rel
    try:
        lista = load_decisiones(path, [h.display_name for h in s.hosts])
    except (OSError, ValueError) as e:
        typer.echo(f"{rel}: {e}", err=True)
        raise typer.Exit(1) from None
    url = f"http://{s.monitor_host.ip}:{s.monitor.puertos.prometheus}"
    cfg = bot_cfg.desde_dict(json.loads(bot_config(s, lista)), {}, sin_telegram=True)
    cfg = dataclasses.replace(cfg, prometheus=url)
    try:
        estados = estado_decisiones(cfg, Prometheus(url, http_json), time.time())
    except FuenteError as e:
        typer.echo(f"Prometheus ({url}) no responde o le faltan datos: {e}", err=True)
        raise typer.Exit(1) from None
    for d, e in estados:
        extra = (f" {d.ofrecido}" if d.ofrecido else "") + (f" (revisar {d.revisar:%d-%m-%Y})" if d.revisar else "")
        typer.echo(f"[{e}] {d.seccion} · {d.host} · {d.objeto}{extra}")
    if not limpiar:
        return
    quitar = {i for i, (_, e) in enumerate(estados) if e != VIGENTE}
    if not quitar:
        typer.echo("nada que limpiar")
        return
    antes = path.read_text(encoding="utf-8")
    try:
        despues = quitar_entradas(antes, quitar)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo("".join(difflib.unified_diff(antes.splitlines(True), despues.splitlines(True), str(rel), str(rel))))
    if yes:
        path.write_text(despues, encoding="utf-8")
        typer.echo(f"{rel}: {len(quitar)} decisiones quitadas")
    else:
        typer.echo("(solo diff: añade --yes para escribir)")
```

- [ ] **Step 4: Comprobar que pasan.** Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy src`. Expected: todo PASS y sin errores.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/cli.py tests/test_cli_decisiones.py
git commit -m "feat: vigia decisiones dice qué decisiones siguen vigentes y limpia las demás (vigia-3j2)"
```

### Task 8: Documentación

**Files:** Modify: `docs/bot.md`, `src/vigia/claude/skills/vigia/SKILL.md`

- [ ] **Step 1: `docs/bot.md`**: añadir una sección «Decisiones en /pendientes» tras la de `/pendientes`, con: para qué sirve; cómo se declara (`modulos.bot.decisiones: decisiones.yaml`); el formato (copiar el ejemplo YAML de la spec, con `host1`); la tabla de coincidencia de la spec; que una decisión nunca oculta un ⚠ ni silencia alertas; la caducidad (`ofrecido`, `revisar`) y los comandos `vigia decisiones` y `vigia decisiones --limpiar [--yes]`.

- [ ] **Step 2: `SKILL.md`**: en la parte del bot, una viñeta: «Si el usuario decide no actuar sobre algo de /pendientes, apuntarlo en el `decisiones.yaml` del sitio (seccion, host, objeto, ofrecido o revisar, motivo, ref) y desplegar el monitor; `vigia decisiones` dice cuáles siguen vigentes (docs/bot.md)».

- [ ] **Step 3: Literales y tests.** Run: `uv run pytest -q`. Expected: PASS (incluye el control de literales prohibidos del golden).

- [ ] **Step 4: Commit**

```bash
git add docs/bot.md src/vigia/claude/skills/vigia/SKILL.md
git commit -m "docs: decisiones en /pendientes (vigia-3j2)"
```

### Task 9: Aplicarlo en el sitio de desarrollo (repo del sitio, no de vigia)

**Files (repo del sitio):** Create: `monitor/decisiones.yaml`; Modify: `monitor/site.yaml`

- [ ] **Step 1:** Crear `monitor/decisiones.yaml` con las decisiones vigentes del sitio (las que el usuario ya ha tomado), por ejemplo la de Prometheus en la LTS, la etiqueta más concreta de Valkey y la revisión del soporte de Grafana, cada una con su `ref` de beads.
- [ ] **Step 2:** En `monitor/site.yaml`, añadir `decisiones: decisiones.yaml` a `modulos.bot`.
- [ ] **Step 3:** Desde `monitor/`: `uv sync --reinstall-package vigia`, `uv run vigia validate` (Expected: «… N decisiones»), `uv run vigia decisiones` (Expected: todas `[vigente]`), `uv run vigia skill ..` y `uv run vigia deploy monitor` (Expected: diff en `bot/config.json` y en el código del bot).
- [ ] **Step 4:** El usuario lanza `! cd monitor && uv run vigia deploy monitor --yes` y comprueba `/pendientes` en Telegram.
- [ ] **Step 5:** Commit en el repo del sitio: `feat: decisiones de /pendientes`.
