# Tareas programadas por textfile — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** vigia vigila tareas programadas (copias de seguridad…) que dejan su estado en ficheros `.prom` del
colector textfile de node_exporter: alertas de retraso, error y sin datos, y un panel «Tareas» (vigia-86m).

**Architecture:** `tareas:` y `node_exporter.textfile` en el modelo; un módulo `vigia/tareas.py` con la carpeta
y las expresiones PromQL por tarea (compartidas por alertas y panel); el compose añade el parámetro del
colector y el script de despliegue crea la carpeta. Spec: `docs/superpowers/specs/2026-10-28-tareas-textfile-design.md`.

**Tech Stack:** Python 3.12, pydantic v2, Jinja2 (compose), PromQL, provisioning de Grafana; pytest, ruff, mypy, uv.

Comandos desde `~/minube/red_de_casa/vigia`. Antes de cada commit: `uv run ruff check . && uv run ruff format --check src tests && uv run mypy src`.
Sin `Co-Authored-By` en los commits. Si un test golden falla por un cambio intencionado:
`VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py` y revisar el `git diff tests/golden`.

---

## Mapa de ficheros

| Fichero | Cambio |
|---------|--------|
| `src/vigia/model.py` | `NodeExporter(Exporter)` con `textfile`; `Tarea`; `Site.tareas`; validación cruzada |
| `src/vigia/tareas.py` (nuevo) | `TEXTFILE_DIR`, `textfile_activo(h)` y expresiones PromQL por tarea |
| `src/vigia/templates/compose/_agents.j2` | `--collector.textfile.directory` si `textfile` |
| `src/vigia/deploy/__init__.py` | `Unit.textfile` y `install -d` antes del `up` |
| `src/vigia/alerting.py` | tres reglas de tareas |
| `src/vigia/dashboards/tasks.py` (nuevo) | panel «Tareas» |
| `src/vigia/dashboards/__init__.py` | registra `tareas.json` |
| `examples/sitio-ejemplo/site.yaml` | `textfile: true` en nodo1 y nodo2, dos tareas |
| `tests/test_model.py`, `tests/test_tareas.py` (nuevo), `tests/test_deploy.py`, `tests/test_alerting.py`, `tests/test_dashboards.py`, `tests/golden/` | tests |
| `docs/tareas.md` (nuevo), `docs/alertas.md`, `README.md`, `src/vigia/claude/skills/vigia/SKILL.md`, `CHANGELOG.md` | documentación |

---

### Task 1: Modelo (`textfile`, `tareas`, validación)

**Files:**
- Modify: `src/vigia/model.py` (clase `Exporter` ~l. 228, `Host` ~l. 316, `Site` ~l. 826 y `_cross_validate`)
- Test: `tests/test_model.py`

- [ ] **Step 1: Tests que fallan** — al final de `tests/test_model.py`:

```python
def _con_tareas(d: dict[str, Any]) -> dict[str, Any]:
    d["hosts"][2]["node_exporter"]["textfile"] = True  # nodo2
    d["tareas"] = [{"nombre": "copias-bd", "host": "nodo2", "max_horas": 26}]
    return d


def test_tareas_validas(example_data: dict[str, Any]) -> None:
    s = _validate(_con_tareas(example_data))
    assert s.tareas[0].max_horas == 26
    assert s.get_host("nodo2").node_exporter.textfile  # type: ignore[union-attr]


def test_textfile_solo_en_node_exporter(example_data: dict[str, Any]) -> None:
    example_data["hosts"][4]["windows_exporter"]["textfile"] = True  # puesto1
    _assert_invalid(example_data, "Extra inputs are not permitted")


def test_tarea_host_desconocido(example_data: dict[str, Any]) -> None:
    _con_tareas(example_data)["tareas"][0]["host"] = "nodo9"
    _assert_invalid(example_data, "tarea copias-bd: host desconocido")


def test_tarea_host_sin_textfile(example_data: dict[str, Any]) -> None:
    _con_tareas(example_data)["tareas"][0]["host"] = "nodo1"
    _assert_invalid(example_data, "tarea copias-bd: nodo1 no tiene node_exporter con `textfile: true`")


def test_tareas_repetidas(example_data: dict[str, Any]) -> None:
    d = _con_tareas(example_data)
    d["tareas"].append(dict(d["tareas"][0]))
    _assert_invalid(d, "tareas repetidas")


@pytest.mark.parametrize("horas", [0, 745])
def test_tarea_max_horas_fuera_de_rango(example_data: dict[str, Any], horas: int) -> None:
    _con_tareas(example_data)["tareas"][0]["max_horas"] = horas
    _assert_invalid(example_data, "max_horas")
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_model.py -q -k "tarea or textfile"`
Expected: FAIL (`tareas`/`textfile`: «Extra inputs are not permitted» en los válidos; los de error no encuentran su texto).

