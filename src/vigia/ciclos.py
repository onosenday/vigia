"""Catálogo de ciclos de vida: cuándo pierde el soporte cada versión de cada producto (docs/ciclos.md).

Un YAML por producto en `vigia/catalogo/`. Los que cubre endoflife.date se refrescan con
`vigia ciclos actualizar` (lo ejecuta el mantenedor y commitea; nunca el build); el resto (OMV, DSM) se
mantiene a mano. El build convierte el catálogo en reglas de grabación constantes de Prometheus, para que
alertas, paneles y bot usen la misma tabla:

  vigia_ciclo_fin_soporte_timestamp{producto, ciclo}   epoch del fin de soporte que cuenta (ver fecha_aviso)
  vigia_ciclo_info{producto, ciclo, ultimo}             1 por ciclo conocido; `ultimo` = ciclo más reciente
  vigia_ciclos_catalogo_timestamp{producto}             epoch de la última comprobación del producto
  vigia_ciclo_superado{producto, ciclo, ultimo}         1 por ciclo anterior al de referencia (aviso_version)
  vigia_ciclo_aviso_dias{producto}                      días de aviso antes del fin de soporte

y, con la versión instalada en cada equipo (node_os_info, vigia_producto_info del updates-exporter y la
imagen de cada contenedor en cAdvisor, con la etiqueta `contenedor`), las derivadas:

  vigia_producto_ciclo{nombre, producto, producto_nombre, ciclo, version}   1 por equipo y producto
  vigia_soporte_restante_dias{…}            días hasta el fin de soporte (negativo: ya sin soporte)
  vigia_version_mayor_disponible{…, ultimo} 1 si el ciclo instalado es anterior al de referencia
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.request import Request, urlopen

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

if TYPE_CHECKING:
    from vigia.model import Site

CATALOGO_DIR = Path(str(files("vigia") / "catalogo"))
ENDOFLIFE_API = "https://endoflife.date/api/{slug}.json"

FIN = "vigia_ciclo_fin_soporte_timestamp"
INFO = "vigia_ciclo_info"
COMPROBADO = "vigia_ciclos_catalogo_timestamp"
SUPERADO = "vigia_ciclo_superado"
PRODUCTO_CICLO = "vigia_producto_ciclo"
RESTANTE = "vigia_soporte_restante_dias"
MAYOR = "vigia_version_mayor_disponible"
AVISO = "vigia_ciclo_aviso_dias"
PRODUCTO_INFO = "vigia_producto_info"
"""Lo publica el updates-exporter: producto y versión que informa cada host (docs/actualizaciones.md)."""

ProductoId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
CicloId = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z][0-9A-Za-z._-]{0,19}$")]
FechaAviso = Literal["normal", "extendido"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _promql(rx: str) -> str:
    """Una expresión `^…` del catálogo para PromQL (label_replace y `=~` anclan al principio y al final)."""
    return rx.removeprefix("^") + ".*"


class Ciclo(_Base):
    ciclo: CicloId
    publicado: date
    fin_soporte: date | None = None
    """Fin del soporte normal (actualizaciones de seguridad). None: aún sin fecha anunciada."""
    fin_extendido: date | None = None
    """Fin del soporte extendido (Debian ELTS, Ubuntu ESM, DSM LTS…), si existe."""
    ultima_version: str | None = Field(default=None, max_length=40)
    lts: bool = False

    def fin(self, aviso: FechaAviso) -> date | None:
        """La fecha que cuenta: la extendida si se pide y existe; si no, la normal."""
        if aviso == "extendido" and self.fin_extendido:
            return self.fin_extendido
        return self.fin_soporte


class Producto(_Base):
    producto: ProductoId
    nombre: Annotated[
        str, StringConstraints(min_length=1, max_length=40, pattern=r"^[^\x00-\x1f`$\\{}<>\"]*$")
    ]
    fuente: Literal["endoflife", "manual"]
    endoflife: ProductoId | None = None
    """Slug de endoflife.date (solo con fuente endoflife)."""
    referencia: str | None = Field(default=None, max_length=200)
    """De dónde salen los datos a mano (fuente manual)."""
    fecha_aviso: FechaAviso = "normal"
    ultimo_lts: bool = False
    """La versión de referencia es el último ciclo LTS (Ubuntu), no el último publicado."""
    os_ids: list[ProductoId] = []
    """`ID` de os-release con que aparece en node_os_info (debian, raspbian…): de ahí sale su versión."""
    imagen_regex: str | None = None
    """Expresión que casa la imagen de un contenedor (`repo/nombre:etiqueta`, de cAdvisor) y extrae la
    versión de la etiqueta en su primer grupo. Las etiquetas sin versión suficiente (`latest`, `8` cuando los
    ciclos son `8.x`) no deben casar: así no generan avisos falsos."""
    ciclo_regex: str
    """Expresión que extrae el ciclo de una versión instalada en su primer grupo, p. ej. `7.7.24-7` → `7`."""
    ejemplos: dict[str, CicloId] = Field(min_length=1)
    """Versión instalada → ciclo esperado: los tests comprueban `ciclo_regex` con ellos."""
    ejemplos_imagen: dict[str, CicloId | None] = {}
    """Imagen → ciclo esperado (None: no debe casar). Obligatorio con `imagen_regex`."""
    aviso_dias: int | None = Field(default=None, ge=1, le=730)
    """Días de aviso antes del fin de soporte para este producto (si no, `umbrales.soporte_dias`). Para
    productos de ciclos cortos (Prometheus: 6 semanas) que si no estarían siempre en aviso."""
    aviso_version: bool = True
    """Avisar de versión mayor nueva. No en productos de versiones frecuentes (las imágenes nuevas las
    avisa el vigilante de imágenes)."""
    comprobado: date
    ciclos: list[Ciclo] = Field(min_length=1)
    """Del más reciente al más antiguo."""

    @field_validator("ciclo_regex", "imagen_regex")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        """Desde el principio (`^…`), sin `$`, con un grupo y válida en Python y en RE2 (PromQL)."""
        if v is None:
            return v
        try:
            r = re.compile(v)
        except re.error as e:
            raise ValueError(f"la expresión no compila: {e}") from e
        if r.groups < 1:
            raise ValueError("la expresión necesita un grupo con el ciclo o la versión")
        if '"' in v or "\n" in v or re.search(r"\(\?(=|!|<=|<!)|\\[1-9]", v):
            raise ValueError("la expresión no puede llevar comillas, saltos de línea, lookarounds ni \\1")
        if not v.startswith("^") or v.endswith("$"):
            raise ValueError("la expresión empieza por `^` y no acaba en `$` (casa el principio)")
        return v

    @model_validator(mode="after")
    def _check(self) -> Producto:
        if (self.fuente == "endoflife") != (self.endoflife is not None):
            raise ValueError("`endoflife` es obligatorio con fuente endoflife y solo con ella")
        if self.fuente == "manual" and not self.referencia:
            raise ValueError("un producto a mano necesita `referencia`")
        nombres = [c.ciclo for c in self.ciclos]
        if len(set(nombres)) != len(nombres):
            raise ValueError("ciclos repetidos")
        fechas = [c.publicado for c in self.ciclos]
        if fechas != sorted(fechas, reverse=True):
            raise ValueError("los ciclos van del más reciente al más antiguo")
        for version, ciclo in self.ejemplos.items():
            if self.ciclo_de(version) != ciclo:
                raise ValueError(
                    f"ejemplo {version!r}: ciclo_regex da {self.ciclo_de(version)!r}, no {ciclo!r}"
                )
            if ciclo not in nombres:
                raise ValueError(f"ejemplo {version!r}: el ciclo {ciclo!r} no está en el catálogo")
        if self.ultimo_lts and not any(c.lts for c in self.ciclos):
            raise ValueError("ultimo_lts sin ningún ciclo LTS")
        if bool(self.imagen_regex) != bool(self.ejemplos_imagen):
            raise ValueError("`imagen_regex` y `ejemplos_imagen` van juntos")
        for imagen, esperado in self.ejemplos_imagen.items():
            da = self.ciclo_de_imagen(imagen)
            if da != esperado:
                raise ValueError(f"imagen {imagen!r}: da el ciclo {da!r}, no {esperado!r}")
        return self

    @property
    def ultimo(self) -> Ciclo:
        """Ciclo de referencia para «hay una versión mayor nueva»."""
        if self.ultimo_lts:
            return next(c for c in self.ciclos if c.lts)
        return self.ciclos[0]

    def ciclo_de(self, version: str) -> str | None:
        m = re.match(self.ciclo_regex, version)
        return m.group(1) if m else None

    def ciclo_de_imagen(self, imagen: str) -> str | None:
        """Ciclo de la versión de la etiqueta, como lo calcula PromQL (anclado al principio y al final)."""
        if not self.imagen_regex:
            return None
        m = re.fullmatch(_promql(self.imagen_regex), imagen)
        return self.ciclo_de(m.group(1)) if m else None

    @property
    def regex_promql(self) -> str:
        return _promql(self.ciclo_regex)

    @property
    def superados(self) -> list[Ciclo]:
        """Ciclos publicados antes que el de referencia (los posteriores, como un Ubuntu no LTS, no)."""
        return [c for c in self.ciclos if c.publicado < self.ultimo.publicado]


Catalogo = dict[str, Producto]


def cargar(directorio: Path = CATALOGO_DIR) -> Catalogo:
    out: Catalogo = {}
    for f in sorted(directorio.glob("*.yaml")):
        p = Producto.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        if p.producto != f.stem:
            raise ValueError(f"{f.name}: el producto se llama {p.producto!r}")
        out[p.producto] = p
    return out


@functools.cache
def catalogo() -> Catalogo:
    """El catálogo del paquete (se lee una vez por proceso)."""
    return cargar()


def hay_versiones(s: Site) -> bool:
    """El sitio tiene alguna fuente de versiones instaladas (node_os_info, el updates-exporter o cAdvisor)."""
    return any(h.node_exporter or h.cadvisor for h in s.hosts) or s.modulos.updates_exporter.activo


def _epoch(d: date) -> int:
    return int(datetime.combine(d, time(), tzinfo=UTC).timestamp())


def _regla(record: str, valor: int, **labels: str) -> dict[str, Any]:
    return {"record": record, "expr": f"vector({valor})", "labels": labels}


def _q(v: str) -> str:
    """Cadena de PromQL entre comillas dobles."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _replace(expr: str, label: str, value: str, src: str = "", regex: str = "") -> str:
    return f"label_replace({expr}, {_q(label)}, {_q(value)}, {_q(src)}, {_q(regex)})"


