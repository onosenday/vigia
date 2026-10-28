# Bot de comandos por Telegram — plan de implementación (vigia-c3b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** un servicio `bot` en el stack `monitor` de vigia que atiende comandos de consulta (`/estado`,
`/alertas`, `/host`, `/dispositivo`, `/info`, `/lista`, `/ayuda`) solo desde el chat de alertas.

**Architecture:** subpaquete `vigia.bot` (solo biblioteca estándar) que `vigia build` copia a `build/bot/`
con un `Dockerfile` y un `config.json` generado; el compose del monitor lo levanta con la imagen local
`vigia-bot:local`. Lee Prometheus (hosts y dispositivos de netinv) y la API de alertas de Grafana; habla con
Telegram por *long polling*.

**Tech Stack:** Python 3.12 (urllib, http.server, zoneinfo), pydantic (modelo), Jinja2 (compose), pytest,
ruff, mypy estricto.

**Spec:** `docs/superpowers/specs/2026-10-28-bot-comandos-design.md`.

**Reglas del repo** (`CLAUDE.md`): repo público, solo datos sintéticos (`10.99.0.0/24`, `ejemplo.lan`);
secretos solo por nombre de variable; commits en castellano con tipo en inglés y sin menciones a Claude.
Comandos de verificación: `uv run pytest`, `uv run ruff check .`, `uv run mypy .`.

---

## Mapa de ficheros

| Fichero | Acción | Responsabilidad |
|---------|--------|-----------------|
| `src/vigia/model.py` | modificar | `Bot` en `Modules` y validación cruzada |
| `src/vigia/bot/__init__.py` | crear | docstring del subpaquete |
| `src/vigia/bot/formato.py` | crear | escapado, recorte, horas, duraciones, porcentajes |
| `src/vigia/bot/buscar.py` | crear | normalización y búsqueda por nombre/IP/MAC |
| `src/vigia/bot/fuentes.py` | crear | `http_json`, `FuenteError`, `Prometheus`, `Grafana`, `Alerta` |
| `src/vigia/bot/config.py` | crear | `Config`, `HostCfg`, `load` |
| `src/vigia/bot/consultas.py` | crear | PromQL fijas, `Avisos`, `estado_host`, `Dispositivo`, `dispositivos` |
| `src/vigia/bot/comandos.py` | crear | `Contexto`, `parsear`, `responder` y cada comando |
| `src/vigia/bot/telegram.py` | crear | `Telegram`, `Mensajeria`, `clasificar`, `Limitador` |
| `src/vigia/bot/__main__.py` | crear | `Salud`, `servir_salud`, `Bucle`, `main` |
| `src/vigia/images/bot/Dockerfile` | crear | imagen del bot |
| `src/vigia/build.py` | modificar | `bot_config`, `_bot` y su llamada en `build_site` |
| `src/vigia/templates/compose/monitor.yml.j2` | modificar | servicio `bot` |
| `src/vigia/templates/prometheus/prometheus.yml.j2` | modificar | job `bot` |
| `src/vigia/deploy/__init__.py` | modificar | `bot` en `MONITOR_DIRS`/`RELOAD`; secreto del token de Grafana |
| `examples/sitio-ejemplo/site.yaml` | modificar | `modulos.bot` activo |
| `tests/golden/sitio-ejemplo/` | regenerar | golden con el bot |
| `tests/bot_fakes.py` | crear | config, http y contexto falsos |
| `tests/test_bot_*.py` | crear | tests de cada módulo |
| `tests/test_model.py`, `tests/test_deploy.py` | modificar | validación del bot; secreto sintético |
| `docs/bot.md`, `README.md`, `CHANGELOG.md` | crear/modificar | documentación |

---

### Task 1: Modelo — `modulos.bot`

**Files:**
- Modify: `src/vigia/model.py` (tras `class SnmpModule`, en `Modules` y en `Site._cross_validate`)
- Test: `tests/test_model.py`

- [ ] **Step 1: Tests que fallan** — añadir al final de `tests/test_model.py`:

```python
def test_bot_inactivo_por_defecto(example_data: dict[str, Any]) -> None:
    example_data["modulos"].pop("bot", None)
    assert not _validate(example_data).modulos.bot.activo


def test_bot_sin_telegram(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN"}
    del example_data["alertas"]["telegram"]
    _assert_invalid(example_data, "bot activo sin alertas por Telegram")


def test_bot_sin_token_de_grafana(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True}
    _assert_invalid(example_data, "bot activo sin `grafana_token`")


def test_bot_zona_no_valida(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN", "zona": "../etc"}
    _assert_invalid(example_data, "String should match pattern")


def test_bot_valido(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN"}
    b = _validate(example_data).modulos.bot
    assert (b.zona, b.puerto) == ("Europe/Madrid", 9466)
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_model.py -k bot -v`
Expected: FAIL (`Modules` no tiene `bot`: «Extra inputs are not permitted» / `AttributeError`).

- [ ] **Step 3: Implementación** — en `src/vigia/model.py`, tras `class SnmpModule`:

```python
Zona = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]+(/[A-Za-z0-9_+-]+){0,2}$")]
"""Zona horaria IANA (Europe/Madrid, UTC)."""


class Bot(Base):
    """Bot de consultas por Telegram en el chat de las alertas (solo lectura)."""

    activo: bool = False
    grafana_token: EnvVarName | None = None
    """Variable con un token de cuenta de servicio de Grafana con rol Viewer (alertas activas)."""
    zona: Zona = "Europe/Madrid"
    """Zona horaria de las horas que muestra."""
    puerto: Port = 9466
    """/metrics del bot, solo en la red interna del stack."""
```

En `class Modules`, añadir el campo al final:

```python
    bot: Bot = Bot()
```

En `Site._cross_validate`, justo después del bloque `if m.updates_exporter.activo: ...`:

```python
        if m.bot.activo:
            if not (self.alertas.activo and self.alertas.telegram):
                errors.append(
                    "bot activo sin alertas por Telegram: usa el bot y el chat de `alertas.telegram`"
                )
            if not m.bot.grafana_token:
                errors.append("bot activo sin `grafana_token` (token de Grafana con rol Viewer)")
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add src/vigia/model.py tests/test_model.py
git commit -m "feat(bot): modulos.bot en el modelo con su validación (vigia-c3b)"
```

---

### Task 2: `formato.py`

**Files:**
- Create: `src/vigia/bot/__init__.py`, `src/vigia/bot/formato.py`
- Test: `tests/test_bot_formato.py`

- [ ] **Step 1: Test que falla** — `tests/test_bot_formato.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vigia.bot.formato import MAX_CARACTERES, duracion, esc, hora, pct, recortar

Z = "Europe/Madrid"
TZ = ZoneInfo(Z)


def _ts(y: int, mo: int, d: int, h: int, mi: int) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_esc() -> None:
    assert esc("<b>&") == "&lt;b&gt;&amp;"


def test_recortar_lineas() -> None:
    t = recortar([str(i) for i in range(35)])
    assert len(t.splitlines()) == 30
    assert t.splitlines()[-1] == "… y 6 más"


def test_recortar_corto_sin_cambios() -> None:
    assert recortar(["a", "b"]) == "a\nb"


def test_recortar_caracteres_por_una_coma() -> None:
    t = recortar([", ".join(["nombre"] * 1000)])
    assert len(t) <= MAX_CARACTERES
    assert t.endswith("nombre …")


def test_duracion() -> None:
    assert duracion(42) == "42 s"
    assert duracion(23 * 60 + 5) == "23 min"
    assert duracion(3 * 3600 + 5 * 60) == "3 h 5 min"
    assert duracion(2 * 86400 + 3600) == "2 d 1 h"
    assert duracion(-5) == "0 s"


def test_hora() -> None:
    ahora = _ts(2026, 10, 28, 18, 0)
    assert hora(_ts(2026, 10, 28, 14, 5), ahora, Z) == "14:05"
    assert hora(_ts(2026, 10, 27, 23, 10), ahora, Z) == "ayer 23:10"
    assert hora(_ts(2026, 10, 20, 9, 0), ahora, Z) == "20-10 09:00"


def test_pct() -> None:
    assert pct(12.4) == "12%"
    assert pct(None) == "—"
```

- [ ] **Step 2: Comprobar que falla**

Run: `uv run pytest tests/test_bot_formato.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot'`.

- [ ] **Step 3: Implementación**

`src/vigia/bot/__init__.py`:

```python
"""Bot de consultas por Telegram (solo lectura). Solo biblioteca estándar: en su contenedor corre como el
paquete `vigia_bot`, sin vigia instalado, así que los módulos se importan entre sí de forma relativa."""
```

`src/vigia/bot/formato.py`:

```python
"""Textos del bot: HTML de Telegram escapado, compacto y con horas locales."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

MAX_LINEAS = 30
MAX_CARACTERES = 4000
"""Telegram admite 4096 caracteres por mensaje."""


def esc(v: object) -> str:
    return html.escape(str(v), quote=False)


def recortar(lineas: list[str], maximo: int = MAX_LINEAS) -> str:
    """Como mucho `maximo` líneas (la última dice cuántas faltan) y MAX_CARACTERES caracteres.

    El corte por caracteres se hace en un salto de línea o en «, » para no partir una entidad ni una etiqueta.
    """
    if len(lineas) > maximo:
        lineas = [*lineas[: maximo - 1], f"… y {len(lineas) - maximo + 1} más"]
    texto = "\n".join(lineas)
    if len(texto) <= MAX_CARACTERES:
        return texto
    limite = MAX_CARACTERES - 2
    corte = max(texto.rfind("\n", 0, limite), texto.rfind(", ", 0, limite))
    return texto[: corte if corte > 0 else limite] + " …"


def duracion(segundos: float) -> str:
    s = int(max(segundos, 0))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h {s % 3600 // 60} min"
    return f"{s // 86400} d {s % 86400 // 3600} h"


def hora(ts: float, ahora: float, zona: str) -> str:
    """14:05 si es hoy, «ayer 23:10» si fue ayer y «20-10 09:00» si es anterior."""
    tz = ZoneInfo(zona)
    t, n = datetime.fromtimestamp(ts, tz), datetime.fromtimestamp(ahora, tz)
    if t.date() == n.date():
        return t.strftime("%H:%M")
    if (n.date() - t.date()).days == 1:
        return "ayer " + t.strftime("%H:%M")
    return t.strftime("%d-%m %H:%M")


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}%"
```

- [ ] **Step 4: Comprobar que pasa**

Run: `uv run pytest tests/test_bot_formato.py -v && uv run ruff check src/vigia/bot && uv run mypy src/vigia/bot`
Expected: PASS, sin avisos.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot tests/test_bot_formato.py
git commit -m "feat(bot): formato de las respuestas (vigia-c3b)"
```

---

### Task 3: `buscar.py`

**Files:**
- Create: `src/vigia/bot/buscar.py`
- Test: `tests/test_bot_buscar.py`

- [ ] **Step 1: Test que falla** — `tests/test_bot_buscar.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from vigia.bot.buscar import buscar, normalizar


@dataclass(frozen=True)
class X:
    nombre: str
    ip: str
    mac: str


ITEMS = [
    X("Impresora Salón", "10.99.0.40", "aa:bb:cc:00:00:01"),
    X("Impresora Despacho", "10.99.0.41", "aa:bb:cc:00:00:02"),
    X("NAS", "10.99.0.20", "aa:bb:cc:00:00:03"),
    X("NAS 2", "10.99.0.21", "aa:bb:cc:00:00:04"),
]


def _claves(x: X) -> tuple[str, str, str]:
    return (x.nombre, x.ip, x.mac)


def test_normalizar() -> None:
    assert normalizar("  Salón ") == "salon"


def test_sin_acentos_ni_mayusculas() -> None:
    assert buscar("impresora salon", ITEMS, _claves) == [ITEMS[0]]


def test_ip_exacta() -> None:
    assert buscar("10.99.0.40", ITEMS, _claves) == [ITEMS[0]]


def test_mac_con_guiones() -> None:
    assert buscar("AA-BB-CC-00-00-03", ITEMS, _claves) == [ITEMS[2]]


def test_exacto_antes_que_contiene() -> None:
    assert buscar("nas", ITEMS, _claves) == [ITEMS[2]]


def test_ambiguo() -> None:
    assert buscar("impresora", ITEMS, _claves) == ITEMS[:2]


def test_vacio_y_sin_resultado() -> None:
    assert buscar("  ", ITEMS, _claves) == []
    assert buscar("tostadora", ITEMS, _claves) == []
```

- [ ] **Step 2: Comprobar que falla**

Run: `uv run pytest tests/test_bot_buscar.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot.buscar'`.

- [ ] **Step 3: Implementación** — `src/vigia/bot/buscar.py`:

```python
"""Búsqueda por nombre, IP o MAC sin distinguir mayúsculas ni acentos: primero exacta, luego «contiene»."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence

_MAC = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$")


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def _clave(texto: str) -> str:
    n = normalizar(texto)
    return n.replace("-", ":") if _MAC.match(n) else n


def buscar[T](consulta: str, items: Sequence[T], claves: Callable[[T], Iterable[str]]) -> list[T]:
    q = _clave(consulta)
    if not q:
        return []
    exactos = [i for i in items if q in {_clave(k) for k in claves(i) if k}]
    if exactos:
        return exactos
    return [i for i in items if any(q in _clave(k) for k in claves(i) if k)]
```

- [ ] **Step 4: Comprobar que pasa**

Run: `uv run pytest tests/test_bot_buscar.py -v && uv run ruff check src/vigia/bot && uv run mypy src/vigia/bot`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/buscar.py tests/test_bot_buscar.py
git commit -m "feat(bot): búsqueda por nombre, IP o MAC (vigia-c3b)"
```

---

### Task 4: `fuentes.py` y `config.py`

**Files:**
- Create: `src/vigia/bot/fuentes.py`, `src/vigia/bot/config.py`, `tests/bot_fakes.py`
- Test: `tests/test_bot_fuentes.py`

- [ ] **Step 1: Fakes y tests que fallan**

`tests/bot_fakes.py` (lo usan también las tareas siguientes; `Contexto` llega en la Task 5, así que de
momento **no** se define `contexto()`):

```python
"""Config, http y datos falsos del bot (sintéticos)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from vigia.bot.config import Config, HostCfg
from vigia.bot.fuentes import FuenteError, Http

ZONA = "Europe/Madrid"
TZ = ZoneInfo(ZONA)
CHAT = -1000000000001
Serie = list[tuple[dict[str, str], float]]


def ts(y: int, mo: int, d: int, h: int, mi: int) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


AHORA = ts(2026, 10, 28, 14, 28)

HOSTS = (
    HostCfg("nodo1", "Nodo 1", "10.99.0.10", "omv"),
    HostCfg("nodo2", "Nodo 2", "10.99.0.11", "linux"),
    HostCfg("nas", "NAS", "10.99.0.20", "synology"),
)


def cfg(**cambios: Any) -> Config:
    base: dict[str, Any] = {
        "sitio": "Ejemplo",
        "chat_id": CHAT,
        "zona": ZONA,
        "puerto": 9466,
        "prometheus": "http://prometheus:9090",
        "grafana": "http://grafana:3000",
        "netinv": True,
        "disco_pct": 90,
        "hosts": HOSTS,
        "telegram_token": "123456:token-sintetico",
        "grafana_token": "glsa_sintetico",
    }
    base.update(cambios)
    return Config(**base)


def fake_http(
    prom: Mapping[str, Serie] | None = None,
    alertas: list[dict[str, Any]] | None = None,
    prom_caido: bool = False,
    grafana_caida: bool = False,
) -> Http:
    """Prometheus responde `prom[expresión]`; Grafana, `alertas`. `*_caido` simula la fuente sin respuesta."""

    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        if url.startswith("http://prometheus:9090/"):
            if prom_caido:
                raise FuenteError("URLError")
            expr = parse_qs(urlsplit(url).query)["query"][0]
            result = [{"metric": m, "value": [AHORA, str(v)]} for m, v in (prom or {}).get(expr, [])]
            return {"status": "success", "data": {"resultType": "vector", "result": result}}
        if url.startswith("http://grafana:3000/"):
            if grafana_caida:
                raise FuenteError("HTTP 401")
            return alertas or []
        raise AssertionError(f"URL inesperada: {url}")

    return http
```

`tests/test_bot_fuentes.py`:

```python
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from vigia.bot.config import load
from vigia.bot.fuentes import ALERTAS_API, FuenteError, Grafana, Prometheus, http_json

from .bot_fakes import CHAT, fake_http, ts


def test_prometheus_query() -> None:
    http = fake_http({"up": [({"nombre": "Nodo 1"}, 1.0)]})
    assert Prometheus("http://prometheus:9090", http).query("up") == [({"nombre": "Nodo 1"}, 1.0)]


def test_prometheus_respuesta_de_error() -> None:
    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        return {"status": "error", "error": "parse error"}

    with pytest.raises(FuenteError):
        Prometheus("http://prometheus:9090", http).query("up")


def test_grafana_alertas_ordenadas_y_con_token() -> None:
    vistos: list[Mapping[str, str] | None] = []

    def http(
        url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        vistos.append(headers)
        assert url.endswith(ALERTAS_API)
        return [
            {"labels": {"alertname": "Disco casi lleno", "nombre": "Nodo 1"},
             "startsAt": "2026-10-28T13:20:00Z", "annotations": {"summary": "s"}},
            {"labels": {"alertname": "Caído", "nombre": "Nodo 2"},
             "startsAt": "2026-10-28T13:05:00.123456789Z", "annotations": {}},
        ]

    al = Grafana("http://grafana:3000", "glsa_x", http).alertas()
    assert [a.regla for a in al] == ["Caído", "Disco casi lleno"]
    assert abs(al[0].desde - (ts(2026, 10, 28, 14, 5) + 0.123456)) < 0.001
    assert vistos[0] == {"Authorization": "Bearer glsa_x"}


def test_grafana_sin_token() -> None:
    with pytest.raises(FuenteError):
        Grafana("http://grafana:3000", "", fake_http()).alertas()


def test_repr_sin_token() -> None:
    assert "glsa_x" not in repr(Grafana("http://grafana:3000", "glsa_x", fake_http()))


def test_http_json_no_filtra_la_url() -> None:
    with pytest.raises(FuenteError) as e:
        http_json("http://127.0.0.1:9/bot123456:SECRETO/getMe", timeout=2)
    assert "SECRETO" not in str(e.value) and "SECRETO" not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def _config_json(tmp_path: Path) -> Path:
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "sitio": "Ejemplo", "chat_id": CHAT, "zona": "Europe/Madrid", "puerto": 9466,
                "prometheus": "http://prometheus:9090", "grafana": "http://grafana:3000", "netinv": True,
                "disco_pct": 90,
                "hosts": [{"id": "nodo1", "nombre": "Nodo 1", "ip": "10.99.0.10", "tipo": "omv"}],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_config_load(tmp_path: Path) -> None:
    c = load(_config_json(tmp_path), {"TELEGRAM_TOKEN": "123:abc", "GRAFANA_TOKEN": "glsa_x"})
    assert c.chat_id == CHAT and c.hosts[0].nombre == "Nodo 1" and c.telegram_token == "123:abc"
    assert "123:abc" not in repr(c) and "glsa_x" not in repr(c)


def test_config_sin_token_de_telegram(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        load(_config_json(tmp_path), {})
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_fuentes.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot.config'`.

- [ ] **Step 3: Implementación**

`src/vigia/bot/fuentes.py`:

```python
"""HTTP de solo lectura a Prometheus y Grafana (y transporte de Telegram), con la biblioteca estándar.