- [ ] **Step 3: Implementación** en `src/vigia/model.py`:

Tras `class Exporter`:

```python
class NodeExporter(Exporter):
    textfile: bool = False
    """Lee los `.prom` de la carpeta de tareas (vigia.tareas.TEXTFILE_DIR). En `gestion: externo`, el
    administrador ya ha añadido `--collector.textfile.directory` a ese exporter."""
```

En `Host`: `node_exporter: NodeExporter | None = None` (en lugar de `Exporter | None`).

Antes de `class Site` (junto a `Bridge`):

```python
class Tarea(Base):
    """Tarea programada que deja su estado en el textfile de node_exporter de su host."""

    nombre: Id
    host: Id
    max_horas: int = Field(ge=1, le=744)
    """Horas máximas sin una ejecución correcta antes de avisar."""
```

En `Site`, tras `bridges`:

```python
    tareas: list[Tarea] = []
    """Tareas programadas (copias…) vigiladas por el textfile de node_exporter ([docs/tareas.md])."""
```

En `_cross_validate`, antes de `if errors:`:

```python
        nombres = [t.nombre for t in self.tareas]
        if len(nombres) != len(set(nombres)):
            errors.append(f"tareas repetidas: {sorted({n for n in nombres if nombres.count(n) > 1})}")
        for t in self.tareas:
            th = hosts_by_id.get(t.host)
            if th is None:
                errors.append(f"tarea {t.nombre}: host desconocido {t.host!r}")
            elif not (th.node_exporter and th.node_exporter.textfile):
                errors.append(f"tarea {t.nombre}: {t.host} no tiene node_exporter con `textfile: true`")
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_model.py -q && uv run mypy src`
Expected: todo PASS; mypy sin errores.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/model.py tests/test_model.py
git commit -m "feat(tareas): textfile en node_exporter y tareas en el modelo (vigia-86m)"
```

---

### Task 2: Módulo `vigia/tareas.py` (carpeta y expresiones)

**Files:**
- Create: `src/vigia/tareas.py`
- Test: `tests/test_tareas.py`

- [ ] **Step 1: Tests que fallan** — `tests/test_tareas.py`:

```python
"""Expresiones PromQL por tarea: cada término filtra por el host (`nombre`) y la tarea declarados."""

from __future__ import annotations

from typing import Any

from vigia.model import Site
from vigia.tareas import TEXTFILE_DIR, edad_horas, margen, resultado, retraso, sin_datos, textfile_activo


def _site(d: dict[str, Any]) -> Site:
    d["hosts"][1]["node_exporter"]["textfile"] = True  # nodo1 (nombre «Nodo 1»)
    d["hosts"][2]["node_exporter"]["textfile"] = True  # nodo2
    d["tareas"] = [
        {"nombre": "copias-bd", "host": "nodo2", "max_horas": 26},
        {"nombre": "informe", "host": "nodo1", "max_horas": 30},
    ]
    return Site.model_validate(d)


SEL_BD = 'nombre="nodo2", tarea="copias-bd"'
SEL_INF = 'nombre="Nodo 1", tarea="informe"'


def test_carpeta() -> None:
    assert TEXTFILE_DIR == "/var/lib/vigia/textfile"


