"""Modelo de un sitio (site.yaml), validado con pydantic.

Todo lo que se genera sale de aquí: si un dato no pasa la validación, no llega a ninguna plantilla.
Los secretos nunca están en el modelo: solo el nombre de la variable de entorno que los contiene.
"""

from __future__ import annotations

import ipaddress
import posixpath
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from vigia import __version__

# --- tipos básicos -----------------------------------------------------------------------------------

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
"""Identificador: minúsculas, dígitos y guiones. Va a nombres de contenedor, uid y etiquetas."""

Text = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f`$\\{}<>]*$")]
"""Texto visible (nombres, títulos): sin caracteres de control, `$`, llaves, `<>` ni barras invertidas,
para que no pueda interpretarse en compose (`${…}`), Jinja, Grafana (`${var}`) ni HTML."""

OptionalText = Annotated[str, StringConstraints(max_length=80, pattern=r"^[^\x00-\x1f`$\\{}<>]*$")]

EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
"""Nombre de una variable del fichero de entorno del sitio (nunca su valor)."""

Duration = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,5}(ms|s|m|h|d|w|y)$")]
Port = Annotated[int, Field(ge=1, le=65535)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
_FORBIDDEN_DIRS = {
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/lib",
    "/lib64",
    "/opt",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/srv",
    "/sys",
    "/tmp",  # noqa: S108 - lista de rutas prohibidas
    "/usr",
    "/var",
    "/volume1",
    "/mnt",
    "/media",
}


def _remote_path(v: str) -> str:
    """Ruta absoluta normalizada y con al menos dos niveles: sobre ella se borra y se copia como root."""
    if posixpath.normpath(v) != v or "//" in v or v.endswith("/"):
        raise ValueError(f"ruta remota no normalizada: {v!r}")
    parts = [p for p in v.split("/") if p]
    if len(parts) < 2 or any(p in (".", "..") for p in parts) or v in _FORBIDDEN_DIRS:
        raise ValueError(f"ruta remota demasiado general o peligrosa: {v!r}")
    return v


RemotePath = Annotated[
    str,
    StringConstraints(pattern=r"^/[A-Za-z0-9._/@+-]*$", max_length=255),
    AfterValidator(_remote_path),
]
Iface = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,15}$")]
_IMAGE_RE = r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?$"
ImageRef = Annotated[str, StringConstraints(pattern=_IMAGE_RE)]
_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
FQDN_RE = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"


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


def _site_path(v: Path) -> Path:
    if v.is_absolute() or ".." in v.parts:
        raise ValueError(f"ruta fuera del sitio: {v} (debe ser relativa y sin '..')")
    return v


SitePath = Annotated[Path, AfterValidator(_site_path)]
"""Fichero dentro de la carpeta del sitio (assets/, devices.yaml)."""


def _host_port(v: str) -> str:
    m = re.fullmatch(r"([0-9.]+|[A-Za-z0-9.-]+):([0-9]{1,5})", v)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise ValueError(f"se espera host:puerto: {v!r}")
    return v


HostPort = Annotated[str, AfterValidator(_host_port)]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


# --- perfiles por tipo de equipo -------------------------------------------------------------------


class DeviceType(StrEnum):
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


class Profile(Base):
    """Qué sabe hacer vigia con un tipo de equipo."""

    metrics: Literal["node", "windows", "snmp", "ninguna"]
    """Exporter natural del tipo: node_exporter, windows_exporter, SNMP o solo ping/HTTP."""
    snmp_module: str | None = None
    """Módulo de snmp_exporter (de su snmp.yml por defecto) si se mide por SNMP."""
    updates: Literal["apt", "syno", "ninguna"] = "ninguna"
    docker: bool = False
    """Puede alojar contenedores (y por tanto cAdvisor o la propia monitorización)."""
    ping_group: str = "servidor"