def _desde_os(p: Producto) -> str:
    """vigia_producto_ciclo de un producto a partir de node_os_info (distribución del sistema)."""
    ids = "|".join(re.escape(i) for i in p.os_ids)
    e = f"node_os_info{{id=~{_q(ids)}}}"
    e = _replace(e, "producto", p.producto)
    e = _replace(e, "producto_nombre", p.nombre)
    e = _replace(e, "version", "$1", "version_id", "(.*)")
    e = _replace(e, "ciclo", "$1", "version_id", p.regex_promql)
    return f"max by (nombre, producto, producto_nombre, ciclo, version) ({e})"


def _desde_exporter(p: Producto) -> str:
    """vigia_producto_ciclo de un producto a partir de vigia_producto_info (updates-exporter)."""
    e = f"{PRODUCTO_INFO}{{producto={_q(p.producto)}}}"
    e = _replace(e, "producto_nombre", p.nombre)
    e = _replace(e, "ciclo", "$1", "version", p.regex_promql)
    return f"max by (nombre, producto, producto_nombre, ciclo, version) ({e})"


def _desde_contenedor(p: Producto) -> str:
    """vigia_producto_ciclo de un producto a partir de la imagen de cada contenedor (cAdvisor)."""
    assert p.imagen_regex
    rx = _promql(p.imagen_regex)
    e = f'container_last_seen{{image=~{_q(rx)}, name!=""}}'
    e = _replace(e, "producto", p.producto)
    e = _replace(e, "producto_nombre", p.nombre)
    e = _replace(e, "contenedor", "$1", "name", "(.*)")
    e = _replace(e, "version", "$1", "image", rx)
    e = _replace(e, "ciclo", "$1", "version", p.regex_promql)
    return f"group by (nombre, contenedor, producto, producto_nombre, ciclo, version) ({e})"


