# Política de rama por producto — plan de implementación (vigia-y5q)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que el catálogo de ciclos declare «este producto sigue su LTS» con un motivo, y que la alerta de
imágenes nuevas, el panel «Mantenimiento» y `/pendientes` dejen de ofrecer tags de ramas cortas.

**Architecture:** campo `politica` en `Producto` (`ciclos.py`); `ciclos.reglas` genera la tabla constante
`vigia_politica_ciclo` y la derivada `vigia_imagen_descartada` a partir de `wud_containers`; alerta y panel
la restan con `unless`, y el bot la lee para pasar las líneas a «Decidido». El sitio puede desactivarla con
`ciclos.politica: {producto: todas}`.

**Tech Stack:** Python 3.12, pydantic 2, PromQL (reglas de grabación), pytest, `promtool test rules` (por
Docker con `VIGIA_PROMTOOL`), uv.

Spec: `docs/superpowers/specs/2026-11-03-politica-rama-design.md`.

Comprobaciones de cada tarea (desde la raíz del repo): `uv run pytest -q`, `uv run ruff check .`,
`uv run ruff format --check <ficheros tocados>`, `uv run mypy .` (hay un error previo en
`tests/test_cli_decisiones.py:46` que no es de este trabajo). Promtool:

```bash
VIGIA_PROMTOOL='docker run --rm -u {uid} -v {dir}:{dir} -w {dir} --entrypoint promtool prom/prometheus:v3.13.5' \
  uv run pytest -q tests/test_ciclos_promtool.py
```

Commits: tipo en inglés, descripción en castellano, `(vigia-y5q)` al final, **sin** `Co-Authored-By`.

---

### Task 1: `politica` en el catálogo

**Files:**
- Modify: `src/vigia/ciclos.py` (nuevo `Politica`, campo en `Producto`, validación en `Producto._check`)
- Modify: `src/vigia/catalogo/prometheus.yaml`
- Test: `tests/test_ciclos.py`

- [ ] **Step 1: tests que fallan** — añadir al final de `tests/test_ciclos.py`:

```python
POLITICA = {"rama": "lts", "motivo": "seguimos la LTS"}


def _con_politica(**cambios: Any) -> dict[str, Any]:
    base = _producto(imagen_regex=IMAGEN, ejemplos_imagen={"x/nasos:3.1": "3", "nasos:3": None}, politica=POLITICA)
    base["ciclos"][1]["lts"] = True  # el ciclo 2 es la LTS
    return base | cambios


def test_politica_de_rama() -> None:
    p = Producto.model_validate(_con_politica())
    assert p.politica is not None and p.politica.rama == "lts"
    assert ciclos.catalogo()["prometheus"].politica is not None


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"ciclos": [{"ciclo": "3", "publicado": "2025-05-01"}]}, "ningún ciclo LTS"),
        ({"imagen_regex": None, "ejemplos_imagen": {}}, "imagen_regex"),
        ({"politica": {"rama": "lts", "motivo": 'con "comillas"'}}, "motivo"),
        ({"politica": {"rama": "estable", "motivo": "x"}}, "rama"),
    ],
)
def test_politica_invalida(cambios: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        Producto.model_validate(_con_politica(**cambios))


def test_actualizar_conserva_la_politica() -> None:
    p = Producto.model_validate(_con_politica(fuente="endoflife", endoflife="nas-os", referencia=None))
    nuevo = ciclos.desde_endoflife(p, fetch=lambda _url: _respuesta(), hoy=date(2026, 10, 1))
    assert nuevo.politica == p.politica
```

(`_respuesta()` es el helper que ya usa `test_desde_endoflife`; su ciclo 3 sale `lts: True`, así que la
validación pasa.)

- [ ] **Step 2: comprobar que fallan**

Run: `uv run pytest -q tests/test_ciclos.py -k politica`
Expected: FAIL (`politica` es un campo extra: `extra_forbidden`).