PROFILES: dict[DeviceType, Profile] = {
    DeviceType.linux: Profile(metrics="node", updates="apt", docker=True),
    DeviceType.omv: Profile(metrics="node", updates="apt", docker=True),
    DeviceType.raspbian: Profile(metrics="node", updates="apt", docker=True),
    DeviceType.proxmox: Profile(metrics="node", updates="apt"),
    DeviceType.synology: Profile(
        metrics="snmp", snmp_module="synology", updates="syno", docker=True, ping_group="nas"
    ),
    DeviceType.qnap: Profile(metrics="snmp", snmp_module="if_mib", ping_group="nas"),
    DeviceType.truenas: Profile(metrics="node", ping_group="nas"),
    DeviceType.windows: Profile(metrics="windows"),
    DeviceType.router: Profile(metrics="ninguna", ping_group="red"),
    DeviceType.switch: Profile(metrics="snmp", snmp_module="if_mib", ping_group="red"),
    DeviceType.ap: Profile(metrics="ninguna", ping_group="red"),
    DeviceType.impresora: Profile(
        metrics="snmp", snmp_module="printer_mib,hrDevice,vigia_impresora", ping_group="perifericos"
    ),
    DeviceType.sai: Profile(metrics="snmp", snmp_module="ups_mib", ping_group="perifericos"),
    DeviceType.otro: Profile(metrics="ninguna", ping_group="otros"),
}


# --- branding ---------------------------------------------------------------------------------------


class Colors(Base):
    primario: Color = "#1f6feb"
    acento: Color = "#f59e0b"


class Branding(Base):
    nombre: Text
    """Nombre corto del sitio en asuntos de alertas, portada e informes (Casa, Oficina…)."""
    prefijo_titulo: OptionalText = ""
    """Se antepone al título de cada panel ("Oficina · ")."""
    carpeta: Text
    """Carpeta de Grafana donde se provisionan los paneles."""
    uid_prefijo: Id
    """Prefijo de los uid de los paneles (`<prefijo>-servidores`); cambiarlo rompe los enlaces guardados."""
    tag: Text
    """Tag de los paneles y nombre del proveedor de provisioning."""
    colores: Colors = Colors()
    logo: SitePath | None = None
    favicon: SitePath | None = None
    tema: Literal["dark", "light"] = "dark"
    portada: bool = True
    """Genera el panel «Inicio» con el logo y lo pone como página de inicio de Grafana."""
    grafana: bool = True
    """Aplica el branding a Grafana: nombre de instancia, tema, logo y favicon."""


# --- hosts ------------------------------------------------------------------------------------------


class Exporter(Base):
    puerto: Port
    gestion: Literal["vigia", "externo"] = "vigia"
    """`vigia` lo despliega; `externo` ya está instalado por otro medio y solo se consulta."""


class Snmp(Base):
    auth: Id = "por-defecto"
    """Nombre de la autenticación en `snmp.auths` del sitio."""
    modulo: str | None = None
    """Módulo de snmp_exporter; por defecto, el del perfil del tipo."""


class Updates(Base):
    usuario: Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")] = "updexp"
    intervalo_min: int | None = Field(default=None, ge=600, le=7 * 86400)
    """Segundos mínimos entre consultas (para equipos cuyos discos hibernan)."""


UserName = Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]
StackName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]


class SshAccess(Base):
    """Cómo entra vigia en el host para desplegar. Solo nombres de variables, nunca valores."""

    usuario: UserName
    clave: bool = True
    """Autenticación por clave SSH (BatchMode). Si es `false`, contraseña de `secreto` con sshpass."""
    secreto: EnvVarName | None = None
    sudo_secreto: list[EnvVarName] = []
    """Variables con la contraseña de sudo (se usa la primera que tenga valor); vacía = sin sudo."""

    @model_validator(mode="after")
    def _password_needs_secret(self) -> SshAccess:
        if not self.clave and not self.secreto:
            raise ValueError("ssh sin clave necesita `secreto` (variable con la contraseña)")
        return self


class DeployOMV(Base):
    adaptador: Literal["omv"]
    stack: StackName
    uuid: Annotated[str, StringConstraints(pattern=_UUID_RE)]
    dir: RemotePath | None = None
    """Carpeta del stack (la de los ficheros que monta el compose); no hace falta si solo hay body."""