def reglas(
    catalogo: Catalogo, fecha_aviso: Mapping[str, FechaAviso] | None = None, soporte_dias: int = 90
) -> dict[str, Any]:
    """Reglas de grabación de Prometheus: la tabla de ciclos (constantes) y lo derivado por equipo.

    `soporte_dias`: días de aviso de los productos sin `aviso_dias` propio (umbral del sitio)."""
    fecha_aviso = fecha_aviso or {}
    tabla: list[dict[str, Any]] = []
    for p in catalogo.values():
        aviso = fecha_aviso.get(p.producto, p.fecha_aviso)
        tabla.append(_regla(COMPROBADO, _epoch(p.comprobado), producto=p.producto))
        tabla.append(_regla(AVISO, p.aviso_dias or soporte_dias, producto=p.producto))
        for c in p.ciclos:
            tabla.append(_regla(INFO, 1, producto=p.producto, ciclo=c.ciclo, ultimo=p.ultimo.ciclo))
            fin = c.fin(aviso)
            if fin:
                tabla.append(_regla(FIN, _epoch(fin), producto=p.producto, ciclo=c.ciclo))
        for c in p.superados if p.aviso_version else []:
            tabla.append(_regla(SUPERADO, 1, producto=p.producto, ciclo=c.ciclo, ultimo=p.ultimo.ciclo))

    # etiquetas fijas por regla: sin ellas, varias reglas que graban la misma serie son «duplicadas»
    def fuente(p: Producto, origen: str, expr: str) -> dict[str, Any]:
        return {"record": PRODUCTO_CICLO, "expr": expr, "labels": {"producto": p.producto, "fuente": origen}}

    fuentes = [fuente(p, "sistema", _desde_os(p)) for p in catalogo.values() if p.os_ids]
    fuentes += [fuente(p, "updates-exporter", _desde_exporter(p)) for p in catalogo.values()]
    fuentes += [fuente(p, "contenedor", _desde_contenedor(p)) for p in catalogo.values() if p.imagen_regex]
    derivadas = [
        {
            "record": RESTANTE,
            "expr": f"({PRODUCTO_CICLO} * on (producto, ciclo) group_left () {FIN} - time()) / 86400",
        },
        {"record": MAYOR, "expr": f"{PRODUCTO_CICLO} * on (producto, ciclo) group_left (ultimo) {SUPERADO}"},
    ]
    return {
        # un solo grupo: Prometheus evalúa sus reglas en orden y cada una ve las anteriores en la misma pasada
        "groups": [{"name": "vigia-ciclos", "rules": tabla + fuentes + derivadas}]
    }