Los errores nunca llevan la URL ni la excepción original: la URL de Telegram contiene el token del bot.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

MAX_RESPUESTA = 5_000_000
ALERTAS_API = "/api/alertmanager/grafana/api/v2/alerts?active=true&silenced=false&inhibited=false"


class FuenteError(Exception):
    """Una fuente no respondió o respondió algo inesperado. El texto es solo el tipo de fallo."""


class Http(Protocol):
    def __call__(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any: ...


def http_json(
    url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
) -> Any:
    """GET (o POST con `body` en JSON) y respuesta JSON."""
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URLs fijas de config.json
            return json.loads(r.read(MAX_RESPUESTA))
    except urllib.error.HTTPError as e:
        raise FuenteError(f"HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        raise FuenteError(type(e).__name__) from None


class Prometheus:
    def __init__(self, base: str, http: Http) -> None:
        self.base = base.rstrip("/")
        self.http = http

    def query(self, expr: str) -> list[tuple[dict[str, str], float]]:
        """Consulta instantánea: [(etiquetas, valor)]."""
        d = self.http(f"{self.base}/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
        try:
            if d["status"] != "success":
                raise FuenteError("consulta fallida")
            return [
                ({str(k): str(v) for k, v in r["metric"].items()}, float(r["value"][1]))
                for r in d["data"]["result"]
            ]
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise FuenteError("respuesta no válida") from None


@dataclass(frozen=True)
class Alerta:
    regla: str
    objeto: str
    """Etiqueta `nombre` (el host o servicio afectado)."""
    desde: float
    resumen: str


class Grafana:
    def __init__(self, base: str, token: str, http: Http) -> None:
        self.base = base.rstrip("/")
        self._token = token
        self.http = http

    def __repr__(self) -> str:
        return f"Grafana({self.base!r})"

    def alertas(self) -> list[Alerta]:
        """Alertas disparadas ahora (sin las silenciadas), de la más antigua a la más reciente."""
        if not self._token:
            raise FuenteError("sin token")
        d = self.http(self.base + ALERTAS_API, headers={"Authorization": f"Bearer {self._token}"})
        if not isinstance(d, list):
            raise FuenteError("respuesta no válida")
        out = []
        for a in d:
            if not isinstance(a, dict):
                continue
            lab, ann = a.get("labels") or {}, a.get("annotations") or {}
            out.append(
                Alerta(
                    str(lab.get("alertname", "")),
                    str(lab.get("nombre", "")),
                    _instante(str(a.get("startsAt", ""))),
                    str(ann.get("summary", "")),
                )
            )
        return sorted(out, key=lambda x: x.desde)


def _instante(v: str) -> float:
    """ISO 8601 de Grafana (nanosegundos y Z) a epoch; 0 si no se entiende."""
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v).timestamp()
    except ValueError:
        return 0.0
```

`src/vigia/bot/config.py`:

```python
"""Configuración del bot: config.json que genera `vigia build` y tokens del entorno del contenedor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HostCfg:
    id: str
    nombre: str
    """Nombre visible: el valor de la etiqueta `nombre` en Prometheus."""
    ip: str
    tipo: str


@dataclass(frozen=True)
class Config:
    sitio: str
    chat_id: int
    zona: str
    puerto: int
    prometheus: str
    grafana: str
    netinv: bool
    disco_pct: int
    hosts: tuple[HostCfg, ...]
    """En el orden de `hosts:` del site.yaml."""
    telegram_token: str = field(repr=False)
    grafana_token: str = field(repr=False)


def load(path: Path, env: Mapping[str, str]) -> Config:
    d = json.loads(path.read_text(encoding="utf-8"))
    token = env.get("TELEGRAM_TOKEN", "")
    if not token:
        raise ValueError("falta TELEGRAM_TOKEN en el entorno del contenedor")
    return Config(
        sitio=str(d["sitio"]),
        chat_id=int(d["chat_id"]),
        zona=str(d["zona"]),
        puerto=int(d["puerto"]),
        prometheus=str(d["prometheus"]),
        grafana=str(d["grafana"]),
        netinv=bool(d["netinv"]),
        disco_pct=int(d["disco_pct"]),
        hosts=tuple(
            HostCfg(str(h["id"]), str(h["nombre"]), str(h["ip"]), str(h["tipo"])) for h in d["hosts"]
        ),
        telegram_token=token,
        grafana_token=env.get("GRAFANA_TOKEN", ""),
    )
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_bot_fuentes.py -v && uv run ruff check src/vigia/bot tests && uv run mypy .`
Expected: PASS, sin avisos.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/fuentes.py src/vigia/bot/config.py tests/bot_fakes.py tests/test_bot_fuentes.py
git commit -m "feat(bot): fuentes (Prometheus, alertas de Grafana) y configuración (vigia-c3b)"
```

---

### Task 5: `consultas.py` y comandos de hosts y alertas

**Files:**
- Create: `src/vigia/bot/consultas.py`, `src/vigia/bot/comandos.py`
- Modify: `tests/bot_fakes.py` (añadir `contexto`)
- Test: `tests/test_bot_comandos.py`

- [ ] **Step 1: Fake de contexto y tests que fallan**

Añadir al final de `tests/bot_fakes.py` (y el import `from vigia.bot.comandos import Contexto` y
`from vigia.bot.fuentes import Grafana, Prometheus` arriba, junto a los demás):

```python
def contexto(
    prom: Mapping[str, Serie] | None = None,
    alertas: list[dict[str, Any]] | None = None,
    prom_caido: bool = False,
    grafana_caida: bool = False,
    **cambios: Any,
) -> Contexto:
    c = cfg(**cambios)
    h = fake_http(prom, alertas, prom_caido, grafana_caida)
    prom_, grafana = Prometheus(c.prometheus, h), Grafana(c.grafana, c.grafana_token, h)
    return Contexto(c, prom_, grafana, ahora=lambda: AHORA)
```

`tests/test_bot_comandos.py`:

```python
from __future__ import annotations

from typing import Any

from vigia.alerting import FS_EXCLUDED
from vigia.bot import consultas as q
from vigia.bot.comandos import parsear, responder

from .bot_fakes import Serie, contexto

N1, N2, NAS = {"nombre": "Nodo 1"}, {"nombre": "Nodo 2"}, {"nombre": "NAS"}

PROM: dict[str, Serie] = {
    q.SERVIDORES: [(N1, 1), (N2, 0)],
    q.PING: [(NAS, 1)],
    q.CPU: [(N1, 12.4)],
    q.RAM: [(N1, 40.2)],
    q.DISCO_MAX: [(N1, 95.0)],
    q.CARGA: [(N1, 0.52)],
    q.TEMP: [(N1, 48.0)],
    q.UPTIME: [(N1, 3 * 86400 + 7200)],
    q.DISCOS: [
        ({"nombre": "Nodo 1", "mountpoint": "/srv/datos"}, 95.2),
        ({"nombre": "Nodo 1", "mountpoint": "/"}, 61.0),
        ({"nombre": "Nodo 2", "mountpoint": "/"}, 10.0),
    ],
    q.CONTENEDORES: [(N1, 14)],
}
CAIDO: list[dict[str, Any]] = [
    {
        "labels": {"alertname": "Caído", "nombre": "Nodo 2"},
        "startsAt": "2026-10-28T13:05:00Z",
        "annotations": {},
    }
]


def test_fs_excluded_igual_que_las_alertas() -> None:
    assert q.FS_EXCLUDED == FS_EXCLUDED


def test_parsear() -> None:
    assert parsear("hola") is None
    assert parsear("/Host  nodo1 ") == ("host", "nodo1")
    assert parsear("/estado@ejemplo_bot") == ("estado", "")
    assert parsear("/info " + "x" * 100) == ("info", "x" * 64)


def test_texto_que_no_es_comando() -> None:
    assert responder("hola", contexto()) is None


def test_comando_desconocido_da_la_ayuda() -> None:
    r = responder("/tostadora", contexto())
    assert r is not None and r.startswith("<b>Comandos</b>")
    assert "/host &lt;nombre o IP&gt; — ficha de un servidor" in r


def test_estado() -> None:
    assert responder("/estado", contexto(PROM)) == (
        "<b>Ejemplo</b>\n"
        "✅ Nodo 1 · CPU 12% · RAM 40% · disco 95% ⚠\n"
        "❌ Nodo 2\n"
        "✅ NAS\n"
        "Sin alertas"
    )


def test_estado_con_alertas() -> None:
    r = responder("/estado", contexto(PROM, CAIDO))
    assert r is not None and r.endswith("Alertas (1): Caído (Nodo 2)")


def test_estado_con_fuentes_caidas() -> None:
    assert responder("/estado", contexto(prom_caido=True, grafana_caida=True)) == (
        "<b>Ejemplo</b>\n❔ Nodo 1\n❔ Nodo 2\n❔ NAS\n⚠ Prometheus no responde\n⚠ Grafana no responde"
    )


def test_alertas() -> None:
    assert responder("/alertas", contexto(alertas=CAIDO)) == "❌ Caído · Nodo 2 · desde 14:05 (23 min)"
    assert responder("/alertas", contexto()) == "Sin alertas"
    assert responder("/alertas", contexto(grafana_caida=True)) == "⚠ Grafana no responde"


def test_host() -> None:
    assert responder("/host nodo 1", contexto(PROM)) == (
        "✅ <b>Nodo 1</b> · 10.99.0.10 · omv\n"
        "CPU 12% · RAM 40% · carga 0.52 · 48 °C\n"
        "Encendido hace 3 d 2 h\n"
        "💾 / 61%\n"
        "💾 /srv/datos 95% ⚠\n"
        "Contenedores en marcha: 14"
    )


def test_host_por_ip_y_sin_metricas() -> None:
    assert responder("/host 10.99.0.20", contexto(PROM)) == "✅ <b>NAS</b> · 10.99.0.20 · synology"


def test_host_errores() -> None:
    c = contexto(PROM)
    assert responder("/host", c) == "Uso: /host &lt;nombre o IP&gt;"
    assert responder("/host <x>", c) == "No conozco &lt;x&gt;. Hosts: Nodo 1, Nodo 2, NAS"
    assert responder("/host nodo", c) == "Varios coinciden: Nodo 1, Nodo 2. Afina un poco."


def test_host_con_prometheus_caido() -> None:
    assert responder("/host nas", contexto(prom_caido=True)) == (
        "❔ <b>NAS</b> · 10.99.0.20 · synology\n⚠ Prometheus no responde"
    )
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_comandos.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot.comandos'`.

- [ ] **Step 3: Implementación**

`src/vigia/bot/consultas.py`:

```python
"""PromQL fijas del bot y lectura de los dispositivos de netinv.

Nada de lo que escribe el usuario entra en una consulta: se pide todo el sitio y se filtra en Python.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fuentes import FuenteError, Prometheus

FS_EXCLUDED = "tmpfs|ramfs|overlay|squashfs|nsfs|devtmpfs|fuse.+"
"""Igual que `vigia.alerting.FS_EXCLUDED`: en su contenedor el bot no tiene vigia (un test lo vigila)."""
_FS = f'fstype!~"{FS_EXCLUDED}"'
_USO = f"100 * (1 - node_filesystem_avail_bytes{{{_FS}}} / node_filesystem_size_bytes{{{_FS}}})"

SERVIDORES = 'max by (nombre) (up{job=~"node|windows|snmp"})'
PING = 'max by (nombre) (probe_success{job="ping"})'
CPU = '100 * (1 - avg by (nombre) (rate(node_cpu_seconds_total{mode="idle"}[5m])))'
RAM = (
    "100 * (1 - max by (nombre) (node_memory_MemAvailable_bytes) "
    "/ max by (nombre) (node_memory_MemTotal_bytes))"
)
DISCO_MAX = f"max by (nombre) ({_USO})"
DISCOS = f"max by (nombre, mountpoint) ({_USO})"
WIN_DISCOS = (
    'max by (nombre, volume) (100 * (1 - windows_logical_disk_free_bytes{volume=~"[A-Z]:"} '
    '/ windows_logical_disk_size_bytes{volume=~"[A-Z]:"}))'
)
CARGA = "max by (nombre) (node_load1)"
TEMP = "max by (nombre) (node_hwmon_temp_celsius)"
UPTIME = "max by (nombre) (time() - node_boot_time_seconds)"
CONTENEDORES = 'count by (nombre) (container_last_seen{name!=""})'
DISP_INFO = "netinv_device_info"
DISP_ULTIMA = "netinv_device_last_seen_seconds"
DISP_PRIMERA = "netinv_device_first_seen_seconds"

PROM_CAIDO = "⚠ Prometheus no responde"
GRAFANA_CAIDO = "⚠ Grafana no responde"


class Avisos:
    """Fuentes que no respondieron mientras se preparaba una respuesta (cada aviso, una vez)."""

    def __init__(self) -> None:
        self.lineas: list[str] = []

    def add(self, texto: str) -> None:
        if texto not in self.lineas:
            self.lineas.append(texto)


def serie(prom: Prometheus, avisos: Avisos, expr: str) -> list[tuple[dict[str, str], float]]:
    try:
        return prom.query(expr)
    except FuenteError:
        avisos.add(PROM_CAIDO)
        return []


def por(prom: Prometheus, avisos: Avisos, expr: str, etiqueta: str = "nombre") -> dict[str, float]:
    return {m.get(etiqueta, ""): v for m, v in serie(prom, avisos, expr)}


def estado_host(nombre: str, up: dict[str, float], ping: dict[str, float]) -> str:
    """✅ si responde algún exporter o el ping, ❌ si los hay y ninguno responde, ❔ sin datos."""
    valores = [d[nombre] for d in (up, ping) if nombre in d]
    if not valores:
        return "❔"
    return "✅" if max(valores) >= 1 else "❌"


@dataclass(frozen=True)
class Dispositivo:
    mac: str
    ip: str
    nombre: str
    tipo: str
    ubicacion: str
    fabricante: str
    modelo: str
    encendido: bool
    ultima: float
    primera: float


def dispositivos(prom: Prometheus) -> list[Dispositivo]:
    """Los que netinv vio en sus últimos 30 días. Lanza FuenteError si Prometheus no responde."""
    ultima = {m.get("mac", ""): v for m, v in prom.query(DISP_ULTIMA)}
    primera = {m.get("mac", ""): v for m, v in prom.query(DISP_PRIMERA)}
    out = []
    for m, _ in prom.query(DISP_INFO):
        mac = m.get("mac", "")
        out.append(
            Dispositivo(
                mac=mac,
                ip=m.get("ip", ""),
                nombre=m.get("mostrar") or m.get("nombre") or mac,
                tipo=m.get("tipo", ""),
                ubicacion=m.get("ubicacion", ""),
                fabricante=m.get("fabricante", ""),
                modelo=m.get("modelo", ""),
                encendido=m.get("encendido") == "●",
                ultima=ultima.get(mac, 0.0),
                primera=primera.get(mac, 0.0),
            )
        )
    return out
```

`src/vigia/bot/comandos.py` (los comandos de dispositivos llegan en la Task 6; aquí ya se registran
`ayuda`, `estado`, `alertas` y `host`):

```python
"""Comandos del bot: parseo, despacho y respuestas en HTML de Telegram (todo dato pasa por `esc`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .buscar import buscar
from .config import Config, HostCfg
from .consultas import (
    CARGA,
    CONTENEDORES,
    CPU,
    DISCO_MAX,
    DISCOS,
    GRAFANA_CAIDO,
    PING,
    RAM,
    SERVIDORES,
    TEMP,
    UPTIME,
    WIN_DISCOS,
    Avisos,
    estado_host,
    por,
    serie,
)
from .formato import duracion, esc, hora, pct, recortar
from .fuentes import FuenteError, Grafana, Prometheus

MAX_ARG = 64
MAX_OPCIONES = 8
MAX_ALERTAS_ESTADO = 5

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
            + f" · desde {hora(a.desde, now, z)} ({duracion(now - a.desde)})"
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


COMANDOS: dict[str, Comando] = {
    "estado": estado,
    "alertas": alertas,
    "host": host,
    "ayuda": ayuda,
    "start": ayuda,
}
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_bot_comandos.py -v && uv run ruff check src/vigia/bot tests && uv run mypy .`
Expected: PASS, sin avisos.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/consultas.py src/vigia/bot/comandos.py tests/bot_fakes.py tests/test_bot_comandos.py
git commit -m "feat(bot): /estado, /alertas, /host y /ayuda (vigia-c3b)"
```

---

### Task 6: Comandos de dispositivos (`/dispositivo`, `/info`, `/lista`)

**Files:**
- Modify: `src/vigia/bot/comandos.py`
- Test: `tests/test_bot_comandos.py`

- [ ] **Step 1: Tests que fallan** — añadir a `tests/test_bot_comandos.py` (y `ts` y `AHORA` al import de
`.bot_fakes`):

```python
IMPRESORA = {
    "mac": "aa:bb:cc:00:00:40", "ip": "10.99.0.40", "nombre": "Impresora", "mostrar": "Impresora",
    "tipo": "impresora", "ubicacion": "Despacho", "fabricante": "Ejemplo SA", "modelo": "", "encendido": "●",
}
TELE = {
    "mac": "aa:bb:cc:00:00:50", "ip": "10.99.0.50", "nombre": "", "mostrar": "tele-salon ¿?", "tipo": "",
    "ubicacion": "", "fabricante": "Ejemplo TV", "modelo": "", "encendido": "○",
}
DISP: dict[str, Serie] = {
    q.DISP_INFO: [(IMPRESORA, 1), (TELE, 1)],
    q.DISP_ULTIMA: [
        ({"mac": "aa:bb:cc:00:00:40"}, AHORA - 180),
        ({"mac": "aa:bb:cc:00:00:50"}, ts(2026, 10, 27, 23, 10)),
    ],
    q.DISP_PRIMERA: [({"mac": "aa:bb:cc:00:00:40"}, ts(2026, 10, 20, 9, 0))],
}


def test_dispositivo() -> None:
    c = contexto(DISP)
    assert responder("/dispositivo impresora", c) == "🟢 Impresora · 10.99.0.40 · visto hace 3 min"
    assert responder("/dispositivo 10.99.0.50", c) == "⚪ tele-salon ¿? · 10.99.0.50 · última vez ayer 23:10"
    assert responder("/dispositivo tostadora", c) == "No conozco tostadora. Prueba /lista"
    assert responder("/dispositivo", c) == "Uso: /dispositivo &lt;nombre, IP o MAC&gt;"


def test_info() -> None:
    assert responder("/info AA-BB-CC-00-00-40", contexto(DISP)) == (
        "🟢 <b>Impresora</b>\n"
        "Tipo: impresora\n"
        "Ubicación: Despacho\n"
        "Fabricante: Ejemplo SA\n"
        "IP: 10.99.0.40\n"
        "MAC: aa:bb:cc:00:00:40\n"
        "Primera vez: 20-10 09:00\n"
        "Última vez: 14:25"
    )


def test_lista() -> None:
    c = contexto(DISP)
    assert responder("/lista", c) == "<b>Encendidos: 1</b>\nimpresora (1): Impresora"
    assert responder("/lista Impresora", c) == "<b>Encendidos: 1</b>\nimpresora (1): Impresora"
    assert responder("/lista tv", c) == "Nada encendido de tipo tv"


def test_dispositivos_sin_netinv_o_sin_prometheus() -> None:
    sin = "Este sitio no tiene netinv: no hay inventario de dispositivos."
    assert responder("/lista", contexto(DISP, netinv=False)) == sin
    assert responder("/info impresora", contexto(DISP, netinv=False)) == sin
    assert responder("/dispositivo impresora", contexto(prom_caido=True)) == "⚠ Prometheus no responde"
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_comandos.py -k "dispositivo or info or lista" -v`
Expected: FAIL (los comandos aún no existen: responden con la ayuda).

- [ ] **Step 3: Implementación** — en `src/vigia/bot/comandos.py`:

Imports: añadir `normalizar` a `from .buscar import buscar, normalizar`, y `PROM_CAIDO`, `Dispositivo` y
`dispositivos` a la lista de `from .consultas import (...)`.

Constantes, junto a `MAX_ALERTAS_ESTADO`:

```python
SIN_NETINV = "Este sitio no tiene netinv: no hay inventario de dispositivos."
SIN_TIPO = "sin clasificar"
```

Funciones, antes de `COMANDOS`:

```python
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
```

Y en `COMANDOS`:

```python
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
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_bot_comandos.py -v && uv run ruff check src/vigia/bot tests && uv run mypy .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/comandos.py tests/test_bot_comandos.py
git commit -m "feat(bot): /dispositivo, /info y /lista desde las métricas de netinv (vigia-c3b)"
```

---

### Task 7: `telegram.py`

**Files:**
- Create: `src/vigia/bot/telegram.py`
- Test: `tests/test_bot_telegram.py`

- [ ] **Step 1: Tests que fallan** — `tests/test_bot_telegram.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from vigia.bot.fuentes import FuenteError
from vigia.bot.telegram import Limitador, Telegram, clasificar

from .bot_fakes import AHORA, CHAT


class Grabadora:
    def __init__(self, respuesta: Any) -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[str, Any, float]] = []

    def __call__(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 10.0
    ) -> Any:
        self.llamadas.append((url, body, timeout))
        return self.respuesta


def test_actualizaciones() -> None:
    g = Grabadora({"ok": True, "result": [{"update_id": 7}]})
    assert Telegram("123:abc", g).actualizaciones(5) == [{"update_id": 7}]
    url, body, timeout = g.llamadas[0]
    assert url == "https://api.telegram.org/bot123:abc/getUpdates"
    assert body == {"timeout": 50, "allowed_updates": ["message"], "offset": 5}
    assert timeout == 60


def test_rechazo() -> None:
    with pytest.raises(FuenteError):
        Telegram("123:abc", Grabadora({"ok": False})).actualizaciones(None)


def test_enviar() -> None:
    g = Grabadora({"ok": True, "result": {}})
    Telegram("123:abc", g).enviar(CHAT, "<b>hola</b>")
    url, body, _ = g.llamadas[0]
    assert url.endswith("/sendMessage")
    assert body["chat_id"] == CHAT and body["parse_mode"] == "HTML" and body["text"] == "<b>hola</b>"


def test_registrar_comandos() -> None:
    g = Grabadora({"ok": True, "result": True})
    Telegram("123:abc", g).registrar_comandos([("estado", "resumen")])
    assert g.llamadas[0][1] == {"commands": [{"command": "estado", "description": "resumen"}]}


def test_repr_sin_token() -> None:
    assert "abc" not in repr(Telegram("123:abc", Grabadora({})))


def _msg(chat: int, date: float = AHORA, text: Any = "/estado") -> dict[str, Any]:
    return {"update_id": 1, "message": {"chat": {"id": chat}, "date": date, "text": text}}


def test_clasificar() -> None:
    desde = AHORA - 120
    assert clasificar(_msg(CHAT), CHAT, desde) == ("atender", "/estado")
    assert clasificar(_msg(42), CHAT, desde) == ("otro_chat", "42")
    assert clasificar(_msg(CHAT, date=AHORA - 600), CHAT, desde) == ("ignorar", "")
    assert clasificar(_msg(CHAT, text=None), CHAT, desde) == ("ignorar", "")
    assert clasificar({"update_id": 2, "edited_message": {}}, CHAT, desde) == ("ignorar", "")


class Reloj:
    def __init__(self) -> None:
        self.t = 0.0
        self.dormidas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.dormidas.append(s)
        self.t += s


def test_limitador_espacia_y_corta() -> None:
    r = Reloj()
    lim = Limitador(reloj=r, dormir=r.dormir)
    assert lim.permitir() and lim.permitir()
    assert r.dormidas == [1.0]
    for _ in range(18):
        assert lim.permitir()
    assert not lim.permitir()  # 20 en el último minuto
    r.t += 60
    assert lim.permitir()
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_telegram.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot.telegram'`.

- [ ] **Step 3: Implementación** — `src/vigia/bot/telegram.py`:

```python
"""API de bots de Telegram: long polling, envío, filtro del chat autorizado y límite de respuestas."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from .fuentes import FuenteError, Http

API = "https://api.telegram.org"
ESPERA = 50
"""Segundos que Telegram retiene getUpdates si no hay mensajes."""


class Mensajeria(Protocol):
    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]: ...

    def enviar(self, chat_id: int, texto: str) -> None: ...


class Telegram:
    def __init__(self, token: str, http: Http, api: str = API) -> None:
        self._token = token
        self.http = http
        self.api = api

    def __repr__(self) -> str:
        return "Telegram(<token oculto>)"

    def _llamar(self, metodo: str, body: dict[str, Any], timeout: float = 10.0) -> Any:
        d = self.http(f"{self.api}/bot{self._token}/{metodo}", body=body, timeout=timeout)
        if not isinstance(d, dict) or not d.get("ok"):
            raise FuenteError(f"{metodo} rechazado")
        return d.get("result")

    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"timeout": ESPERA, "allowed_updates": ["message"]}
        if offset is not None:
            body["offset"] = offset
        r = self._llamar("getUpdates", body, timeout=ESPERA + 10)
        return [u for u in r if isinstance(u, dict)] if isinstance(r, list) else []

    def enviar(self, chat_id: int, texto: str) -> None:
        self._llamar(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": texto,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )

    def registrar_comandos(self, comandos: Iterable[tuple[str, str]]) -> None:
        self._llamar("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in comandos]})


def clasificar(update: dict[str, Any], chat_id: int, desde: float) -> tuple[str, str]:
    """("atender", texto), ("otro_chat", id del chat) o ("ignorar", "")."""
    m = update.get("message")
    if not isinstance(m, dict):
        return "ignorar", ""
    chat = m.get("chat")
    cid = chat.get("id") if isinstance(chat, dict) else None
    if cid != chat_id:
        return "otro_chat", str(cid)
    texto = m.get("text")
    if not isinstance(texto, str) or float(m.get("date", 0)) < desde:
        return "ignorar", ""
    return "atender", texto


class Limitador:
    """Como mucho `por_minuto` respuestas por minuto y una cada `intervalo` segundos (si no, espera)."""

    def __init__(
        self,
        por_minuto: int = 20,
        intervalo: float = 1.0,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.por_minuto = por_minuto
        self.intervalo = intervalo
        self.reloj = reloj
        self.dormir = dormir
        self._envios: deque[float] = deque()

    def permitir(self) -> bool:
        now = self.reloj()
        while self._envios and now - self._envios[0] >= 60:
            self._envios.popleft()
        if len(self._envios) >= self.por_minuto:
            return False
        if self._envios and now - self._envios[-1] < self.intervalo:
            self.dormir(self.intervalo - (now - self._envios[-1]))
            now = self.reloj()
        self._envios.append(now)
        return True
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_bot_telegram.py -v && uv run ruff check src/vigia/bot tests && uv run mypy .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/telegram.py tests/test_bot_telegram.py
git commit -m "feat(bot): cliente de Telegram, filtro de chat y limitador (vigia-c3b)"
```

---

### Task 8: `__main__.py` — bucle, salud y arranque

**Files:**
- Create: `src/vigia/bot/__main__.py`
- Test: `tests/test_bot_main.py`

- [ ] **Step 1: Tests que fallan** — `tests/test_bot_main.py`:

```python
from __future__ import annotations

import itertools
import urllib.request
from typing import Any

from vigia.bot.__main__ import ERROR_INTERNO, Bucle, Salud, servir_salud
from vigia.bot.comandos import Contexto, responder
from vigia.bot.fuentes import FuenteError
from vigia.bot.telegram import Limitador

from .bot_fakes import AHORA, CHAT, contexto


class FakeTg:
    def __init__(self, lotes: list[list[dict[str, Any]] | Exception]) -> None:
        self.lotes = lotes
        self.offsets: list[int | None] = []
        self.enviados: list[tuple[int, str]] = []

    def actualizaciones(self, offset: int | None) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        lote = self.lotes.pop(0)
        if isinstance(lote, Exception):
            raise lote
        return lote

    def enviar(self, chat_id: int, texto: str) -> None:
        self.enviados.append((chat_id, texto))


def _msg(uid: int, chat: int = CHAT, text: str = "/ayuda") -> dict[str, Any]:
    return {"update_id": uid, "message": {"chat": {"id": chat}, "date": AHORA, "text": text}}


def _bucle(tg: FakeTg, dormidas: list[float] | None = None, **kw: Any) -> tuple[Bucle, Salud]:
    c, salud = contexto(), Salud()
    sin_espera = Limitador(reloj=itertools.count(0.0, 2.0).__next__)
    destino = dormidas if dormidas is not None else []
    b = Bucle(c.cfg, tg, c, salud, sin_espera, reloj=lambda: AHORA, dormir=destino.append, **kw)
    return b, salud


def test_atiende_el_chat_y_avanza_el_offset() -> None:
    tg = FakeTg([[_msg(10)], []])
    b, salud = _bucle(tg)
    b.paso()
    b.paso()
    assert tg.enviados[0][0] == CHAT and tg.enviados[0][1].startswith("<b>Comandos</b>")
    assert tg.offsets == [None, 11]
    assert 'vigia_bot_mensajes_total{resultado="atendido"} 1' in salud.texto()


def test_descarta_otro_chat() -> None:
    tg = FakeTg([[_msg(10, chat=42)]])
    b, salud = _bucle(tg)
    b.paso()
    assert tg.enviados == []
    assert 'vigia_bot_mensajes_total{resultado="descartado"} 1' in salud.texto()


def test_reintenta_con_espera_creciente() -> None:
    tg = FakeTg([FuenteError("HTTP 502"), FuenteError("URLError"), [_msg(1)], FuenteError("URLError")])
    dormidas: list[float] = []
    b, _ = _bucle(tg, dormidas)
    for _ in range(4):
        b.paso()
    assert dormidas == [1.0, 2.0, 1.0]
    assert len(tg.enviados) == 1


def test_error_interno_no_tumba_el_bucle() -> None:
    def roto(texto: str, ctx: Contexto) -> str | None:
        raise RuntimeError("fallo")

    tg = FakeTg([[_msg(1)]])
    b, salud = _bucle(tg, responder=roto)
    b.paso()
    assert tg.enviados == [(CHAT, ERROR_INTERNO)]
    assert 'vigia_bot_mensajes_total{resultado="error"} 1' in salud.texto()


def test_responder_por_defecto() -> None:
    b, _ = _bucle(FakeTg([]))
    assert b.responder is responder


def test_metrics_http() -> None:
    srv = servir_salud(Salud(), 0)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/metrics"
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310
            assert "vigia_bot_up 1" in r.read().decode()
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_main.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vigia.bot.__main__'`.

- [ ] **Step 3: Implementación** — `src/vigia/bot/__main__.py`:

```python
"""Arranque del bot (`python -m vigia_bot` en su contenedor): /metrics, comandos de Telegram y bucle."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import comandos
from .comandos import AYUDA, Contexto
from .config import Config, load
from .fuentes import FuenteError, Grafana, Prometheus, http_json
from .telegram import Limitador, Mensajeria, Telegram, clasificar

CONFIG = Path("/etc/vigia-bot/config.json")
ANTIGUEDAD = 120
"""Al arrancar se ignoran los mensajes de más de 2 min: no se contesta a destiempo."""
ESPERA_MAX = 60.0
ERROR_INTERNO = "⚠ Error interno; mira el log del bot"


def log(*partes: object) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *partes, flush=True)


class Salud:
    RESULTADOS = ("atendido", "descartado", "limitado", "error")

    def __init__(self) -> None:
        self._n = dict.fromkeys(self.RESULTADOS, 0)
        self._lock = threading.Lock()

    def contar(self, resultado: str) -> None:
        with self._lock:
            self._n[resultado] += 1

    def texto(self) -> str:
        with self._lock:
            n = dict(self._n)
        lineas = [
            "# HELP vigia_bot_up El bot está en marcha.",
            "# TYPE vigia_bot_up gauge",
            "vigia_bot_up 1",
            "# HELP vigia_bot_mensajes_total Mensajes recibidos por resultado.",
            "# TYPE vigia_bot_mensajes_total counter",
        ]
        lineas += [f'vigia_bot_mensajes_total{{resultado="{r}"}} {v}' for r, v in n.items()]
        return "\n".join(lineas) + "\n"


def servir_salud(salud: Salud, puerto: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # nombre fijado por http.server
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            body = salud.texto().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    # todas las interfaces del contenedor: solo la red interna del stack, sin puerto publicado
    srv = ThreadingHTTPServer(("", puerto), Handler)  # noqa: S104
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Bucle:
    def __init__(
        self,
        cfg: Config,
        tg: Mensajeria,
        ctx: Contexto,
        salud: Salud,
        limitador: Limitador,
        responder: Callable[[str, Contexto], str | None] = comandos.responder,
        reloj: Callable[[], float] = time.time,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg, self.tg, self.ctx, self.salud, self.limitador = cfg, tg, ctx, salud, limitador
        self.responder, self.dormir = responder, dormir
        self.offset: int | None = None
        self.desde = reloj() - ANTIGUEDAD
        self.espera = 1.0

    def paso(self) -> None:
        try:
            updates = self.tg.actualizaciones(self.offset)
        except FuenteError as e:
            log("telegram:", e, f"(reintento en {self.espera:.0f} s)")
            self.dormir(self.espera)
            self.espera = min(self.espera * 2, ESPERA_MAX)
            return
        self.espera = 1.0
        for u in updates:
            self.offset = int(u.get("update_id", 0)) + 1
            tipo, valor = clasificar(u, self.cfg.chat_id, self.desde)
            if tipo == "otro_chat":
                self.salud.contar("descartado")
                log("descartado un mensaje del chat", valor)
            elif tipo == "atender":
                self._atender(valor)

    def _atender(self, texto: str) -> None:
        try:
            respuesta = self.responder(texto, self.ctx)
        except Exception as e:  # un comando roto no puede parar el bot
            log("error en el comando:", type(e).__name__)
            self.salud.contar("error")
            respuesta = ERROR_INTERNO
        if respuesta is None:
            return
        if not self.limitador.permitir():
            self.salud.contar("limitado")
            return
        try:
            self.tg.enviar(self.cfg.chat_id, respuesta)
            if respuesta != ERROR_INTERNO:
                self.salud.contar("atendido")
        except FuenteError as e:
            log("telegram:", e)


def main() -> None:
    cfg = load(CONFIG, os.environ)
    tg = Telegram(cfg.telegram_token, http_json)
    prom = Prometheus(cfg.prometheus, http_json)
    ctx = Contexto(cfg, prom, Grafana(cfg.grafana, cfg.grafana_token, http_json))
    salud = Salud()
    servir_salud(salud, cfg.puerto)
    try:
        tg.registrar_comandos((c, d) for c, _, d in AYUDA)
    except FuenteError as e:
        log("setMyCommands:", e)
    log("bot en marcha:", cfg.sitio, "·", len(cfg.hosts), "hosts")
    bucle = Bucle(cfg, tg, ctx, salud, Limitador())
    while True:
        bucle.paso()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Comprobar que pasan**

Run: `uv run pytest tests/test_bot_main.py -v && uv run ruff check src/vigia/bot tests && uv run mypy .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/bot/__main__.py tests/test_bot_main.py
git commit -m "feat(bot): bucle con reintentos, /metrics y arranque (vigia-c3b)"
```

---

### Task 9: Build — imagen, `config.json`, compose y job de Prometheus

**Files:**
- Create: `src/vigia/images/bot/Dockerfile`
- Modify: `src/vigia/build.py`, `src/vigia/templates/compose/monitor.yml.j2`,
  `src/vigia/templates/prometheus/prometheus.yml.j2`, `examples/sitio-ejemplo/site.yaml`
- Test: `tests/test_bot_build.py`; regenerar `tests/golden/sitio-ejemplo/`

- [ ] **Step 1: Activar el bot en el ejemplo y tests que fallan**

En `examples/sitio-ejemplo/site.yaml`, al final del bloque `modulos:` (tras `snmp:` y sus `auths`):

```yaml
  bot: {activo: true, grafana_token: BOT_GRAFANA_TOKEN}
```

`tests/test_bot_build.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from vigia.bot.config import load
from vigia.build import build_site
from vigia.model import Site

from .conftest import EXAMPLE


def _out(data: dict[str, Any]) -> tuple[Site, dict[str, str | bytes]]:
    s = Site.model_validate(data)
    return s, build_site(s, EXAMPLE)


def test_bot_en_el_build(example_data: dict[str, Any]) -> None:
    s, out = _out(example_data)
    assert {"bot/Dockerfile", "bot/__main__.py", "bot/comandos.py", "bot/config.json"} <= set(out)
    assert not any("__pycache__" in k for k in out)
    cfg = json.loads(out["bot/config.json"])
    assert [h["id"] for h in cfg["hosts"]] == [h.id for h in s.hosts]
    assert cfg["chat_id"] == -1000000000001
    assert (cfg["prometheus"], cfg["grafana"]) == ("http://prometheus:9090", "http://grafana:3000")


def test_servicio_del_bot(example_data: dict[str, Any]) -> None:
    _, out = _out(example_data)
    bot = yaml.safe_load(out["ejemplo_monitor.yml"])["services"]["bot"]
    assert bot["read_only"] is True and bot["cap_drop"] == ["ALL"] and "ports" not in bot
    assert bot["user"] == "65534:65534" and bot["container_name"] == "ejm-bot"
    assert "TELEGRAM_TOKEN=${ALERTAS_TELEGRAM_TOKEN}" in bot["environment"]
    assert "GRAFANA_TOKEN=${BOT_GRAFANA_TOKEN}" in bot["environment"]
    assert bot["volumes"] == ["./bot:/etc/vigia-bot:ro"]


def test_job_de_prometheus(example_data: dict[str, Any]) -> None:
    _, out = _out(example_data)
    jobs = yaml.safe_load(out["prometheus/prometheus.yml"])["scrape_configs"]
    job = next(j for j in jobs if j["job_name"] == "bot")
    assert job["static_configs"] == [{"targets": ["bot:9466"], "labels": {"nombre": "Bot de Telegram"}}]


def test_config_generada_la_lee_el_bot(example_data: dict[str, Any], tmp_path: Path) -> None:
    s, out = _out(example_data)
    p = tmp_path / "config.json"
    p.write_text(str(out["bot/config.json"]), encoding="utf-8")
    c = load(p, {"TELEGRAM_TOKEN": "123:abc"})
    assert [h.nombre for h in c.hosts] == [h.display_name for h in s.hosts]


def test_sin_bot(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"]["activo"] = False
    _, out = _out(example_data)
    assert not any(k.startswith("bot/") for k in out)
    assert "vigia-bot" not in str(out["ejemplo_monitor.yml"])
    assert "job_name: bot" not in str(out["prometheus/prometheus.yml"])
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_bot_build.py -v`
Expected: FAIL (no hay `bot/…` en el build).

- [ ] **Step 3: Implementación**

`src/vigia/images/bot/Dockerfile`:

```dockerfile
# vigia-bot — consultas por Telegram en el chat de las alertas (solo lectura)
FROM python:3.12-alpine
RUN apk add --no-cache tzdata
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY *.py /app/vigia_bot/
WORKDIR /app
USER 65534:65534
CMD ["python3", "-m", "vigia_bot"]
```

`src/vigia/build.py`: añadir `import json` a los imports; en `build_site`, justo después del bloque
`if s.modulos.netinv.activo: ...`:

```python
    if s.modulos.bot.activo:
        out.update(_bot(s))
```

y, después de `_bundled_image`:

```python
def bot_config(s: Site) -> str:
    """config.json del bot: sin secretos (los tokens llegan por el entorno del contenedor)."""
    assert s.alertas.telegram  # lo garantiza la validación del modelo
    b = s.modulos.bot
    data = {
        "sitio": s.branding.nombre,
        "chat_id": int(s.alertas.telegram.chat_id),
        "zona": b.zona,
        "puerto": b.puerto,
        "prometheus": "http://prometheus:9090",
        "grafana": "http://grafana:3000",
        "netinv": s.modulos.netinv.activo,
        "disco_pct": s.alertas.umbrales.disco_pct,
        "hosts": [{"id": h.id, "nombre": h.display_name, "ip": h.ip, "tipo": h.tipo.value} for h in s.hosts],
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def _bot(s: Site) -> dict[str, str | bytes]:
    """Dockerfile, código de `vigia.bot` (será el paquete `vigia_bot` del contenedor) y config.json."""
    out = _bundled_image("bot", "bot")
    with as_file(files("vigia").joinpath("bot")) as path:
        for f in sorted(Path(path).glob("*.py")):
            out[f"bot/{f.name}"] = f.read_bytes()
    out["bot/config.json"] = bot_config(s)
    return out
```

`src/vigia/templates/compose/monitor.yml.j2`: tras el bloque `{% if s.modulos.netinv.activo %} … {% endif %}`
del servicio netinv (antes de `volumes:`):

```jinja
{% if s.modulos.bot.activo %}

  # Bot de consultas por Telegram en el chat de las alertas (solo lectura). Imagen local desde ./bot;
  # /metrics en :{{ s.modulos.bot.puerto | raw }}, solo para Prometheus (sin puerto publicado).
  bot:
    build: ./bot
    image: vigia-bot:local
    container_name: {{ prefix ~ "bot" }}
    restart: unless-stopped
    user: "65534:65534"
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    environment:
      - {{ "TELEGRAM_TOKEN=${" ~ s.alertas.telegram.token ~ "}" }}
      - {{ "GRAFANA_TOKEN=${" ~ s.modulos.bot.grafana_token ~ "}" }}
    volumes:
      - ./bot:/etc/vigia-bot:ro        # carpeta, no el fichero: el despliegue la reescribe por inodo
    depends_on:
      - prometheus
      - grafana
{% endif %}
```

`src/vigia/templates/prometheus/prometheus.yml.j2`: tras el bloque del job `netinv`:

```jinja
{% if s.modulos.bot.activo %}

  # Bot de consultas por Telegram (salud)
  - job_name: bot
    scrape_interval: 60s
    static_configs:
      - targets: [{{ "bot:" ~ s.modulos.bot.puerto }}]
        labels: {nombre: Bot de Telegram}
{% endif %}
```

- [ ] **Step 4: Comprobar que pasan y regenerar el golden**

Run: `uv run pytest tests/test_bot_build.py -v`
Expected: PASS.

Run: `VIGIA_UPDATE_GOLDEN=1 uv run pytest tests/test_build_golden.py && git status --short tests/golden`
Expected: aparecen `tests/golden/sitio-ejemplo/bot/*` (Dockerfile, `*.py`, `config.json`) y cambian
`ejemplo_monitor.yml` y `prometheus/prometheus.yml`. Revisar con `git diff tests/golden` que no cambia nada
más.

Run: `uv run pytest -q`
Expected: FAIL solo en `tests/test_deploy.py` si algún test despliega el monitor con `SECRETS` (falta
`BOT_GRAFANA_TOKEN`): se arregla en la Task 10. Todo lo demás, PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/images/bot src/vigia/build.py src/vigia/templates examples/sitio-ejemplo/site.yaml \
        tests/test_bot_build.py tests/golden
git commit -m "feat(bot): imagen, config.json, servicio del compose y job de Prometheus (vigia-c3b)"
```

---

### Task 10: Despliegue — carpeta gestionada, reinicio y secreto

**Files:**
- Modify: `src/vigia/deploy/__init__.py` (`MONITOR_DIRS`, `RELOAD`, `units`, `secret_names`)
- Test: `tests/test_deploy.py`

- [ ] **Step 1: Tests que fallan** — en `tests/test_deploy.py`, añadir a `SECRETS`:

```python
    "BOT_GRAFANA_TOKEN": "glsa-sintetico-000",
```

y al final del fichero (añadir `secret_names` al import de `vigia.deploy`):

```python
def test_unidad_monitor_con_bot(example_data: dict[str, Any]) -> None:
    s, built = _built(example_data)
    u = units(s, built)["monitor"]
    assert "bot" in u.dirs and "ejm-bot" in u.restart
    assert "BOT_GRAFANA_TOKEN" in u.secrets and "ALERTAS_TELEGRAM_TOKEN" in u.secrets
    assert "BOT_GRAFANA_TOKEN" in secret_names(s)
    assert check_no_secrets(built, SECRETS, secret_names(s)) == []
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/test_deploy.py -v`
Expected: FAIL en `test_unidad_monitor_con_bot` («bot» no está en `dirs`).

- [ ] **Step 3: Implementación** — en `src/vigia/deploy/__init__.py`:

```python
MONITOR_DIRS = [
    "prometheus/targets",
    "blackbox",
    "grafana-provisioning",
    "dashboards",
    "netinv",
    "snmp",
    "branding",
    "bot",
]
```

```python
RELOAD = ["prometheus", "blackbox", "grafana", "snmp-exporter", "bot"]
```

En `units`, tras `if s.alertas.activo: secrets += s.alertas.env_vars`:

```python
        if s.modulos.bot.activo and s.modulos.bot.grafana_token:
            secrets.append(s.modulos.bot.grafana_token)
```

En `secret_names`, antes del `for h in s.hosts:`:

```python
    if s.modulos.bot.grafana_token:
        out.add(s.modulos.bot.grafana_token)
```

- [ ] **Step 4: Comprobar que pasa toda la batería**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: PASS, sin avisos.

- [ ] **Step 5: Commit**

```bash
git add src/vigia/deploy/__init__.py tests/test_deploy.py
git commit -m "feat(bot): el despliegue del monitor gestiona la carpeta del bot y su token de Grafana (vigia-c3b)"
```

---

### Task 11: Documentación

**Files:**
- Create: `docs/bot.md`
- Modify: `README.md` (sección «Qué sabe vigilar», tras el párrafo de alertas), `CHANGELOG.md` (arriba)

- [ ] **Step 1: `docs/bot.md`**

```markdown
# Bot de consultas por Telegram

El bot de las alertas también responde a comandos en el mismo chat: solo consulta, nunca cambia nada.

| Comando | Qué responde |
|---------|--------------|
| `/estado` | cada host (✅/❌/❔; CPU, RAM y disco si tiene node_exporter) y las alertas activas |
| `/alertas` | alertas disparadas, desde cuándo |
| `/host <nombre o IP>` | ficha de un servidor: CPU, RAM, carga, temperatura, discos, contenedores |
| `/dispositivo <nombre, IP o MAC>` | si está conectado (netinv) |
| `/info <nombre, IP o MAC>` | ficha del dispositivo: tipo, ubicación, fabricante, IP, MAC, primera y última vez |
| `/lista [tipo]` | dispositivos encendidos, por tipo |
| `/ayuda` | los comandos |

Solo atiende el chat de `alertas.telegram.chat_id`; lo que llegue de otro chat se descarta sin responder.

## Activarlo

1. Alertas por Telegram configuradas (ver [alertas.md](alertas.md)). En @BotFather, el bot con *Group
   Privacy* activado (en el grupo solo recibe `/comandos`) y *Allow Groups* desactivado.
2. Token de Grafana de solo lectura: *Administración ▸ Usuarios y acceso ▸ Cuentas de servicio ▸ Añadir*,
   rol **Viewer**, y *Añadir token*. Guárdalo en el fichero de entorno del sitio (`BOT_GRAFANA_TOKEN`) y, en
   OMV, también en el *Environment* del stack del monitor (`vigia deploy` aborta si falta).
3. En `site.yaml`:

   ```yaml
   modulos:
     bot: {activo: true, grafana_token: BOT_GRAFANA_TOKEN}   # zona: Europe/Madrid, puerto: 9466
   ```

4. `uv run vigia deploy monitor` (diff) y, si está bien, `--yes`.
5. Prueba: `/estado` en el grupo; un mensaje privado al bot no debe recibir respuesta.

## Salud

Prometheus lee `/metrics` del bot (job `bot`): `vigia_bot_up` y `vigia_bot_mensajes_total{resultado}`
(atendido, descartado, limitado, error). Si el bot cae, avisa la regla «Exporter sin respuesta».
```

- [ ] **Step 2: README y CHANGELOG**

En `README.md`, tras el párrafo que empieza «Alertas con la marca del sitio…»:

```markdown
El mismo bot responde a consultas en el chat de alertas (`/estado`, `/host`, `/dispositivo`…), solo
lectura: ver [docs/bot.md](docs/bot.md).
```

En `CHANGELOG.md`, tras `# Cambios`:

```markdown
## Sin publicar

- **Bot de consultas por Telegram** (`modulos.bot`): `/estado`, `/alertas`, `/host`, `/dispositivo`,
  `/info`, `/lista` y `/ayuda` en el chat de las alertas; solo lectura, solo ese chat, sin puertos
  publicados ([docs/bot.md](docs/bot.md)).
```

- [ ] **Step 3: Verificación completa**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: PASS, sin avisos.

- [ ] **Step 4: Commit**

```bash
git add docs/bot.md README.md CHANGELOG.md
git commit -m "docs: bot de consultas por Telegram (vigia-c3b)"
```

---

### Task 12: Puesta en marcha en el sitio de casa (myNet) — **con OK del usuario en cada paso**

Fuera del repo de vigia; nada de esto lo ejecuta el agente sin un OK explícito (rule `operaciones.md`).

- [ ] **Step 1 (usuario):** en Grafana (`:3300` de sol4), cuenta de servicio Viewer y token; añadir
  `BOT_GRAFANA_TOKEN` al fichero de entorno de myNet **y** al *Environment* del stack `grafana_prometheus`
  en la UI de OMV. Comprobar en @BotFather que *Group Privacy* está activado y *Allow Groups* desactivado.
- [ ] **Step 2:** en `myNet/monitor/site.yaml`, `modulos.bot: {activo: true, grafana_token:
  BOT_GRAFANA_TOKEN}`; en `monitor/`, `uv sync --reinstall-package vigia` y `uv run vigia validate`.
- [ ] **Step 3:** `uv run vigia deploy monitor` (diff) → presentar el diff → con OK, `--yes`
  (copia previa en `/root/vigia-backups/`; rollback: `uv run vigia rollback monitor --yes`).
- [ ] **Step 4:** verificación: `docker logs` del contenedor `bot` («bot en marcha»), target `bot` *up* en
  Prometheus, cada comando en el grupo y un mensaje privado al bot sin respuesta.
- [ ] **Step 5:** `CLAUDE.md` de myNet (línea en «Capa core… Monitorización») y commit en myNet.
```