class DeployCompose(Base):
    adaptador: Literal["compose"]
    dir: RemotePath
    proyecto: StackName | None = None
    """Proyecto de compose; por defecto, el de la unidad (monitor.proyecto, `<host>-agentes`…)."""


class DeploySynology(Base):
    """Container Manager de DSM: docker en /usr/local/bin y siempre con sudo."""

    adaptador: Literal["synology"]
    dir: RemotePath
    proyecto: StackName | None = None


Deploy = Annotated[DeployOMV | DeployCompose | DeploySynology, Field(discriminator="adaptador")]


class ExtraIp(Base):
    ip: IP
    nombre: Text


class PiholeHost(Base):
    url: URL
    primaria: bool = False


class Host(Base):
    id: Id
    nombre: Text | None = None
    """Nombre visible; por defecto, el id."""
    tipo: DeviceType
    ip: IP
    ips_extra: list[ExtraIp] = []
    grupo: Id | None = None
    """Grupo en el panel de ping; por defecto, el del perfil del tipo."""
    ssh_puerto: Port = 22
    ssh: SshAccess | None = None
    node_exporter: Exporter | None = None
    windows_exporter: Exporter | None = None
    cadvisor: Exporter | None = None
    snmp: Snmp | None = None
    docker_root: RemotePath = "/var/lib/docker"
    discos_hibernan: bool = False
    """Sus discos duermen: solo se le sondean URLs que den 200 y con el intervalo mínimo."""
    actualizaciones: Updates | None = None
    pihole: PiholeHost | None = None
    deploy: Deploy | None = None
    """Cómo se despliegan los agentes (node_exporter, cAdvisor…) en este host."""

    @property
    def display_name(self) -> str:
        return self.nombre or self.id

    @property
    def profile(self) -> Profile:
        return PROFILES[self.tipo]

    @property
    def is_printer_snmp(self) -> bool:
        return self.tipo is DeviceType.impresora and self.snmp is not None

    @property
    def ping_group(self) -> str:
        return self.grupo or self.profile.ping_group

    @property
    def ips(self) -> list[str]:
        return [self.ip, *(e.ip for e in self.ips_extra)]

    @model_validator(mode="after")
    def _check_consistency(self) -> Host:
        p = self.profile
        if self.cadvisor and not p.docker:
            raise ValueError(f"host {self.id}: el tipo {self.tipo} no ejecuta Docker (cAdvisor)")
        if self.windows_exporter and self.tipo is not DeviceType.windows:
            raise ValueError(f"host {self.id}: windows_exporter solo en tipo windows")
        if self.actualizaciones and p.updates == "ninguna":
            raise ValueError(f"host {self.id}: el tipo {self.tipo} no admite comprobar actualizaciones")
        return self


class Vip(Base):
    """IP virtual (keepalived, balanceador) compartida por varios hosts."""

    id: Id
    ip: IP
    nombre: Text
    grupo: Id = "core"


# --- objetivos --------------------------------------------------------------------------------------


class Ping(Base):
    """Equipo vigilado por ping. Con `host`, la IP, el nombre y el grupo salen de su ficha."""

    host: Id | None = None
    ip: IP | None = None
    nombre: Text | None = None
    grupo: Id | None = None
    alerta: bool = True
    """`false` para equipos que se apagan a propósito: se vigilan en los paneles, pero no avisan."""

    @model_validator(mode="after")
    def _check_target(self) -> Ping:
        if not self.host and not (self.ip and self.nombre):
            raise ValueError("un ping necesita `host` o bien `ip` y `nombre`")
        return self


BLACKBOX_MODULES = ("http_any", "https_interno", "minecraft")