- [ ] **Step 3: implementación** — en `src/vigia/ciclos.py`, antes de `class Producto`:

```python
Texto = Annotated[str, StringConstraints(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f`$\\{}<>\"]*$")]
"""Texto que va en etiquetas de Prometheus y en el bot: sin comillas, llaves, `$` ni `<>`."""


class Politica(_Base):
    """Qué ramas de un producto ofrece vigia (docs/ciclos.md, «Política de rama»)."""

    rama: Literal["lts"]
    """`lts`: no se ofrecen etiquetas de ciclos no LTS a quien ya está en una LTS."""
    motivo: Texto
```

En `Producto`, tras `aviso_version`:

```python
    politica: Politica | None = None
    """Política de rama de las imágenes de este producto; sin ella se ofrecen todas las ramas."""
```

Al final de `Producto._check`, antes de `return self`:

```python
        if self.politica and not any(c.lts for c in self.ciclos):
            raise ValueError("`politica` con rama lts sin ningún ciclo LTS")
        if self.politica and not self.imagen_regex:
            raise ValueError("`politica` solo se aplica a imágenes: falta `imagen_regex`")
```

En `src/vigia/catalogo/prometheus.yaml`, tras `aviso_version: false`:

```yaml
politica:
  rama: lts
  motivo: vigia sigue la LTS de Prometheus; las demás ramas duran 6 semanas
```

- [ ] **Step 4: comprobar que pasan**

Run: `uv run pytest -q tests/test_ciclos.py`
Expected: PASS. Si el mensaje de `motivo` o `rama` no casa, ajustar el `match` al texto real de pydantic
(contiene el nombre del campo).

- [ ] **Step 5: commit**

```bash
git add src/vigia/ciclos.py src/vigia/catalogo/prometheus.yaml tests/test_ciclos.py
git commit -m "feat: política de rama por producto en el catálogo de ciclos (vigia-y5q)"
```

---

### Task 2: `ciclos.politica` en `site.yaml`

**Files:**
- Modify: `src/vigia/model.py` (`class Ciclos` ~l. 914; validación junto a `ciclos.fecha_aviso` ~l. 1147)
- Test: `tests/test_ciclos.py`

- [ ] **Step 1: tests que fallan**

```python
def test_sitio_desactiva_la_politica(example_data: dict[str, Any]) -> None:
    example_data["ciclos"] = {"politica": {"prometheus": "todas"}}
    assert Site.model_validate(example_data).ciclos.politica == {"prometheus": "todas"}


@pytest.mark.parametrize("producto", ["no-existe", "debian"])  # debian no tiene política
def test_sitio_politica_sin_politica_en_el_catalogo(example_data: dict[str, Any], producto: str) -> None:
    example_data["ciclos"] = {"politica": {producto: "todas"}}
    with pytest.raises(ValidationError, match="sin política de rama"):
        Site.model_validate(example_data)
```

- [ ] **Step 2:** `uv run pytest -q tests/test_ciclos.py -k "sitio and politica"` → FAIL.

- [ ] **Step 3: implementación** — en `class Ciclos`:

```python
    politica: dict[Id, Literal["todas"]] = {}
    """Por producto: `todas` ofrece todas las ramas aunque el catálogo siga solo la LTS."""
```

(`Literal` ya se importa en `model.py`; si no, añadirlo de `typing`.) En el validador del sitio, tras el
bloque de `ciclos.fecha_aviso`:

```python
        cat = catalogo_ciclos()
        sin = sorted(p for p in self.ciclos.politica if p not in cat or cat[p].politica is None)
        if sin:
            errors.append(f"ciclos.politica: productos sin política de rama en el catálogo: {sin}")
