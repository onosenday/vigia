"""Genera todo lo desplegable de un sitio en `build/`, de forma determinista."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from vigia import __version__
from vigia.model import Host, Site
from vigia.render import Crudo, plantilla, volcar_yaml


@dataclass(frozen=True)
class Hay:
    node: bool
    windows: bool
    cadvisor: bool
    snmp: bool


def _cabecera(s: Site, que: str) -> Crudo:
    return Crudo(
        f"# {que} — generado por vigia {__version__} para «{s.sitio.nombre}».\n"
        "# No editar: cambia site.yaml y ejecuta `vigia build`."
    )


def hay(s: Site) -> Hay:
    return Hay(
        node=any(h.node_exporter for h in s.hosts),
        windows=any(h.windows_exporter for h in s.hosts),
        cadvisor=any(h.cadvisor for h in s.hosts),
        snmp=s.modulos.snmp.activo and any(h.snmp for h in s.hosts),
    )


def _modulo_servicio(s: Site, srv: Any) -> str | None:
    if srv.modulo and srv.modulo != "http_any":
        return str(srv.modulo)
    if srv.espera_200:
        return "http_200"
    return None


# --- objetivos (file_sd) ----------------------------------------------------------------------------


def objetivos(s: Site) -> dict[str, Any]:
    """Ficheros de prometheus/targets/: nombre -> lista de grupos de objetivos."""
    out: dict[str, Any] = {}
    nodos = [h for h in s.hosts if h.node_exporter]
    if nodos:
        out["nodos.yml"] = [
            {"targets": [f"{h.ip}:{h.node_exporter.puerto}"], "labels": {"nombre": h.visible}}
            for h in nodos
            if h.node_exporter
        ]
    win = [h for h in s.hosts if h.windows_exporter]
    if win:
        out["windows.yml"] = [
            {"targets": [f"{h.ip}:{h.windows_exporter.puerto}"], "labels": {"nombre": h.visible}}
            for h in win
            if h.windows_exporter
        ]
    cad = [h for h in s.hosts if h.cadvisor]
    if cad:
        out["cadvisor.yml"] = [
            {"targets": [f"{h.ip}:{h.cadvisor.puerto}"], "labels": {"nombre": h.visible}}
            for h in cad
            if h.cadvisor
        ]
    if hay(s).snmp:
        grupos = []
        for h in s.hosts:
            if not h.snmp:
                continue
            modulo = h.snmp.modulo or h.perfil.snmp_modulo or "if_mib"
            etiquetas = {
                "nombre": h.visible,
                "tipo": h.tipo.value,
                "__param_module": modulo,
                "__param_auth": h.snmp.auth,
            }
            grupos.append({"targets": [h.ip], "labels": etiquetas})
        out["snmp.yml"] = grupos
    if s.modulos.blackbox:
        if s.ping:
            out["hosts.yml"] = [
                {"targets": [ip], "labels": {"nombre": nombre, "grupo": grupo}}
                for ip, nombre, grupo in s.ping_resuelto()
            ]
        if s.servicios:
            grupos = []
            for srv in s.servicios:
                labels: dict[str, str] = {"nombre": srv.nombre, "host": srv.host}
                mod = _modulo_servicio(s, srv)
                if mod:
                    labels["__param_module"] = mod
                grupos.append({"targets": [srv.url], "labels": labels})
            out["servicios.yml"] = grupos
        if s.web.objetivos:
            out["web.yml"] = [{"targets": [w.url], "labels": {"nombre": w.nombre}} for w in s.web.objetivos]
    return out


def _sondas(s: Site) -> list[tuple[str, str, str, str]]:
    """(job, módulo, fichero, comentario) de los jobs de blackbox además de `web` y `dns`."""
    out = []
    if s.servicios:
        out.append(
            (
                "servicio",
                "http_any",
                "servicios.yml",
                "Servicios por IP:puerto (paneles de administración, APIs)",
            )
        )
    if s.ping:
        out.append(("ping", "icmp", "hosts.yml", "Equipos de la red (ping)"))
    return out


# --- contexto de compose ----------------------------------------------------------------------------


def _pihole(s: Site) -> dict[str, str]:
    partes = [urlsplit(h.pihole.url) for h in s.piholes if h.pihole]
    return {
        "hosts": ",".join(p.hostname or "" for p in partes),
        "puertos": ",".join(str(p.port or (443 if p.scheme == "https" else 80)) for p in partes),
        "protocolos": ",".join(p.scheme for p in partes),
        "urls": ",".join(f"{p.scheme}://{p.netloc}" for p in partes),
    }


def _snmp_vars(s: Site) -> list[str]:
    vs: list[str] = []
    for a in s.modulos.snmp.auths:
        for v in (a.usuario, a.clave_auth, a.clave_priv, a.comunidad):
            if v and v not in vs:
                vs.append(v)
    return vs


def _auths_snmp(s: Site) -> str:
    auths: dict[str, Any] = {}
    for a in s.modulos.snmp.auths:
        if a.version == "v3":
            auths[a.nombre] = {
                "version": 3,
                "security_level": "authPriv",
                "username": f"${{{a.usuario}}}",
                "auth_protocol": "SHA256",
                "password": f"${{{a.clave_auth}}}",
                "priv_protocol": "AES",
                "priv_password": f"${{{a.clave_priv}}}",
            }
        else:
            auths[a.nombre] = {"version": 2, "community": f"${{{a.comunidad}}}"}
    return volcar_yaml({"auths": auths}, _cabecera(s, "Autenticaciones SNMP (solo referencias ${VAR})"))


def hosts_spec(s: Site) -> str:
    partes = []
    for h in s.hosts:
        a = h.actualizaciones
        if not a:
            continue
        spec = f"{h.id}:{h.ip}:{h.ssh_puerto}:{a.usuario}"
        if a.intervalo_min:
            spec += f":{a.intervalo_min}"
        partes.append(spec)
    return " ".join(partes)


def _regex_dns(ip: str) -> str:
    return ".*\\t" + re.escape(ip) + "$"


# --- build ------------------------------------------------------------------------------------------


def construir(s: Site, raiz_sitio: Path) -> dict[str, str | bytes]:
    """Devuelve {ruta relativa: contenido} de todo lo generado (sin escribir nada)."""
    out: dict[str, str | bytes] = {}
    pre = s.monitor.prefijo_contenedores
    h = hay(s)
    mon = s.monitor_host

    out["prometheus/prometheus.yml"] = plantilla(
        "prometheus/prometheus.yml.j2", s=s, hay=h, sondas=_sondas(s), cabecera=_cabecera(s, "Prometheus")
    )
    for nombre, grupos in objetivos(s).items():
        out[f"prometheus/targets/{nombre}"] = volcar_yaml(grupos, _cabecera(s, "Objetivos de Prometheus"))

    if s.modulos.blackbox:
        out["blackbox/blackbox.yml"] = plantilla(
            "blackbox/blackbox.yml.j2",
            s=s,
            ca=s.web.ca is not None,
            minecraft=any(x.modulo == "minecraft" for x in s.servicios),
            regex_dns=_regex_dns(s.dns.espera) if s.dns else "",
            cabecera=_cabecera(s, "blackbox_exporter"),
        )
        if s.web.ca:
            out["blackbox/ca.crt"] = (raiz_sitio / s.web.ca).read_bytes()

    out["grafana-provisioning/datasources/prometheus.yml"] = plantilla("grafana/datasources.yml.j2", s=s)
    out["grafana-provisioning/dashboards/vigia.yml"] = plantilla("grafana/dashboards.yml.j2", s=s)
    if s.branding.grafana and s.branding.logo:
        out["branding/logo.svg"] = (raiz_sitio / s.branding.logo).read_bytes()
    if s.branding.grafana and s.branding.favicon:
        out["branding/favicon.png"] = (raiz_sitio / s.branding.favicon).read_bytes()

    if s.modulos.snmp.activo:
        out["snmp/auths.yml"] = _auths_snmp(s)

    if s.modulos.netinv.activo:
        out.update(_imagen("netinv", "netinv"))
        if s.modulos.netinv.dispositivos:
            out["netinv/devices.yaml"] = (raiz_sitio / s.modulos.netinv.dispositivos).read_bytes()

    out[f"{s.monitor.proyecto}.yml"] = plantilla(
        "compose/monitor.yml.j2",
        s=s,
        pre=pre,
        nodo=mon,
        pihole=_pihole(s),
        snmp_vars=_snmp_vars(s),
        cabecera=_cabecera(s, f"Stack {s.monitor.proyecto} (host {mon.id})"),
    )

    for hst in s.hosts:
        if hst.id != mon.id and _agentes(hst):
            out[f"agentes/{hst.id}.yml"] = plantilla(
                "compose/agentes.yml.j2",
                s=s,
                pre=pre,
                nodo=hst,
                cabecera=_cabecera(s, f"Agentes del host {hst.id}"),
            )

    u = s.modulos.updates_exporter
    if u.activo:
        out["updates-exporter/docker-compose.yml"] = plantilla(
            "compose/updates_exporter.yml.j2",
            u=u,
            pre=pre,
            hosts_spec=hosts_spec(s),
            cabecera=_cabecera(s, f"updates-exporter (host {u.host})"),
        )
        out.update(
            {
                k.replace("updates_exporter/", "updates-exporter/"): v
                for k, v in _imagen("updates_exporter", "updates_exporter").items()
            }
        )

    from vigia.dashboards import paneles  # noqa: PLC0415 - evita el ciclo con dashboards

    for nombre, contenido in paneles(s, raiz_sitio).items():
        out[f"dashboards/{nombre}"] = contenido
    return out


def _agentes(h: Host) -> bool:
    return bool(
        (h.node_exporter and h.node_exporter.gestion == "vigia")
        or (h.cadvisor and h.cadvisor.gestion == "vigia")
    )


def _imagen(nombre: str, destino: str) -> dict[str, str | bytes]:
    out: dict[str, str | bytes] = {}
    base = files("vigia").joinpath("images", nombre)
    with as_file(base) as ruta:
        for f in sorted(Path(ruta).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                out[f"{destino}/{f.relative_to(ruta).as_posix()}"] = f.read_bytes()
    return out


def escribir(contenido: dict[str, str | bytes], destino: Path) -> None:
    """Sustituye `destino` por lo generado (solo ficheros de vigia: se limpia entero)."""
    marca = destino / ".vigia-build"
    if destino.exists():
        if not marca.exists():
            raise RuntimeError(f"{destino} existe y no lo generó vigia: no se toca")
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    marca.write_text("generado por vigia; se regenera entero en cada build\n", encoding="utf-8")
    for rel, datos in sorted(contenido.items()):
        f = destino / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(datos, bytes):
            f.write_bytes(datos)
        else:
            f.write_text(datos, encoding="utf-8")