class Service(Base):
    """Servicio por IP:puerto (paneles de administración, APIs)."""

    url: URL | HostPort
    nombre: Text
    host: Id
    """Host (o VIP) donde corre: agrupa el servicio en los paneles."""
    modulo: Literal["http_any", "https_interno", "minecraft"] | None = None
    """Sonda de blackbox si no es la normal (`http_any`)."""
    espera_200: bool = False
    """Confirmado que responde 200: obligatorio en hosts cuyos discos hibernan."""
    alerta: bool = True

    @model_validator(mode="after")
    def _check_module(self) -> Service:
        is_url = "://" in self.url
        if not is_url and self.modulo in (None, "http_any", "https_interno"):
            raise ValueError(f"servicio {self.nombre}: host:puerto necesita un módulo TCP (p. ej. minecraft)")
        if is_url and self.modulo == "minecraft":
            raise ValueError(f"servicio {self.nombre}: el módulo minecraft va con host:puerto, no con URL")
        return self


class Web(Base):
    url: URL
    nombre: Text
    alerta: bool = True


class WebConfig(Base):
    ca: SitePath | None = None
    """CA interna (en assets/) para validar los certificados y medir su caducidad."""
    objetivos: list[Web] = []


class DnsServer(Base):
    ip: IP


class Dns(Base):
    consulta: Annotated[str, StringConstraints(pattern=FQDN_RE)]
    espera: IP
    servidores: list[IP]
    etiqueta_servidor: Id = "dns"


# --- módulos ----------------------------------------------------------------------------------------


class Authorization(Base):
    """Constancia de que el responsable de la red autoriza el descubrimiento activo (arp-scan, nmap)."""

    responsable: Text
    fecha: date
    referencia: Text


class Netinv(Base):
    activo: bool = False
    nmap: bool = False
    intervalo: int = Field(default=900, ge=300, le=86400)
    puerto: Port = 9877
    iface: Iface | None = None
    dispositivos: SitePath | None = None
    """devices.yaml del sitio (clasificación manual). Nunca entra en el paquete."""
    autorizacion: Authorization | None = None

    @model_validator(mode="after")
    def _check_authorized(self) -> Netinv:
        if self.activo and self.autorizacion is None:
            raise ValueError("netinv activo exige `autorizacion` (responsable, fecha y referencia)")
        return self


class PiholeExporter(Base):
    activo: bool = False
    puerto: Port = 9617
    secreto: EnvVarName | None = None
    """Variable con las contraseñas de aplicación de las Pi-hole, separadas por comas, en su orden."""


class UpdatesExporter(Base):
    activo: bool = False
    host: Id | None = None
    puerto: Port = 8099
    intervalo: int = Field(default=3600, ge=600, le=86400)
    claves: RemotePath | None = None
    """Carpeta del host con la clave SSH dedicada (montada :ro, nunca en git)."""
    deploy: Deploy | None = None


class SnmpAuth(Base):
    nombre: Id
    version: Literal["v3", "v2c"] = "v3"
    usuario: EnvVarName | None = None
    clave_auth: EnvVarName | None = None
    clave_priv: EnvVarName | None = None
    comunidad: EnvVarName | None = None
    """Todos son nombres de variables de entorno: los valores no pasan nunca por el modelo."""

    @model_validator(mode="after")
    def _check_complete(self) -> SnmpAuth:
        if self.version == "v3" and not (self.usuario and self.clave_auth and self.clave_priv):
            raise ValueError(f"snmp {self.nombre}: v3 necesita usuario, clave_auth y clave_priv (authPriv)")
        if self.version == "v2c" and not self.comunidad:
            raise ValueError(f"snmp {self.nombre}: v2c necesita comunidad")
        return self


class SnmpModule(Base):
    activo: bool = False
    puerto: Port = 9116
    auths: list[SnmpAuth] = []


class Modules(Base):
    blackbox: bool = True
    netinv: Netinv = Netinv()
    pihole_exporter: PiholeExporter = PiholeExporter()
    updates_exporter: UpdatesExporter = UpdatesExporter()
    snmp: SnmpModule = SnmpModule()


# --- alertas ---------------------------------------------------------------------------------------


class Telegram(Base):
    token: EnvVarName
    """Variable con el token del bot (de BotFather): un bot solo para las alertas del sitio."""
    chat_id: Annotated[str, StringConstraints(pattern=r"^-?[0-9]{1,20}$")]
    """Id numérico del chat, literal: Grafana re-tipa los `$VAR` y un número no le vale como chat id. No es
    secreto (sin el token no sirve); mejor un grupo que el chat de una persona."""