```

- [ ] **Step 4:** `uv run pytest -q tests/test_ciclos.py tests/test_model.py` → PASS.

- [ ] **Step 5: commit**

```bash
git add src/vigia/model.py tests/test_ciclos.py
git commit -m "feat: el sitio puede seguir todas las ramas de un producto (vigia-y5q)"
```

---

### Task 3: reglas de grabación

**Files:**
- Modify: `src/vigia/ciclos.py` (constantes, `_descartadas`, `reglas`; docstring del módulo)
- Modify: `src/vigia/build.py:254`
- Test: `tests/test_ciclos.py`, `tests/test_ciclos_promtool.py`

- [ ] **Step 1: test unitario que falla** (`tests/test_ciclos.py`):

```python
def test_reglas_de_politica() -> None:
    p = Producto.model_validate(_con_politica())
    rules = _reglas({p.producto: p})
    tabla = [r["labels"] for r in rules if r["record"] == ciclos.POLITICA_CICLO]
    assert tabla == [
        {"producto": "nas-os", "ciclo": "3", "lts": "false", "motivo": "seguimos la LTS"},
        {"producto": "nas-os", "ciclo": "2", "lts": "true", "motivo": "seguimos la LTS"},
    ]
    (d,) = [r for r in rules if r["record"] == ciclos.DESCARTADA]
    assert d["labels"] == {"producto": "nas-os"}
    assert d["expr"].startswith("max by (nombre, contenedor, local, remota, producto, motivo)")
    assert 'wud_containers{nueva="true", tipo="tag"}' in d["expr"]
    sin = _reglas({p.producto: p}, politica={"nas-os": "todas"})
    assert not [r for r in sin if r["record"] in (ciclos.POLITICA_CICLO, ciclos.DESCARTADA)]
```

- [ ] **Step 2:** `uv run pytest -q tests/test_ciclos.py -k reglas_de_politica` → FAIL (`POLITICA_CICLO`).

- [ ] **Step 3: implementación** — constantes junto a las demás:

```python
POLITICA_CICLO = "vigia_politica_ciclo"
DESCARTADA = "vigia_imagen_descartada"
```

Docstring del módulo: añadir a la lista de constantes
`vigia_politica_ciclo{producto, ciclo, lts, motivo}   1 por ciclo de un producto con política de rama` y a
las derivadas `vigia_imagen_descartada{nombre, contenedor, local, remota, producto, motivo}   imagen nueva
que la política no ofrece`.

Tras `_desde_contenedor`:

```python
def _descartadas(p: Producto) -> str:
    """Imágenes nuevas (What's Up Docker) que la política no ofrece: la local está en una LTS y la remota en
    un ciclo conocido que no lo es. Con otra cosa (tag sin versión, ciclo desconocido) se avisa como siempre."""
    assert p.imagen_regex
    rx = _promql(p.imagen_regex)
    e = 'wud_containers{nueva="true", tipo="tag"}'
    e = _replace(e, "producto", p.producto)
    e = f'label_join({e}, "img_local", ":", "imagen", "local")'
    e = f'label_join({e}, "img_remota", ":", "imagen", "remota")'
    e = _replace(e, "v_local", "$1", "img_local", rx)
    e = _replace(e, "v_remota", "$1", "img_remota", rx)
    e = _replace(e, "ciclo", "$1", "v_local", p.regex_promql)
    e = _replace(e, "ciclo_remota", "$1", "v_remota", p.regex_promql)
    tabla = f"{POLITICA_CICLO}{{producto={_q(p.producto)}"
    lts = tabla + ', lts="true"}'
    corta = _replace(tabla + ', lts="false"}', "ciclo_remota", "$1", "ciclo", "(.*)")
    e = f"({e} * on (producto, ciclo) group_left (motivo) {lts})"
    e = f"({e} * on (producto, ciclo_remota) group_left () {corta})"
    return f"max by (nombre, contenedor, local, remota, producto, motivo) ({e})"