def test_textfile_activo(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    assert textfile_activo(s.get_host("nodo2"))
    example_data["hosts"][2]["node_exporter"]["gestion"] = "externo"
    example_data["tareas"] = []
    assert not textfile_activo(Site.model_validate(example_data).get_host("nodo2"))


def test_edad_y_margen_por_tarea(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    ts_bd = f"max by (nombre, tarea) (vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_BD}}})"
    assert edad_horas(s) == (
        f"(time() - {ts_bd}) / 3600"
        " or (time() - max by (nombre, tarea) "
        f"(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_INF}}})) / 3600"
    )
    assert retraso(s).split(" or ")[0] == f"(time() - {ts_bd}) / 3600 - 26"
    assert margen(s).split(" or ")[0] == f"26 - (time() - {ts_bd}) / 3600"


def test_resultado_y_sin_datos(example_data: dict[str, Any]) -> None:
    s = _site(example_data)
    assert resultado(s).split(" or ")[:2] == [
        f"max by (nombre, tarea) (vigia_tarea_ultimo_resultado{{{SEL_BD}}})",
        f"2 * absent(vigia_tarea_ultimo_resultado{{{SEL_BD}}})",
    ]
    assert sin_datos(s) == (
        f"absent(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_BD}}})"
        f" or absent(vigia_tarea_ultimo_exito_timestamp_seconds{{{SEL_INF}}})"
    )


def test_escapa_el_nombre_del_host(example_data: dict[str, Any]) -> None:
    example_data["hosts"][2]["nombre"] = 'Nodo "dos"'
    assert 'nombre="Nodo \\"dos\\""' in sin_datos(_site(example_data))
```

(Si `Text` no admite comillas dobles, `test_escapa_el_nombre_del_host` fallará en la validación: en ese caso
se borra ese test, porque el escape no es alcanzable; `promql_escape` se mantiene igualmente.)

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_tareas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.tareas'`.

- [ ] **Step 3: Implementación** — `src/vigia/tareas.py`:

```python
"""Tareas programadas vigiladas por el colector textfile de node_exporter (docs/tareas.md).

Cada tarea escribe en TEXTFILE_DIR/<tarea>.prom (atómico: .prom.tmp + mv):
  vigia_tarea_ultimo_exito_timestamp_seconds{tarea="…"}  epoch de la última ejecución correcta
  vigia_tarea_ultimo_resultado{tarea="…"}                0 = bien, 1 = error
Prometheus añade `nombre` (el host). Las expresiones se unen con `or`, un término por tarea declarada y
filtrado por su host: una tarea con el mismo nombre en otro host no cuenta.
"""

from __future__ import annotations

from collections.abc import Callable

from vigia.dashboards.base import promql_escape
from vigia.model import Host, Site, Tarea

TEXTFILE_DIR = "/var/lib/vigia/textfile"
EXITO = "vigia_tarea_ultimo_exito_timestamp_seconds"
RESULTADO = "vigia_tarea_ultimo_resultado"


def textfile_activo(h: Host) -> bool:
    """vigia despliega el node_exporter de `h` con el colector textfile (y crea la carpeta)."""
    ne = h.node_exporter
    return bool(ne and ne.gestion == "vigia" and ne.textfile)


def _sel(s: Site, t: Tarea) -> str:
    return f'nombre="{promql_escape(s.get_host(t.host).display_name)}", tarea="{promql_escape(t.nombre)}"'


def _por_tarea(s: Site, term: Callable[[Tarea, str], str]) -> str:
    return " or ".join(term(t, _sel(s, t)) for t in s.tareas)


def _edad(sel: str) -> str:
    return f"(time() - max by (nombre, tarea) ({EXITO}{{{sel}}})) / 3600"


def edad_horas(s: Site) -> str:
    """Horas desde la última ejecución correcta de cada tarea."""
    return _por_tarea(s, lambda t, sel: _edad(sel))


def retraso(s: Site) -> str:
    """Horas de más sobre `max_horas` (> 0 = retrasada)."""
    return _por_tarea(s, lambda t, sel: f"{_edad(sel)} - {t.max_horas}")


def margen(s: Site) -> str:
    """Horas que quedan hasta `max_horas` (< 0 = retrasada), para el panel."""
    return _por_tarea(s, lambda t, sel: f"{t.max_horas} - {_edad(sel)}")


def resultado(s: Site) -> str:
    """Último resultado: 0 bien, 1 error, 2 sin datos (no ha escrito nunca)."""
    return _por_tarea(
        s, lambda t, sel: f"max by (nombre, tarea) ({RESULTADO}{{{sel}}}) or 2 * absent({RESULTADO}{{{sel}}})"
    )


def ultimo_error(s: Site) -> str:
    """Último resultado de cada tarea (solo las que han escrito)."""
    return _por_tarea(s, lambda t, sel: f"max by (nombre, tarea) ({RESULTADO}{{{sel}}})")


def sin_datos(s: Site) -> str:
    """1 por cada tarea declarada que no ha escrito nunca su métrica de éxito."""
    return _por_tarea(s, lambda t, sel: f"absent({EXITO}{{{sel}}})")
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_tareas.py -q && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/tareas.py tests/test_tareas.py
git commit -m "feat(tareas): carpeta textfile y expresiones PromQL por tarea (vigia-86m)"
```

---

### Task 3: Compose con el colector textfile

**Files:**
- Modify: `src/vigia/templates/compose/_agents.j2` (macro `node_exporter`)
- Test: `tests/test_tareas.py`

- [ ] **Step 1: Test que falla** — añadir a `tests/test_tareas.py`:

```python
def test_compose_con_textfile(example_data: dict[str, Any]) -> None:
    from vigia.build import build_site

    from .conftest import EXAMPLE

    s = _site(example_data)
    out = build_site(s, EXAMPLE)
    flag = "--collector.textfile.directory=/host/var/lib/vigia/textfile"
    assert flag in out["agentes/nodo2.yml"]
    assert flag in out["ejemplo_monitor.yml"]  # nodo1 es el host del monitor
    example_data["hosts"][2]["node_exporter"]["textfile"] = False
    example_data["tareas"] = [t for t in example_data["tareas"] if t["host"] != "nodo2"]
    assert flag not in build_site(Site.model_validate(example_data), EXAMPLE)["agentes/nodo2.yml"]
```

- [ ] **Step 2: Comprobar que falla**

Run: `uv run pytest tests/test_tareas.py::test_compose_con_textfile -q`
Expected: FAIL (`assert flag in …`).

- [ ] **Step 3: Implementación** — en `_agents.j2`, tras la línea `--collector.filesystem.mount-points-exclude=…`:

```jinja
{% if h.node_exporter.textfile %}
      - '--collector.textfile.directory=/host/var/lib/vigia/textfile'
{% endif %}
```

(Mismo valor que `TEXTFILE_DIR` con el prefijo `/host`: `--path.rootfs` no se aplica al textfile.)

- [ ] **Step 4: Comprobar que pasa**

Run: `uv run pytest tests/test_tareas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/templates/compose/_agents.j2 tests/test_tareas.py
git commit -m "feat(tareas): node_exporter con el colector textfile (vigia-86m)"
```

---

### Task 4: El despliegue crea la carpeta

**Files:**
- Modify: `src/vigia/deploy/__init__.py` (`Unit`, `units`, `deploy_script`)
- Test: `tests/test_deploy.py`

- [ ] **Step 1: Test que falla** — al final de `tests/test_deploy.py`:

```python
def test_carpeta_textfile_solo_si_hace_falta(example_data: dict[str, Any]) -> None:
    example_data["tareas"] = []  # el ejemplo trae textfile en nodo1 y nodo2 (Task 7)
    example_data["hosts"][1]["node_exporter"]["textfile"] = False
    example_data["hosts"][2]["node_exporter"]["textfile"] = False
    s, built = _built(example_data)
    assert "/var/lib/vigia/textfile" not in deploy_script(units(s, built)["agentes:nodo2"], "/tmp/vigia.x")
    example_data["hosts"][2]["node_exporter"]["textfile"] = True
    s, built = _built(example_data)
    script = deploy_script(units(s, built)["agentes:nodo2"], "/tmp/vigia.x")
    assert "install -d -m 755 /var/lib/vigia/textfile" in script
    assert script.index("install -d") < script.index("up -d")
    assert "/var/lib/vigia/textfile" not in deploy_script(units(s, built)["monitor"], "/tmp/vigia.x")
    subprocess.run(["bash", "-n"], input=script.encode(), check=True)
```

- [ ] **Step 2: Comprobar que falla**

Run: `uv run pytest tests/test_deploy.py::test_carpeta_textfile_solo_si_hace_falta -q`
Expected: FAIL (no aparece `install -d`).

- [ ] **Step 3: Implementación** en `src/vigia/deploy/__init__.py`:

Import: `from vigia.tareas import TEXTFILE_DIR, textfile_activo`.

En `Unit`, nuevo campo al final:

```python
    textfile: bool = False
    """Su node_exporter lee la carpeta de tareas: se crea antes del `up`."""
```

En `units()`: en el `Unit("monitor", …)` añadir `textfile=textfile_activo(mon),`; en el de agentes,
`Unit(f"agentes:{h.id}", h, h.deploy, f"{h.id}-agentes", f"agentes/{h.id}.yml", textfile=textfile_activo(h))`.

Nueva función junto a `_restart_script`:

```python
def _textfile_script(u: Unit) -> str:
    """Carpeta de las tareas (idempotente). Sin root (compose sin sudo) avisa y sigue: la alerta «Tarea sin
    datos» lo hará visible."""
    if not u.textfile:
        return ""
    d = q(TEXTFILE_DIR)
    return (
        f"install -d -m 755 {d} 2>/dev/null || "
        f'echo "aviso: no se pudo crear {TEXTFILE_DIR}; créala como root (install -d -m 755 {TEXTFILE_DIR})" >&2'
    )
```

En `deploy_script`, en `parts`, entre `_sync_script(u, up)` y `_up_script(u, up)`: `_textfile_script(u),`.

- [ ] **Step 4: Comprobar que pasa**

Run: `uv run pytest tests/test_deploy.py -q && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/deploy/__init__.py tests/test_deploy.py
git commit -m "feat(tareas): el despliegue crea la carpeta del textfile (vigia-86m)"
```

---

### Task 5: Alertas de tareas

**Files:**
- Modify: `src/vigia/alerting.py` (`rules`, nueva `task_rules`)
- Test: `tests/test_alerting.py`

- [ ] **Step 1: Tests que fallan** — al final de `tests/test_alerting.py`:

```python
def _con_tareas(d: dict[str, Any]) -> dict[str, Any]:
    d["hosts"][2]["node_exporter"]["textfile"] = True
    d["tareas"] = [{"nombre": "copias-bd", "host": "nodo2", "max_horas": 26}]
    return d


def test_reglas_de_tareas(example_data: dict[str, Any]) -> None:
    rules = _rules(_build(_con_tareas(example_data)))
    sel = 'nombre="nodo2", tarea="copias-bd"'
    r = rules["vigia-tarea-retrasada"]
    assert r["data"][0]["model"]["expr"].endswith(f"{{{sel}}})) / 3600 - 26")
    assert r["data"][1]["model"]["conditions"][0]["evaluator"] == {"type": "gt", "params": [0]}
    assert rules["vigia-tarea-error"]["data"][0]["model"]["expr"] == (
        f"max by (nombre, tarea) (vigia_tarea_ultimo_resultado{{{sel}}})"
    )
    assert rules["vigia-tarea-sin-datos"]["for"] == "1h"
    assert "absent(" in rules["vigia-tarea-sin-datos"]["data"][0]["model"]["expr"]


def test_sin_tareas_no_hay_reglas_de_tareas(example_data: dict[str, Any]) -> None:
    example_data["tareas"] = []
    assert not any(uid.startswith("vigia-tarea") for uid in _rules(_build(example_data)))
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_alerting.py -q -k tareas`
Expected: FAIL con `KeyError: 'vigia-tarea-retrasada'`.

- [ ] **Step 3: Implementación** en `src/vigia/alerting.py`:

Import: `from vigia import tareas`.

En `rules()`, tras `if s.printers_snmp: out += printer_rules(s)`:

```python
    if s.tareas:
        out += task_rules(s)
```

Nueva función tras `printer_rules`:

```python
def task_rules(s: Site) -> list[dict[str, Any]]:
    tarea = '{{ index .Labels "nombre" }}: la tarea {{ index .Labels "tarea" }}'
    return [
        _rule(
            "vigia-tarea-retrasada",
            "Tarea sin éxito reciente",
            tareas.retraso(s),
            "gt",
            0,
            "5m",
            tarea + " no termina bien desde hace demasiado"
            "{{ with .Values.A }} ({{ humanize .Value }} h de más){{ end }}",
        ),
        _rule(
            "vigia-tarea-error",
            "Tarea con error",
            tareas.ultimo_error(s),
            "gt",
            0,
            "0s",
            tarea + " acabó con error en su última ejecución",
        ),
        _rule(
            "vigia-tarea-sin-datos",
            "Tarea sin datos",
            tareas.sin_datos(s),
            "gt",
            0,
            "1h",
            tarea + " no ha escrito nunca su métrica (¿script instalado? ¿textfile activo?)",
        ),
    ]
```

- [ ] **Step 4: Comprobar que pasan** (incluido `test_solo_variables_y_sin_dolar_propio`)

Run: `uv run pytest tests/test_alerting.py -q && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/alerting.py tests/test_alerting.py
git commit -m "feat(tareas): alertas de tarea retrasada, con error y sin datos (vigia-86m)"
```

---

### Task 6: Panel «Tareas»

**Files:**
- Create: `src/vigia/dashboards/tasks.py`
- Modify: `src/vigia/dashboards/__init__.py` (import y `dashboards_for`)
- Test: `tests/test_dashboards.py`

- [ ] **Step 1: Tests que fallan** — al final de `tests/test_dashboards.py`:

```python
def test_panel_tareas(example_data: dict[str, Any]) -> None:
    example_data["tareas"] = []
    assert "tareas.json" not in _gen(example_data)
    example_data["hosts"][2]["node_exporter"]["textfile"] = True
    example_data["tareas"] = [{"nombre": "copias-bd", "host": "nodo2", "max_horas": 26}]
    d = _gen(example_data)["tareas.json"]
    assert d["uid"] == "ejm-tareas" and d["title"] == "Ejemplo · Tareas"
    table = d["panels"][1]
    assert table["type"] == "table"
    exprs = [t["expr"] for t in table["targets"]]
    assert len(exprs) == 3 and "absent(" in exprs[2]
    renames = table["transformations"][1]["options"]["renameByName"]
    assert renames["nombre"] == "Host" and renames["tarea"] == "Tarea"
    assert table["options"]["sortBy"] == [{"displayName": "Host", "desc": False}]
```

- [ ] **Step 2: Comprobar que falla**

Run: `uv run pytest tests/test_dashboards.py::test_panel_tareas -q`
Expected: FAIL con `KeyError: 'tareas.json'`.

- [ ] **Step 3: Implementación** — `src/vigia/dashboards/tasks.py`:

```python
"""Panel «Tareas»: tareas programadas que escriben su estado en el textfile de node_exporter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vigia import tareas
from vigia.dashboards.base import Panel, merged_table, row

if TYPE_CHECKING:
    from vigia.dashboards import Brand
    from vigia.model import Site

RESULTADO = [
    {
        "type": "value",
        "options": {
            "0": {"text": "bien", "color": "green"},
            "1": {"text": "error", "color": "red"},
            "2": {"text": "sin datos", "color": "text"},
        },
    }
]


def tasks(s: Site, m: Brand) -> dict[str, Any] | None:
    if not s.tareas:
        return None
    table = merged_table(
        2,
        "Tareas programadas",
        [
            (tareas.edad_horas(s), "Último éxito (h)"),
            (tareas.margen(s), "Margen (h)"),
            (tareas.resultado(s), "Resultado"),
        ],
        0,
        1,
        24,
        max(4, 2 + len(s.tareas)),
        key="Host",
    )
    table["transformations"][1]["options"]["renameByName"]["tarea"] = "Tarea"
    table["options"]["sortBy"] = [{"displayName": "Host", "desc": False}]
    table["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byName", "options": "Último éxito (h)"},
            "properties": [{"id": "decimals", "value": 1}],
        },
        {
            "matcher": {"id": "byName", "options": "Margen (h)"},
            "properties": [
                {"id": "decimals", "value": 1},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {
                    "id": "thresholds",
                    "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}]},
                },
            ],
        },
        {
            "matcher": {"id": "byName", "options": "Resultado"},
            "properties": [
                {"id": "mappings", "value": RESULTADO},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
            ],
        },
    ]
    panels: list[Panel] = [row(1, "Tareas", 0), table]
    return m.dash("tareas", "Tareas", panels, time_from="now-7d")
```

En `src/vigia/dashboards/__init__.py`: `from vigia.dashboards import devices, externals, extra, printers, tasks`
y en `gen`, tras `"externos.json"`: `"tareas.json": tasks.tasks(s, m),`.

- [ ] **Step 4: Comprobar que pasan** (también `test_branding_everywhere`)

Run: `uv run pytest tests/test_dashboards.py -q && uv run ruff format src/vigia/dashboards/tasks.py && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/dashboards/tasks.py src/vigia/dashboards/__init__.py tests/test_dashboards.py
git commit -m "feat(tareas): panel «Tareas» (vigia-86m)"
```

---

### Task 7: Sitio de ejemplo y golden

**Files:**
- Modify: `examples/sitio-ejemplo/site.yaml`
- Modify: `tests/golden/sitio-ejemplo/` (regenerado)

- [ ] **Step 1:** En `site.yaml`: `node_exporter: {puerto: 9100, textfile: true}` en `nodo1` y `nodo2`, y tras
`servicios:` (antes de `web:`):

```yaml
# Tareas programadas que escriben su estado en el textfile de node_exporter (docs/tareas.md).
tareas:
  - {nombre: copias-bd, host: nodo2, max_horas: 26}
  - {nombre: informe-diario, host: nodo1, max_horas: 30}
```

- [ ] **Step 2: Golden**

Run: `uv run pytest -q` → falla `test_golden`. Luego `VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py -q`
y `git diff --stat tests/golden`.
Expected: cambian `agentes/nodo2.yml`, `ejemplo_monitor.yml` (parámetro textfile), `grafana-provisioning/alerting/vigia.yml`
(3 reglas) y aparece `dashboards/tareas.json`. Nada más.

- [ ] **Step 3:** `test_reglas_del_ejemplo` (tests/test_alerting.py) espera el conjunto exacto de reglas: añadir
`"vigia-tarea-retrasada", "vigia-tarea-error", "vigia-tarea-sin-datos"` a ese `set`. En
`test_sin_web_ni_nodos_no_hay_reglas_de_certificado_ni_disco` quitar también `example_data["tareas"] = []`
(al quitar los node_exporter las tareas quedarían sin host válido): añadir esa línea al principio del test.
Si algún otro test quita `node_exporter` de nodo1/nodo2, añadir igual `example_data["tareas"] = []`.

Run: `uv run pytest -q`
Expected: todo PASS.

- [ ] **Step 4: Commit**

```bash
git add examples/sitio-ejemplo/site.yaml tests/
git commit -m "test(tareas): tareas en el sitio de ejemplo y golden (vigia-86m)"
```

---

### Task 8: Documentación

**Files:**
- Create: `docs/tareas.md`
- Modify: `docs/alertas.md` (tabla), `README.md` (Qué sabe vigilar), `src/vigia/claude/skills/vigia/SKILL.md`, `CHANGELOG.md`

- [ ] **Step 1:** `docs/tareas.md`:

````markdown
# Tareas programadas

vigia avisa si una tarea programada (una copia de seguridad, un informe…) deja de terminar bien. Cada tarea
deja su estado en un fichero que lee el colector *textfile* de node_exporter.

## En el sitio

```yaml
hosts:
  - id: srv-1
    node_exporter: {puerto: 9100, textfile: true}
tareas:
  - {nombre: copias-postgres, host: srv-1, max_horas: 26}
```

- Con `gestion: vigia`, el despliegue añade `--collector.textfile.directory` al node_exporter y crea
  `/var/lib/vigia/textfile` (si el usuario de despliegue no es root ni tiene sudo, avisa: créala tú).
- Con `gestion: externo`, añade tú al exporter `--collector.textfile.directory=/var/lib/vigia/textfile`
  (paquete de Debian/Raspbian: en `ARGS` de `/etc/default/prometheus-node-exporter`).
- `max_horas`: margen sin una ejecución correcta antes de avisar (para una tarea diaria, 26).

## En la tarea

Al terminar, la tarea escribe `/var/lib/vigia/textfile/<tarea>.prom` de forma atómica:

```bash
#!/usr/bin/env bash
# uso: vigia-tarea.sh <tarea> <orden…>   (como root, p. ej. desde un servicio de systemd)
set -u
tarea=$1; shift
dir=/var/lib/vigia/textfile; f=$dir/$tarea.prom
"$@"; rc=$?
ok=$(awk '/^vigia_tarea_ultimo_exito_timestamp_seconds/ {print $2}' "$f" 2>/dev/null)
[ "$rc" -eq 0 ] && ok=$(date +%s)
{
  [ -n "$ok" ] && echo "vigia_tarea_ultimo_exito_timestamp_seconds{tarea=\"$tarea\"} $ok"
  echo "vigia_tarea_ultimo_resultado{tarea=\"$tarea\"} $(( rc != 0 ))"
} > "$f.tmp" && mv "$f.tmp" "$f"
exit "$rc"
```

En un error se conserva la hora del último éxito. Ejemplo con systemd:

```ini
# /etc/systemd/system/copias-postgres.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/vigia-tarea.sh copias-postgres /usr/local/bin/copias-postgres.sh
```

## Alertas y panel

| Alerta | Cuándo |
|--------|--------|
| Tarea sin éxito reciente | han pasado más de `max_horas` desde la última ejecución correcta (5 min) |
| Tarea con error | la última ejecución acabó con error |
| Tarea sin datos | la tarea no ha escrito nunca su métrica (1 h): script sin instalar, textfile inactivo o errata en el nombre |

Panel «Tareas»: horas desde el último éxito, margen hasta `max_horas` y resultado de cada tarea.
````

- [ ] **Step 2:** En `docs/alertas.md`, tras la fila «Error de impresora»:

```markdown
| Tarea sin éxito reciente · con error · sin datos | `tareas` ([tareas.md](tareas.md)) | más de `max_horas` sin éxito, última ejecución con error, o nunca ha escrito su métrica |
```

En `README.md`, tras el párrafo de impresoras: `Tareas programadas (copias de seguridad…) por el textfile de node_exporter: [docs/tareas.md](docs/tareas.md).`

En `SKILL.md`, tras la línea de SNMP v3 (~l. 57):

```markdown
  - Tareas programadas (copias…): `node_exporter: {…, textfile: true}` y `tareas: [{nombre, host, max_horas}]`;
    la tarea escribe su `.prom` (envoltorio en docs/tareas.md).
```

En `CHANGELOG.md`, bajo «Sin publicar»:

```markdown
- **Tareas programadas** (`tareas`, `node_exporter.textfile`): alertas de tarea retrasada, con error y sin datos,
  y panel «Tareas», con el colector textfile de node_exporter ([docs/tareas.md](docs/tareas.md)).
```

- [ ] **Step 3: Probar el envoltorio** en una carpeta temporal (sin root):

```bash
t=$(mktemp -d); sed -n '/^#!\/usr\/bin\/env bash/,/^exit/p' docs/tareas.md | sed "s#dir=/var/lib/vigia/textfile#dir=$t#" > "$t/w.sh"
bash "$t/w.sh" prueba true; cat "$t/prueba.prom"; bash "$t/w.sh" prueba false; cat "$t/prueba.prom"
```

Expected: primero éxito con timestamp y resultado 0; luego el mismo timestamp y resultado 1.

- [ ] **Step 4: Commit**

```bash
git add docs/tareas.md docs/alertas.md README.md src/vigia/claude/skills/vigia/SKILL.md CHANGELOG.md
git commit -m "docs(tareas): tareas programadas por textfile (vigia-86m)"
```

---

### Task 9: Verificación final

- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check src tests`, `uv run mypy src`: todo limpio.
- [ ] En un sitio real sin tareas: `uv sync -q --reinstall-package vigia && uv run vigia validate` en su carpeta:
  sigue válido y nada cambia en lo generado (`uv run vigia deploy monitor` muestra diff vacío).
- [ ] `bd close vigia-86m` con un resumen.
````