# --- refresco desde endoflife.date -------------------------------------------------------------------

Fetch = Callable[[str], Any]


def _fetch(url: str) -> Any:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "vigia"})  # noqa: S310 (https fijo)
    with urlopen(req, timeout=30) as r:  # noqa: S310
        return json.load(r)


def _fecha(v: Any, hoy: date) -> date | None:
    """endoflife.date: fecha, `false` (sin fin anunciado) o `true` (terminado sin fecha: cuenta hoy)."""
    if v is True:
        return hoy
    if isinstance(v, str):
        return date.fromisoformat(v)
    return None


def desde_endoflife(p: Producto, fetch: Fetch | None = None, hoy: date | None = None) -> Producto:
    """El mismo producto con los ciclos y la fecha de comprobación de endoflife.date."""
    if p.fuente != "endoflife" or not p.endoflife:
        raise ValueError(f"{p.producto} no se mantiene desde endoflife.date")
    hoy = hoy or date.today()
    datos = (fetch or _fetch)(ENDOFLIFE_API.format(slug=p.endoflife))
    if not isinstance(datos, list) or not datos:
        raise ValueError(f"{p.endoflife}: respuesta inesperada de endoflife.date")
    ciclos = [
        Ciclo(
            ciclo=str(r["cycle"]),
            publicado=date.fromisoformat(r["releaseDate"]),
            fin_soporte=_fecha(r.get("eol"), hoy),
            fin_extendido=_fecha(r.get("extendedSupport"), hoy),
            ultima_version=str(r["latest"]) if r.get("latest") else None,
            lts=r.get("lts") is True,
        )
        for r in datos
    ]
    ciclos.sort(key=lambda c: c.publicado, reverse=True)
    return Producto.model_validate(
        p.model_dump() | {"ciclos": [c.model_dump() for c in ciclos], "comprobado": hoy}
    )


def guardar(p: Producto, directorio: Path = CATALOGO_DIR) -> Path:
    f = directorio / f"{p.producto}.yaml"
    data = p.model_dump(mode="json", exclude_none=True)
    f.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return f