class Mail(Base):
    smtp: HostPort
    """Servidor SMTP con puerto (smtp.gmail.com:587)."""
    usuario: EnvVarName
    clave: EnvVarName
    remitente: EnvVarName
    destinatarios: EnvVarName
    """Direcciones separadas por `;`. Son datos personales: van en el fichero de entorno, no en site.yaml."""


class Thresholds(Base):
    caido: Duration = "5m"
    """Tiempo sin responder (ping, servicio, web, DNS) antes de avisar."""
    exporter_caido: Duration = "5m"
    certificado_dias: int = Field(default=15, ge=1, le=90)
    disco_pct: int = Field(default=90, ge=50, le=99)
    disco_durante: Duration = "15m"
    consumible_pct: int = Field(default=15, ge=1, le=90)
    """Consumible de impresora (tóner, tinta, tambor…) por debajo de este % → aviso."""


class Alerts(Base):
    """Alertas de Grafana con la marca del sitio. Solo infraestructura: nunca dispositivos de netinv."""

    activo: bool = False
    telegram: Telegram | None = None
    correo: Mail | None = None
    umbrales: Thresholds = Thresholds()
    repetir: Duration = "12h"
    """Cada cuánto se repite el aviso de algo que sigue fallando."""

    @model_validator(mode="after")
    def _check_channel(self) -> Alerts:
        if self.activo and not (self.telegram or self.correo):
            raise ValueError("alertas activas sin canal: configura `telegram` o `correo`")
        return self

    @property
    def env_vars(self) -> list[str]:
        """Variables que necesita Grafana (secretos y datos personales), en orden estable."""
        out: list[str] = []
        if self.telegram:
            out.append(self.telegram.token)
        if self.correo:
            c = self.correo
            out += [c.usuario, c.clave, c.remitente, c.destinatarios]
        return list(dict.fromkeys(out))

    @property
    def provisioning_vars(self) -> list[str]:
        """Las que Grafana interpola (`$VAR`) en el fichero de alertas; el SMTP va por GF_SMTP_*."""
        out = [self.telegram.token] if self.telegram else []
        return out + ([self.correo.destinatarios] if self.correo else [])

    @property
    def secret_vars(self) -> list[str]:
        out = [self.telegram.token] if self.telegram else []
        return out + ([self.correo.clave] if self.correo else [])


# --- monitor y sitio --------------------------------------------------------------------------------

DEFAULT_IMAGES: dict[str, str] = {
    "grafana": "grafana/grafana-oss",
    "prometheus": "prom/prometheus",
    "blackbox": "prom/blackbox-exporter",
    "node_exporter": "quay.io/prometheus/node-exporter",
    "cadvisor": "ghcr.io/google/cadvisor",
    "pihole_exporter": "ekofr/pihole-exporter",
    "snmp_exporter": "prom/snmp-exporter",
}


class Ports(Base):
    grafana: Port = 3300
    prometheus: Port = 9390


class Monitor(Base):
    host: Id
    """Host que ejecuta Prometheus, Grafana y las sondas."""
    proyecto: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
    """Proyecto de compose (en OMV, nombre del stack)."""
    prefijo_contenedores: Annotated[str, StringConstraints(pattern=r"^([a-z][a-z0-9-]{0,19}-)?$")] = ""
    puertos: Ports = Ports()
    retencion: Duration = "90d"
    intervalo: Duration = "30s"
    timeout: Duration = "10s"
    grafana_url: URL
    grafana_plugins: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,60}$")]] = []
    dns: list[IP] = []
    """Servidores DNS del contenedor de sondas (si el de Docker no resuelve los nombres internos)."""
    imagenes: dict[str, ImageRef] = {}
    watchtower: bool = False
    """Etiqueta los contenedores para que watchtower los actualice."""
    etiqueta_sitio: bool = True
    """Añade `site: <id>` a las external_labels de Prometheus (federación, alertas)."""
    deploy: Deploy | None = None
    """Cómo se despliega el stack del monitor en su host."""
    grafana_token: EnvVarName | None = None
    """Variable con un token de cuenta de servicio de Grafana (Admin) para `vigia grafana-brand`."""

    @field_validator("imagenes")
    @classmethod
    def _check_images(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = set(v) - set(DEFAULT_IMAGES)
        if unknown:
            raise ValueError(f"imágenes desconocidas: {sorted(unknown)}")
        return v

    def image(self, name: str) -> str:
        return self.imagenes.get(name, DEFAULT_IMAGES[name])


class Network(Base):
    subred: Annotated[str, AfterValidator(lambda v: str(ipaddress.ip_network(v)))]
    dominio: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)*$")]