```

En `reglas`: nuevo parámetro y su uso.

```python
def reglas(
    catalogo: Catalogo,
    fecha_aviso: Mapping[str, FechaAviso] | None = None,
    soporte_dias: int = 90,
    politica: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """…(docstring actual)…

    `politica`: productos en que el sitio sigue todas las ramas (`todas`): sin sus reglas de política."""
    fecha_aviso = fecha_aviso or {}
    politica = politica or {}
    con_politica = [p for p in catalogo.values() if p.politica and politica.get(p.producto) != "todas"]
```

Dentro del bucle de `tabla`, al final de cada producto (`for p in catalogo.values()`):

```python
        if p in con_politica:
            assert p.politica
            for c in p.ciclos:
                tabla.append(
                    _regla(
                        POLITICA_CICLO, 1, producto=p.producto, ciclo=c.ciclo,
                        lts="true" if c.lts else "false", motivo=p.politica.motivo,
                    )
                )
```

(`Producto` es `frozen`, así que es hashable y `p in con_politica` funciona; si mypy protesta, usar un
`set` de ids `{p.producto for p in con_politica}`.) Tras `derivadas`:

```python
    derivadas += [
        {"record": DESCARTADA, "expr": _descartadas(p), "labels": {"producto": p.producto}} for p in con_politica
    ]
```

En `src/vigia/build.py:254`:

```python
        ciclos.reglas(
            ciclos.catalogo(),
            s.ciclos.fecha_aviso,
            s.alertas.umbrales.soporte_dias,
            politica=s.ciclos.politica,
        ),
```

- [ ] **Step 4:** `uv run pytest -q tests/test_ciclos.py` → PASS.

- [ ] **Step 5: test con Prometheus de verdad** — en `tests/test_ciclos_promtool.py`, tras `_windows`:

```python
def _wud(contenedor: str, imagen: str, local: str, remota: str) -> dict[str, str]:
    return {
        "series": f'wud_containers{{nombre="srv-1", contenedor="{contenedor}", imagen="{imagen}", '
        f'local="{local}", remota="{remota}", nueva="true", tipo="tag", job="imagenes"}}',
        "values": "1 1",
    }
```

y al final del fichero:

```python
def test_imagenes_descartadas_por_la_politica(tmp_path: Path, example_data: dict[str, Any]) -> None:
    cmd = _promtool(tmp_path)
    if not cmd:
        pytest.skip("sin promtool (ver VIGIA_PROMTOOL)")
    (tmp_path / "ciclos.yml").write_text(yaml.safe_dump(ciclos.reglas(ciclos.catalogo())), encoding="utf-8")
    politica = ciclos.catalogo()["prometheus"].politica
    assert politica is not None
    (alerta,) = [r for r in alerting.image_rules(Site.model_validate(example_data)) if r["uid"] == "vigia-imagen-version"]
    expr = f"({alerta['data'][0]['model']['expr']}) > 0"

    def img(c: str, imagen: str, local: str, remota: str) -> dict[str, str]:
        return {"nombre": "srv-1", "contenedor": c, "imagen": imagen, "local": local, "remota": remota}

    descartada = img("prom-lts", "prom/prometheus", "v3.13.5", "v3.15.1")
    avisan = [
        img("prom-parche", "prom/prometheus", "v3.13.5", "v3.13.6"),  # misma LTS
        img("prom-corta", "prom/prometheus", "v3.14.0", "v3.15.1"),  # la local no es LTS: debe moverse
        img("prom-nueva", "prom/prometheus", "v3.13.5", "v9.9.0"),  # ciclo que el catálogo no conoce
        img("grafana", "grafana/grafana-oss", "13.0.2", "13.3.0"),  # producto sin política
    ]
    del_d = {k: v for k, v in descartada.items() if k != "imagen"}
    pruebas = [
        _muestras(
            ciclos.DESCARTADA,
            [{"labels": f"{ciclos.DESCARTADA}" + _lbl(del_d | {"producto": "prometheus", "motivo": politica.motivo}), "value": 1}],
        ),
        _muestras(expr, [{"labels": _lbl(m), "value": 1} for m in avisan]),
    ]
    prueba = {
        "rule_files": ["ciclos.yml"],
        "evaluation_interval": f"{HORAS}h",
        "tests": [
            {
                "interval": f"{HORAS}h",
                "input_series": [_wud(**{k: m[k] for k in ("contenedor", "imagen", "local", "remota")}) for m in [descartada, *avisan]],
                "promql_expr_test": pruebas,
            }
        ],
    }
    (tmp_path / "prueba.yml").write_text(yaml.safe_dump(prueba, sort_keys=False), encoding="utf-8")
    res = subprocess.run([*cmd, "test", "rules", "prueba.yml"], cwd=tmp_path, capture_output=True, text=True)  # noqa: S603
    assert res.returncode == 0, res.stdout + res.stderr


def _lbl(m: dict[str, str]) -> str:
    return "{" + ", ".join(f'{k}="{v}"' for k, v in m.items()) + "}"
```

Notas: la serie grabada lleva además la etiqueta `producto` de la regla (ya incluida). El orden de
`exp_samples` no importa en promtool. Este test falla hasta la Task 4 (la alerta aún no resta las
descartadas): en esta tarea comprobar solo la primera muestra comentando la segunda, o hacer la Task 4 antes
del commit — lo más simple es **commitear las Tasks 3 y 4 juntas**.

- [ ] **Step 6:** ejecutar promtool (comando de la cabecera) → la parte de `DESCARTADA` pasa; la de la alerta
falla con `prom-lts` de más. Seguir con la Task 4.

---

### Task 4: alerta y panel restan las descartadas

**Files:**
- Modify: `src/vigia/alerting.py` (`image_rules`, ~l. 408)
- Modify: `src/vigia/dashboards/mantenimiento.py` (`_imagenes`, ~l. 111)
- Test: `tests/test_alerting.py`, `tests/test_dashboards.py`

- [ ] **Step 1: tests que fallan**

En `tests/test_alerting.py::test_reglas_de_imagenes`, tras la primera aserción:

```python
    assert "unless on (nombre, contenedor, remota) vigia_imagen_descartada" in (
        rules["vigia-imagen-version"]["data"][0]["model"]["expr"]
    )
```

En `tests/test_dashboards.py::test_panel_de_mantenimiento`, tras la aserción de títulos:

```python
    (imgs,) = [p for p in d["panels"] if p["title"] == "Imágenes nuevas"]
    assert "unless on (nombre, contenedor, remota) vigia_imagen_descartada" in json.dumps(imgs)
```

(importar `json` si el fichero no lo hace).

- [ ] **Step 2:** `uv run pytest -q tests/test_alerting.py tests/test_dashboards.py` → FAIL.

- [ ] **Step 3: implementación** — en `src/vigia/ciclos.py`, junto a `DESCARTADA`:

```python
SIN_DESCARTADAS = f"unless on (nombre, contenedor, remota) {DESCARTADA}"
"""Lo que se añade a una consulta de wud_containers para no ofrecer lo que la política descarta."""
```

En `alerting.image_rules` (`alerting.py` ya importa `ciclos`):

```python
            f'max by ({por}) (wud_containers{{nueva="true", tipo="tag"}} {ciclos.SIN_DESCARTADAS})',
```

y en el comentario de esa regla añadir: «sin las que descarta la política de rama del catálogo».

En `dashboards/mantenimiento.py::_imagenes` (importar `from vigia import ciclos` si no está):

```python
        [
            (
                "max by (nombre, contenedor, imagen, tipo, local, remota) "
                f'(wud_containers{{nueva="true"}} {ciclos.SIN_DESCARTADAS})',
                "_",
            )
        ],
```

- [ ] **Step 4:** `uv run pytest -q tests/test_alerting.py tests/test_dashboards.py tests/test_ciclos.py` →
PASS, y promtool (comando de la cabecera) → PASS los dos tests.

- [ ] **Step 5: golden** — `VIGIA_UPDATE_GOLDEN=1 uv run pytest -q tests/test_build_golden.py`; revisar
`git diff tests/golden/`: solo deben cambiar `ciclos.yml` (tabla `vigia_politica_ciclo` de Prometheus y la
regla `vigia_imagen_descartada`), la regla de alerta `vigia-imagen-version` y la consulta del panel.

- [ ] **Step 6: commit**

```bash
git add src/vigia/ciclos.py src/vigia/build.py src/vigia/alerting.py src/vigia/dashboards/mantenimiento.py \
  tests/test_ciclos.py tests/test_ciclos_promtool.py tests/test_alerting.py tests/test_dashboards.py tests/golden
git commit -m "feat: alerta y panel no ofrecen imágenes fuera de la rama del catálogo (vigia-y5q)"
```

---

### Task 5: `/pendientes` las muestra en «Decidido»

**Files:**
- Modify: `src/vigia/bot/consultas.py` (junto a `IMAGENES`, l. 55)
- Modify: `src/vigia/bot/pendientes.py` (import y bucle de tags, ~l. 178-193)
- Test: `tests/test_bot_pendientes.py`

- [ ] **Step 1: tests que fallan** (al final de `tests/test_bot_pendientes.py`):

```python
PROM_LTS: dict[str, Serie] = {
    c.IMAGENES: [(_nodo("Nodo 1", contenedor="prometheus", tipo="tag", local="v3.13.5", remota="v3.15.1"), 1)],
    c.DESCARTADAS: [
        (_nodo("Nodo 1", contenedor="prometheus", remota="v3.15.1", motivo="vigia sigue la LTS"), 1)
    ],
}


def test_imagen_descartada_por_vigia() -> None:
    texto = responder("/pendientes", contexto(PROM_LTS)) or ""
    assert texto.splitlines() == [
        "Nada pendiente ✅",
        "<b>✔ Decidido (no hace falta hacer nada)</b>",
        "Nodo 1 · prometheus v3.13.5 → v3.15.1 — vigia sigue la LTS (vigia)",
    ]


def test_la_decision_del_sitio_gana_a_la_de_vigia() -> None:
    dec = (Decision("imagenes", "Nodo 1", "prometheus", "lo nuestro", ofrecido="v3.15.1"),)
    ctx = contexto(PROM_LTS, decisiones=dec)
    assert "Nodo 1 · prometheus v3.13.5 → v3.15.1 — lo nuestro" in (responder("/pendientes", ctx) or "")
    assert [e for _, e in estado_decisiones(ctx.cfg, ctx.prom, ctx.ahora())] == [VIGENTE]
```

- [ ] **Step 2:** `uv run pytest -q tests/test_bot_pendientes.py` → FAIL (`DESCARTADAS`).

- [ ] **Step 3: implementación** — `consultas.py`, tras `IMAGENES`:

```python
DESCARTADAS = "max by (nombre, contenedor, remota, motivo) (vigia_imagen_descartada)"
"""Imágenes nuevas que la política de rama del catálogo no ofrece (vigia.ciclos.DESCARTADA)."""
```

`pendientes.py`: importar `DESCARTADAS` junto a `IMAGENES` y, en la sección de imágenes:

```python
    imgs = q(IMAGENES)
    descartes = {(m.get("nombre"), m.get("contenedor"), m.get("remota")): m.get("motivo", "") for m, _ in q(DESCARTADAS)}
    ...
        d = juez.busca("imagenes", m, m.get("remota"))
        motivo = descartes.get((m.get("nombre"), m.get("contenedor"), m.get("remota")))
        if d:
            decididas.append(linea + _motivo(d))
        elif motivo is not None:
            decididas.append(f"{linea} — {esc(motivo)} (vigia)")
        else:
            lineas.append(linea)
```

(el sitio va primero: su decisión es más concreta y sigue contando como usada).

Añadir un test de consistencia en `tests/test_bot_pendientes.py`, como el de consumibles:

```python
def test_descartadas_es_la_serie_del_catalogo() -> None:
    from vigia import ciclos

    assert ciclos.DESCARTADA in c.DESCARTADAS
```

- [ ] **Step 4:** `uv run pytest -q tests/test_bot_*.py` → PASS (el falso Prometheus devuelve vacío para
consultas que no tiene, así que los tests previos no cambian).

- [ ] **Step 5: commit**

```bash
git add src/vigia/bot/consultas.py src/vigia/bot/pendientes.py tests/test_bot_pendientes.py
git commit -m "feat: /pendientes pasa a Decidido lo que descarta la política de rama (vigia-y5q)"
```

---

### Task 6: documentación y cierre

**Files:**
- Modify: `docs/ciclos.md` (sección nueva «Política de rama» tras «En el sitio»; filas en la tabla de «En Prometheus»)
- Modify: `docs/imagenes.md` (tabla «Avisos»)
- Modify: `docs/bot.md` («Decisiones en /pendientes»)
- Modify: `CHANGELOG.md` (sección «Sin publicar» arriba, o la que use el repo)

- [ ] **Step 1: `docs/ciclos.md`**, nueva sección:

~~~markdown
## Política de rama

Un producto del catálogo puede declarar qué ramas ofrece vigia:

```yaml
politica: {rama: lts, motivo: "vigia sigue la LTS de Prometheus; las demás ramas duran 6 semanas"}
```

Con `rama: lts`, si un contenedor está en un ciclo LTS y What's Up Docker ofrece una etiqueta de un ciclo
conocido que no lo es (`v3.13.5` → `v3.15.1`), no salta «Versión nueva de una imagen», no aparece en el panel
«Mantenimiento» y `/pendientes` la pone en «Decidido» con el motivo y `(vigia)`. Una versión nueva de la misma
LTS (`v3.13.6`) o una LTS nueva sí se ofrecen. Si el contenedor ya está fuera de la LTS no se descarta nada.

Para que un sitio siga todas las ramas:

```yaml
ciclos:
  politica: {prometheus: todas}
```
~~~

En la tabla de «En
Prometheus», dos filas: `vigia_politica_ciclo{producto, ciclo, lts, motivo}` y
`vigia_imagen_descartada{nombre, contenedor, local, remota, producto, motivo}`.

- [ ] **Step 2: `docs/imagenes.md`** — en la fila de «Versión nueva de una imagen» añadir: «salvo las que
descarta la política de rama del catálogo (docs/ciclos.md)».

- [ ] **Step 3: `docs/bot.md`** — en «Decisiones en /pendientes», un párrafo: «Lo que descarta la política de
rama del catálogo (docs/ciclos.md) sale también en Decidido, con `(vigia)` al final; no hace falta escribirlo
en `decisiones.yaml`. Si el sitio tiene su propia decisión para la misma línea, se muestra la suya.»

- [ ] **Step 4: `CHANGELOG.md`** — entrada nueva arriba:

```markdown
## Sin publicar

- **Nuevo**: política de rama en el catálogo. Prometheus sigue su LTS: ya no se ofrece la 3.15 a quien está en
  la 3.13 (ni alerta, ni panel, ni `/pendientes`, donde sale en «Decidido»). Un sitio puede seguir todas las
  ramas con `ciclos.politica: {prometheus: todas}`. Si tenías una decisión en `decisiones.yaml` para eso, sobra:
  `vigia decisiones --limpiar`.
- **Arreglo**: la plantilla de sitio fija Prometheus en la LTS 3.13.5 (la 3.15 pierde el soporte el 06-11-2026).
```

- [ ] **Step 5: comprobación completa** — `uv run pytest -q`, promtool, `uv run ruff check .`,
`uv run ruff format --check` de los ficheros tocados, `uv run mypy .` (solo el error previo).

- [ ] **Step 6: commit**

```bash
git add docs/ciclos.md docs/imagenes.md docs/bot.md CHANGELOG.md
git commit -m "docs: política de rama del catálogo (vigia-y5q)"
```
