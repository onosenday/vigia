"""Modelo de un sitio (site.yaml), validado con pydantic.

Todo lo que se genera sale de aquí: si un dato no pasa la validación, no llega a ninguna plantilla.
Los secretos nunca están en el modelo: solo el nombre de la variable de entorno que los contiene.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# --- tipos básicos -----------------------------------------------------------------------------------

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
"""Identificador: minúsculas, dígitos y guiones. Va a nombres de contenedor, uid y etiquetas."""

Texto = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f`$\\{}<>]*$")]
"""Texto visible (nombres, títulos): sin caracteres de control, `$`, llaves, `<>` ni barras invertidas,
para que no pueda interpretarse en compose (`${…}`), Jinja, Grafana (`${var}`) ni HTML."""

TextoOpcional = Annotated[str, StringConstraints(max_length=80, pattern=r"^[^\x00-\x1f`$\\{}<>]*$")]

NombreVariable = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
"""Nombre de una variable del fichero de entorno del sitio (nunca su valor)."""

Duracion = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,5}(ms|s|m|h|d|w|y)$")]
Puerto = Annotated[int, Field(ge=1, le=65535)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
RutaRemota = Annotated[str, StringConstraints(pattern=r"^/[A-Za-z0-9._/@+-]*$", max_length=255)]
Iface = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,15}$")]
_RE_IMAGEN = r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?$"
Imagen = Annotated[str, StringConstraints(pattern=_RE_IMAGEN)]
_RE_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_RE_FQDN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"


def _ip(v: str) -> str:
    return str(ipaddress.ip_address(v))


IP = Annotated[str, AfterValidator(_ip)]


def _url(v: str) -> str:
    p = urlsplit(v)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError(f"URL no válida (http/https con host): {v!r}")
    if p.username or p.password:
        raise ValueError("la URL no puede llevar usuario ni contraseña: usa una variable de entorno")
    if re.search(r"[\s\"'`$\\{}<>]", v):
        raise ValueError(f"la URL contiene caracteres no permitidos: {v!r}")
    return v


URL = Annotated[str, AfterValidator(_url)]


def _ruta_sitio(v: Path) -> Path:
    if v.is_absolute() or ".." in v.parts:
        raise ValueError(f"ruta fuera del sitio: {v} (debe ser relativa y sin '..')")
    return v


RutaSitio = Annotated[Path, AfterValidator(_ruta_sitio)]
"""Fichero dentro de la carpeta del sitio (assets/, devices.yaml)."""


def _host_puerto(v: str) -> str:
    m = re.fullmatch(r"([0-9.]+|[A-Za-z0-9.-]+):([0-9]{1,5})", v)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise ValueError(f"se espera host:puerto: {v!r}")
    return v


HostPuerto = Annotated[str, AfterValidator(_host_puerto)]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


# --- perfiles por tipo de equipo -------------------------------------------------------------------


class Tipo(StrEnum):
    linux = "linux"
    omv = "omv"
    raspbian = "raspbian"
    proxmox = "proxmox"
    synology = "synology"
    qnap = "qnap"
    truenas = "truenas"
    windows = "windows"
    router = "router"
    switch = "switch"
    ap = "ap"
    impresora = "impresora"
    sai = "sai"
    otro = "otro"


class Perfil(Base):
    """Qué sabe hacer vigia con un tipo de equipo."""

    metricas: Literal["node", "windows", "snmp", "ninguna"]
    """Exporter natural del tipo: node_exporter, windows_exporter, SNMP o solo ping/HTTP."""
    snmp_modulo: str | None = None
    """Módulo de snmp_exporter (de su snmp.yml por defecto) si se mide por SNMP."""
    actualizaciones: Literal["apt", "syno", "ninguna"] = "ninguna"
    docker: bool = False
    """Puede alojar contenedores (y por tanto cAdvisor o la propia monitorización)."""
    grupo_ping: str = "servidor"


PERFILES: dict[Tipo, Perfil] = {
    Tipo.linux: Perfil(metricas="node", actualizaciones="apt", docker=True),
    Tipo.omv: Perfil(metricas="node", actualizaciones="apt", docker=True),
    Tipo.raspbian: Perfil(metricas="node", actualizaciones="apt", docker=True),
    Tipo.proxmox: Perfil(metricas="node", actualizaciones="apt"),
    Tipo.synology: Perfil(
        metricas="snmp", snmp_modulo="synology", actualizaciones="syno", docker=True, grupo_ping="nas"
    ),
    Tipo.qnap: Perfil(metricas="snmp", snmp_modulo="if_mib", grupo_ping="nas"),
    Tipo.truenas: Perfil(metricas="node", grupo_ping="nas"),
    Tipo.windows: Perfil(metricas="windows"),
    Tipo.router: Perfil(metricas="ninguna", grupo_ping="red"),
    Tipo.switch: Perfil(metricas="snmp", snmp_modulo="if_mib", grupo_ping="red"),
    Tipo.ap: Perfil(metricas="ninguna", grupo_ping="red"),
    Tipo.impresora: Perfil(metricas="snmp", snmp_modulo="printer_mib", grupo_ping="perifericos"),
    Tipo.sai: Perfil(metricas="snmp", snmp_modulo="ups_mib", grupo_ping="perifericos"),
    Tipo.otro: Perfil(metricas="ninguna", grupo_ping="otros"),
}


# --- branding ---------------------------------------------------------------------------------------


class Colores(Base):
    primario: Color = "#1f6feb"
    acento: Color = "#f59e0b"


class Branding(Base):
    nombre: Texto
    """Nombre corto del sitio en asuntos de alertas, portada e informes (Casa, Oficina…)."""
    prefijo_titulo: TextoOpcional = ""
    """Se antepone al título de cada panel ("Oficina · ")."""
    carpeta: Texto
    """Carpeta de Grafana donde se provisionan los paneles."""
    uid_prefijo: Id
    """Prefijo de los uid de los paneles (`<prefijo>-servidores`); cambiarlo rompe los enlaces guardados."""
    tag: Texto
    """Tag de los paneles y nombre del proveedor de provisioning."""
    colores: Colores = Colores()
    logo: RutaSitio | None = None
    favicon: RutaSitio | None = None
    tema: Literal["dark", "light"] = "dark"
    portada: bool = True
    """Genera el panel «Inicio» con el logo y lo pone como página de inicio de Grafana."""
    grafana: bool = True
    """Aplica el branding a Grafana: nombre de instancia, tema, logo y favicon."""


# --- hosts ------------------------------------------------------------------------------------------


class Exporter(Base):
    puerto: Puerto
    gestion: Literal["vigia", "externo"] = "vigia"
    """`vigia` lo despliega; `externo` ya está instalado por otro medio y solo se consulta."""


class Snmp(Base):
    auth: Id = "por-defecto"
    """Nombre de la autenticación en `snmp.auths` del sitio."""
    modulo: str | None = None
    """Módulo de snmp_exporter; por defecto, el del perfil del tipo."""


class Actualizaciones(Base):
    usuario: Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")] = "updexp"
    intervalo_min: int | None = Field(default=None, ge=600, le=7 * 86400)
    """Segundos mínimos entre consultas (para equipos cuyos discos hibernan)."""


class DeployOMV(Base):
    adaptador: Literal["omv"]
    stack: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
    uuid: Annotated[str, StringConstraints(pattern=_RE_UUID)]
    dir: RutaRemota | None = None
    """Carpeta del stack (la de los ficheros que monta el compose); no hace falta si solo hay body."""


class DeployCompose(Base):
    adaptador: Literal["compose"]
    dir: RutaRemota
    usuario: Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]


class DeploySynology(Base):
    adaptador: Literal["synology"]
    dir: RutaRemota
    usuario: Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]


Deploy = Annotated[DeployOMV | DeployCompose | DeploySynology, Field(discriminator="adaptador")]


class IpExtra(Base):
    ip: IP
    nombre: Texto


class PiholeHost(Base):
    url: URL
    primaria: bool = False


class Host(Base):
    id: Id
    nombre: Texto | None = None
    """Nombre visible; por defecto, el id."""
    tipo: Tipo
    ip: IP
    ips_extra: list[IpExtra] = []
    grupo: Id | None = None
    """Grupo en el panel de ping; por defecto, el del perfil del tipo."""
    ssh_puerto: Puerto = 22
    node_exporter: Exporter | None = None
    windows_exporter: Exporter | None = None
    cadvisor: Exporter | None = None
    snmp: Snmp | None = None
    docker_root: RutaRemota = "/var/lib/docker"
    discos_hibernan: bool = False
    """Sus discos duermen: solo se le sondean URLs que den 200 y con el intervalo mínimo."""
    actualizaciones: Actualizaciones | None = None
    pihole: PiholeHost | None = None
    deploy: Deploy | None = None
    """Cómo se despliegan los agentes (node_exporter, cAdvisor…) en este host."""

    @property
    def visible(self) -> str:
        return self.nombre or self.id

    @property
    def perfil(self) -> Perfil:
        return PERFILES[self.tipo]

    @property
    def grupo_ping(self) -> str:
        return self.grupo or self.perfil.grupo_ping

    @property
    def ips(self) -> list[str]:
        return [self.ip, *(e.ip for e in self.ips_extra)]

    @model_validator(mode="after")
    def _coherente(self) -> Host:
        p = self.perfil
        if self.cadvisor and not p.docker:
            raise ValueError(f"host {self.id}: el tipo {self.tipo} no ejecuta Docker (cAdvisor)")
        if self.windows_exporter and self.tipo is not Tipo.windows:
            raise ValueError(f"host {self.id}: windows_exporter solo en tipo windows")
        if self.actualizaciones and p.actualizaciones == "ninguna":
            raise ValueError(f"host {self.id}: el tipo {self.tipo} no admite comprobar actualizaciones")
        return self


class Vip(Base):
    """IP virtual (keepalived, balanceador) compartida por varios hosts."""

    id: Id
    ip: IP
    nombre: Texto
    grupo: Id = "core"


# --- objetivos --------------------------------------------------------------------------------------


class Ping(Base):
    """Equipo vigilado por ping. Con `host`, la IP, el nombre y el grupo salen de su ficha."""

    host: Id | None = None
    ip: IP | None = None
    nombre: Texto | None = None
    grupo: Id | None = None

    @model_validator(mode="after")
    def _algo(self) -> Ping:
        if not self.host and not (self.ip and self.nombre):
            raise ValueError("un ping necesita `host` o bien `ip` y `nombre`")
        return self


MODULOS_BLACKBOX = ("http_any", "https_interno", "minecraft")


class Servicio(Base):
    """Servicio por IP:puerto (paneles de administración, APIs)."""

    url: URL | HostPuerto
    nombre: Texto
    host: Id
    """Host (o VIP) donde corre: agrupa el servicio en los paneles."""
    modulo: Literal["http_any", "https_interno", "minecraft"] | None = None
    """Sonda de blackbox si no es la normal (`http_any`)."""
    espera_200: bool = False
    """Confirmado que responde 200: obligatorio en hosts cuyos discos hibernan."""

    @model_validator(mode="after")
    def _modulo(self) -> Servicio:
        es_url = "://" in self.url
        if not es_url and self.modulo in (None, "http_any", "https_interno"):
            raise ValueError(f"servicio {self.nombre}: host:puerto necesita un módulo TCP (p. ej. minecraft)")
        if es_url and self.modulo == "minecraft":
            raise ValueError(f"servicio {self.nombre}: el módulo minecraft va con host:puerto, no con URL")
        return self


class Web(Base):
    url: URL
    nombre: Texto


class WebConfig(Base):
    ca: RutaSitio | None = None
    """CA interna (en assets/) para validar los certificados y medir su caducidad."""
    objetivos: list[Web] = []


class DnsServidor(Base):
    ip: IP


class Dns(Base):
    consulta: Annotated[str, StringConstraints(pattern=_RE_FQDN)]
    espera: IP
    servidores: list[IP]
    etiqueta_servidor: Id = "dns"


# --- módulos ----------------------------------------------------------------------------------------


class Autorizacion(Base):
    """Constancia de que el responsable de la red autoriza el descubrimiento activo (arp-scan, nmap)."""

    responsable: Texto
    fecha: date
    referencia: Texto


class Netinv(Base):
    activo: bool = False
    nmap: bool = False
    intervalo: int = Field(default=900, ge=300, le=86400)
    puerto: Puerto = 9877
    iface: Iface | None = None
    dispositivos: RutaSitio | None = None
    """devices.yaml del sitio (clasificación manual). Nunca entra en el paquete."""
    autorizacion: Autorizacion | None = None

    @model_validator(mode="after")
    def _autorizado(self) -> Netinv:
        if self.activo and self.autorizacion is None:
            raise ValueError("netinv activo exige `autorizacion` (responsable, fecha y referencia)")
        return self


class PiholeExporter(Base):
    activo: bool = False
    puerto: Puerto = 9617
    secreto: NombreVariable | None = None
    """Variable con las contraseñas de aplicación de las Pi-hole, separadas por comas, en su orden."""


class UpdatesExporter(Base):
    activo: bool = False
    host: Id | None = None
    puerto: Puerto = 8099
    intervalo: int = Field(default=3600, ge=600, le=86400)
    claves: RutaRemota | None = None
    """Carpeta del host con la clave SSH dedicada (montada :ro, nunca en git)."""


class SnmpAuth(Base):
    nombre: Id
    version: Literal["v3", "v2c"] = "v3"
    usuario: NombreVariable | None = None
    clave_auth: NombreVariable | None = None
    clave_priv: NombreVariable | None = None
    comunidad: NombreVariable | None = None
    """Todos son nombres de variables de entorno: los valores no pasan nunca por el modelo."""

    @model_validator(mode="after")
    def _completa(self) -> SnmpAuth:
        if self.version == "v3" and not (self.usuario and self.clave_auth and self.clave_priv):
            raise ValueError(f"snmp {self.nombre}: v3 necesita usuario, clave_auth y clave_priv (authPriv)")
        if self.version == "v2c" and not self.comunidad:
            raise ValueError(f"snmp {self.nombre}: v2c necesita comunidad")
        return self


class SnmpModulo(Base):
    activo: bool = False
    puerto: Puerto = 9116
    auths: list[SnmpAuth] = []


class Modulos(Base):
    blackbox: bool = True
    netinv: Netinv = Netinv()
    pihole_exporter: PiholeExporter = PiholeExporter()
    updates_exporter: UpdatesExporter = UpdatesExporter()
    snmp: SnmpModulo = SnmpModulo()


# --- monitor y sitio --------------------------------------------------------------------------------

IMAGENES_POR_DEFECTO: dict[str, str] = {
    "grafana": "grafana/grafana-oss",
    "prometheus": "prom/prometheus",
    "blackbox": "prom/blackbox-exporter",
    "node_exporter": "quay.io/prometheus/node-exporter",
    "cadvisor": "ghcr.io/google/cadvisor",
    "pihole_exporter": "ekofr/pihole-exporter",
    "snmp_exporter": "prom/snmp-exporter",
}


class Puertos(Base):
    grafana: Puerto = 3300
    prometheus: Puerto = 9390


class Monitor(Base):
    host: Id
    """Host que ejecuta Prometheus, Grafana y las sondas."""
    proyecto: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
    """Proyecto de compose (en OMV, nombre del stack)."""
    prefijo_contenedores: Annotated[str, StringConstraints(pattern=r"^([a-z][a-z0-9-]{0,19}-)?$")] = ""
    puertos: Puertos = Puertos()
    retencion: Duracion = "90d"
    intervalo: Duracion = "30s"
    timeout: Duracion = "10s"
    grafana_url: URL
    grafana_plugins: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,60}$")]] = []
    dns: list[IP] = []
    """Servidores DNS del contenedor de sondas (si el de Docker no resuelve los nombres internos)."""
    imagenes: dict[str, Imagen] = {}
    watchtower: bool = False
    """Etiqueta los contenedores para que watchtower los actualice."""
    etiqueta_sitio: bool = True
    """Añade `site: <id>` a las external_labels de Prometheus (federación, alertas)."""

    @field_validator("imagenes")
    @classmethod
    def _imagenes(cls, v: dict[str, str]) -> dict[str, str]:
        desconocidas = set(v) - set(IMAGENES_POR_DEFECTO)
        if desconocidas:
            raise ValueError(f"imágenes desconocidas: {sorted(desconocidas)}")
        return v

    def imagen(self, nombre: str) -> str:
        return self.imagenes.get(nombre, IMAGENES_POR_DEFECTO[nombre])


class Red(Base):
    subred: Annotated[str, AfterValidator(lambda v: str(ipaddress.ip_network(v)))]
    dominio: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)*$")]


class SitioInfo(Base):
    id: Id
    nombre: Texto


class Bridge(Base):
    host: Id
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]
    nombre: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]


class Site(Base):
    vigia: Annotated[str, StringConstraints(pattern=r"^[0-9<>=!~,. ]+$")]
    """Rango de versiones de vigia con el que se probó el sitio."""
    sitio: SitioInfo
    branding: Branding
    red: Red
    monitor: Monitor
    hosts: list[Host]
    """El orden de la lista es el orden de los servidores en los paneles."""
    vips: list[Vip] = []
    ping: list[Ping] = []
    servicios: list[Servicio] = []
    web: WebConfig = WebConfig()
    dns: Dns | None = None
    modulos: Modulos = Modulos()
    bridges: list[Bridge] = []
    """Redes Docker por host (salida de `vigia bridges`), para nombrar las interfaces br-<id>."""

    # -- consultas ------------------------------------------------------------------------------------

    def host(self, id_: str) -> Host:
        for h in self.hosts:
            if h.id == id_:
                return h
        raise KeyError(id_)

    @property
    def monitor_host(self) -> Host:
        return self.host(self.monitor.host)

    @property
    def piholes(self) -> list[Host]:
        return [h for h in self.hosts if h.pihole]

    def ping_resuelto(self) -> list[tuple[str, str, str]]:
        """(ip, nombre, grupo) de cada objetivo de ping, en orden."""
        vips = {v.id: v for v in self.vips}
        out = []
        for p in self.ping:
            if p.host in vips:
                v = vips[p.host]
                out.append((v.ip, p.nombre or v.nombre, p.grupo or v.grupo))
            elif p.host:
                h = self.host(p.host)
                out.append((p.ip or h.ip, p.nombre or h.visible, p.grupo or h.grupo_ping))
            else:
                out.append((str(p.ip), str(p.nombre), p.grupo or "otros"))
        return out

    def avisos(self) -> list[str]:
        """Riesgos que no impiden generar, pero conviene revisar."""
        out = []
        for a in self.modulos.snmp.auths:
            if a.version == "v2c":
                out.append(f"snmp {a.nombre}: v2c va en claro por la red; usa v3 si el equipo lo admite")
        p = self.monitor.puertos
        if p.grafana == 3000 or p.prometheus == 9090:
            out.append("monitor.puertos: Grafana/Prometheus en su puerto por defecto")
        if self.modulos.netinv.activo and self.modulos.netinv.nmap:
            out.append("netinv con nmap: escaneo activo de puertos; confirma que la autorización lo cubre")
        if (
            not self.monitor.imagenes.get("grafana", "").count(":")
            and self.branding.grafana
            and (self.branding.logo or self.branding.favicon)
        ):
            out.append("branding con logo/favicon y Grafana sin versión fija: puede romperse al actualizar")
        return out

    # -- validación cruzada ----------------------------------------------------------------------------

    @model_validator(mode="after")
    def _cruzada(self) -> Site:
        errores: list[str] = []
        red = ipaddress.ip_network(self.red.subred)

        ids = [h.id for h in self.hosts] + [v.id for v in self.vips]
        repetidos = {i for i in ids if ids.count(i) > 1}
        if repetidos:
            errores.append(f"ids repetidos: {sorted(repetidos)}")
        ids_set = set(ids)

        ips = [ip for h in self.hosts for ip in h.ips] + [v.ip for v in self.vips]
        for ip in ips:
            if ipaddress.ip_address(ip) not in red:
                errores.append(f"IP {ip} fuera de la subred {red}")
        rep_ip = {i for i in ips if ips.count(i) > 1}
        if rep_ip:
            errores.append(f"IPs repetidas: {sorted(rep_ip)}")

        if self.monitor.host not in {h.id for h in self.hosts}:
            errores.append(f"monitor.host {self.monitor.host!r} no es un host")
        elif not self.monitor_host.perfil.docker:
            errores.append(f"monitor.host {self.monitor.host!r} es de un tipo sin Docker")

        hosts_por_id = {h.id: h for h in self.hosts}
        for p in self.ping:
            if p.host and p.host not in ids_set:
                errores.append(f"ping: host desconocido {p.host!r}")
            elif p.host in hosts_por_id and p.ip and p.ip not in hosts_por_id[p.host].ips:
                errores.append(f"ping: {p.ip} no es una IP de {p.host}")

        for s in self.servicios:
            if s.host not in ids_set:
                errores.append(f"servicio {s.nombre}: host desconocido {s.host!r}")
            h = hosts_por_id.get(s.host)
            if h and h.discos_hibernan and not s.espera_200:
                errores.append(
                    f"servicio {s.nombre}: {h.id} hiberna sus discos; confirma que responde 200 "
                    "y marca `espera_200: true` (un 403/404 escribe en sus logs y los despierta)"
                )

        if self.dns:
            for ip in self.dns.servidores:
                if ip not in ips:
                    errores.append(f"dns: {ip} no es un host ni una VIP del sitio")

        m = self.modulos
        if m.pihole_exporter.activo:
            if not self.piholes:
                errores.append("pihole_exporter activo sin ningún host con `pihole`")
            if not m.pihole_exporter.secreto:
                errores.append("pihole_exporter activo sin `secreto`")
        if m.netinv.activo and self.piholes and not m.pihole_exporter.secreto:
            errores.append("netinv consulta las Pi-hole: falta modulos.pihole_exporter.secreto")
        if m.updates_exporter.activo:
            if m.updates_exporter.host not in hosts_por_id:
                errores.append("updates_exporter activo sin `host` válido")
            if not m.updates_exporter.claves:
                errores.append("updates_exporter activo sin `claves`")
        for h in self.hosts:
            if h.actualizaciones and not m.updates_exporter.activo:
                errores.append(f"host {h.id}: tiene `actualizaciones` pero updates_exporter está inactivo")
            if h.snmp:
                if not m.snmp.activo:
                    errores.append(f"host {h.id}: tiene `snmp` pero el módulo snmp está inactivo")
                elif h.snmp.auth not in {a.nombre for a in m.snmp.auths}:
                    errores.append(f"host {h.id}: auth SNMP desconocida {h.snmp.auth!r}")
            if h.cadvisor and h.cadvisor.gestion == "vigia" and h.id != self.monitor.host and not h.deploy:
                errores.append(f"host {h.id}: cAdvisor gestionado por vigia necesita `deploy`")
            if (
                h.node_exporter
                and h.node_exporter.gestion == "vigia"
                and h.id != self.monitor.host
                and not h.deploy
            ):
                errores.append(f"host {h.id}: node_exporter gestionado por vigia necesita `deploy`")

        primarias = [h for h in self.piholes if h.pihole and h.pihole.primaria]
        if len(primarias) > 1:
            errores.append("solo puede haber una Pi-hole primaria")

        for b in self.bridges:
            if b.host not in hosts_por_id:
                errores.append(f"bridges: host desconocido {b.host!r}")

        if errores:
            raise ValueError("; ".join(errores))
        return self


def cargar(ruta: Path) -> Site:
    """Lee y valida un site.yaml (solo `yaml.safe_load`)."""
    with ruta.open(encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta}: se esperaba un mapa YAML")
    bridges = ruta.parent / "bridges.yaml"
    if "bridges" not in datos and bridges.exists():
        with bridges.open(encoding="utf-8") as f:
            datos["bridges"] = yaml.safe_load(f) or []
    return Site.model_validate(datos)