class SiteInfo(Base):
    id: Id
    nombre: Text


class Bridge(Base):
    host: Id
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]
    nombre: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]


class Site(Base):
    vigia: Annotated[str, StringConstraints(pattern=r"^[0-9<>=!~,. ]+$")]
    """Rango de versiones de vigia con el que se probó el sitio; con otra versión, el sitio no carga."""
    sitio: SiteInfo
    branding: Branding
    red: Network
    monitor: Monitor
    hosts: list[Host]
    """El orden de la lista es el orden de los servidores en los paneles."""
    vips: list[Vip] = []
    ping: list[Ping] = []
    servicios: list[Service] = []
    web: WebConfig = WebConfig()
    dns: Dns | None = None
    modulos: Modules = Modules()
    alertas: Alerts = Alerts()
    bridges: list[Bridge] = []
    """Redes Docker por host (salida de `vigia bridges`), para nombrar las interfaces br-<id>."""

    @field_validator("vigia")
    @classmethod
    def _check_version(cls, v: str) -> str:
        try:
            spec = SpecifierSet(v)
        except InvalidSpecifier:
            raise ValueError(f"rango de versiones no válido: {v!r} (p. ej. '>=0.2,<0.3')") from None
        if not spec.contains(Version(__version__), prereleases=True):
            raise ValueError(
                f"este sitio pide vigia {v} y está instalada la {__version__}: actualiza el sitio "
                "(pruébalo y sube el rango) o instala una versión compatible"
            )
        return v

    # -- consultas ------------------------------------------------------------------------------------

    def get_host(self, id_: str) -> Host:
        for h in self.hosts:
            if h.id == id_:
                return h
        raise KeyError(id_)

    @property
    def monitor_host(self) -> Host:
        return self.get_host(self.monitor.host)

    @property
    def piholes(self) -> list[Host]:
        return [h for h in self.hosts if h.pihole]

    @property
    def printers_snmp(self) -> list[Host]:
        return [h for h in self.hosts if h.is_printer_snmp and self.modulos.snmp.activo]

    def quiet_hosts(self) -> set[str]:
        """Hosts con algún ping `alerta: false` (se apagan o duermen): tampoco avisan si su exporter calla."""
        return {p.host for p in self.ping if p.host and not p.alerta}

    def resolved_pings(self) -> list[tuple[str, str, str]]:
        """(ip, nombre, grupo) de cada objetivo de ping, en el orden de `ping` (zip con él es válido)."""
        vips = {v.id: v for v in self.vips}
        out = []
        for p in self.ping:
            if p.host in vips:
                v = vips[p.host]
                out.append((v.ip, p.nombre or v.nombre, p.grupo or v.grupo))
            elif p.host:
                h = self.get_host(p.host)
                out.append((p.ip or h.ip, p.nombre or h.display_name, p.grupo or h.ping_group))
            else:
                out.append((str(p.ip), str(p.nombre), p.grupo or "otros"))
        return out

    def warnings(self) -> list[str]:
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
    def _cross_validate(self) -> Site:
        errors: list[str] = []
        net = ipaddress.ip_network(self.red.subred)

        ids = [h.id for h in self.hosts] + [v.id for v in self.vips]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            errors.append(f"ids repetidos: {sorted(duplicates)}")
        ids_set = set(ids)

        ips = [ip for h in self.hosts for ip in h.ips] + [v.ip for v in self.vips]
        for ip in ips:
            if ipaddress.ip_address(ip) not in net:
                errors.append(f"IP {ip} fuera de la subred {net}")
        dup_ips = {i for i in ips if ips.count(i) > 1}
        if dup_ips:
            errors.append(f"IPs repetidas: {sorted(dup_ips)}")

        if self.monitor.host not in {h.id for h in self.hosts}:
            errors.append(f"monitor.host {self.monitor.host!r} no es un host")
        elif not self.monitor_host.profile.docker:
            errors.append(f"monitor.host {self.monitor.host!r} es de un tipo sin Docker")

        hosts_by_id = {h.id: h for h in self.hosts}
        for p in self.ping:
            if p.host and p.host not in ids_set:
                errors.append(f"ping: host desconocido {p.host!r}")
            elif p.host in hosts_by_id and p.ip and p.ip not in hosts_by_id[p.host].ips:
                errors.append(f"ping: {p.ip} no es una IP de {p.host}")

        for s in self.servicios:
            if s.host not in ids_set:
                errors.append(f"servicio {s.nombre}: host desconocido {s.host!r}")
            h = hosts_by_id.get(s.host)
            if h and h.discos_hibernan and not s.espera_200:
                errors.append(
                    f"servicio {s.nombre}: {h.id} hiberna sus discos; confirma que responde 200 "
                    "y marca `espera_200: true` (un 403/404 escribe en sus logs y los despierta)"
                )

        if self.dns:
            for ip in self.dns.servidores:
                if ip not in ips:
                    errors.append(f"dns: {ip} no es un host ni una VIP del sitio")

        m = self.modulos
        if m.pihole_exporter.activo:
            if not self.piholes:
                errors.append("pihole_exporter activo sin ningún host con `pihole`")
            if not m.pihole_exporter.secreto:
                errors.append("pihole_exporter activo sin `secreto`")
        if m.netinv.activo and self.piholes and not m.pihole_exporter.secreto:
            errors.append("netinv consulta las Pi-hole: falta modulos.pihole_exporter.secreto")
        if m.updates_exporter.activo:
            if m.updates_exporter.host not in hosts_by_id:
                errors.append("updates_exporter activo sin `host` válido")
            if not m.updates_exporter.claves:
                errors.append("updates_exporter activo sin `claves`")
        for h in self.hosts:
            if h.actualizaciones and not m.updates_exporter.activo:
                errors.append(f"host {h.id}: tiene `actualizaciones` pero updates_exporter está inactivo")
            if h.snmp:
                if not m.snmp.activo:
                    errors.append(f"host {h.id}: tiene `snmp` pero el módulo snmp está inactivo")
                elif h.snmp.auth not in {a.nombre for a in m.snmp.auths}:
                    errors.append(f"host {h.id}: auth SNMP desconocida {h.snmp.auth!r}")
            if h.cadvisor and h.cadvisor.gestion == "vigia" and h.id != self.monitor.host and not h.deploy:
                errors.append(f"host {h.id}: cAdvisor gestionado por vigia necesita `deploy`")
            if (
                h.node_exporter
                and h.node_exporter.gestion == "vigia"
                and h.id != self.monitor.host
                and not h.deploy
            ):
                errors.append(f"host {h.id}: node_exporter gestionado por vigia necesita `deploy`")

        primaries = [h for h in self.piholes if h.pihole and h.pihole.primaria]
        if len(primaries) > 1:
            errors.append("solo puede haber una Pi-hole primaria")

        for b in self.bridges:
            if b.host not in hosts_by_id:
                errors.append(f"bridges: host desconocido {b.host!r}")

        if errors:
            raise ValueError("; ".join(errors))
        return self


def load_site(path: Path) -> Site:
    """Lee y valida un site.yaml (solo `yaml.safe_load`)."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: se esperaba un mapa YAML")
    bridges = path.parent / "bridges.yaml"
    if "bridges" not in data and bridges.exists():
        with bridges.open(encoding="utf-8") as f:
            data["bridges"] = yaml.safe_load(f) or []
    return Site.model_validate(data)
