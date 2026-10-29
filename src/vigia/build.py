"""Genera todo lo desplegable de un sitio en `build/`, de forma determinista."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from vigia import __version__
from vigia.alerting import alerting, smtp_env
from vigia.model import Host, Site
from vigia.render import Raw, dump_yaml, render_template


@dataclass(frozen=True)
class Present:
    node: bool
    windows: bool
    cadvisor: bool
    snmp: bool


def _header(s: Site, what: str) -> Raw:
    return Raw(
        f"# {what} — generado por vigia {__version__} para «{s.sitio.nombre}».\n"
        "# No editar: cambia site.yaml y ejecuta `vigia build`."
    )


def present(s: Site) -> Present:
    return Present(
        node=any(h.node_exporter for h in s.hosts),
        windows=any(h.windows_exporter for h in s.hosts),
        cadvisor=any(h.cadvisor for h in s.hosts),
        snmp=s.modulos.snmp.activo and any(h.snmp for h in s.hosts),
    )


def _service_module(s: Site, srv: Any) -> str | None:
    if srv.modulo and srv.modulo != "http_any":
        return str(srv.modulo)
    if srv.espera_200:
        return "http_200"
    return None


# --- objetivos (file_sd) ----------------------------------------------------------------------------


def targets(s: Site) -> dict[str, Any]:
    """Ficheros de prometheus/targets/: nombre -> lista de grupos de objetivos."""
    out: dict[str, Any] = {}
    nodes = [h for h in s.hosts if h.node_exporter]
    if nodes:
        out["nodos.yml"] = [
            {"targets": [f"{h.ip}:{h.node_exporter.puerto}"], "labels": {"nombre": h.display_name}}
            for h in nodes
            if h.node_exporter
        ]
    win = [h for h in s.hosts if h.windows_exporter]
    if win:
        out["windows.yml"] = [
            {"targets": [f"{h.ip}:{h.windows_exporter.puerto}"], "labels": {"nombre": h.display_name}}
            for h in win
            if h.windows_exporter
        ]
    cad = [h for h in s.hosts if h.cadvisor]
    if cad:
        out["cadvisor.yml"] = [
            {"targets": [f"{h.ip}:{h.cadvisor.puerto}"], "labels": {"nombre": h.display_name}}
            for h in cad
            if h.cadvisor
        ]
    if present(s).snmp:
        groups = []
        for h in s.hosts:
            if not h.snmp:
                continue
            module = h.snmp.modulo or h.profile.snmp_module or "if_mib"
            snmp_labels = _no_alert(
                {
                    "nombre": h.display_name,
                    "tipo": h.tipo.value,
                    "__param_module": module,
                    "__param_auth": h.snmp.auth,
                },
                h.id not in s.quiet_hosts(),
            )
            groups.append({"targets": [h.ip], "labels": snmp_labels})
        out["snmp.yml"] = groups
    if s.modulos.blackbox:
        if s.ping:
            out["hosts.yml"] = [
                {"targets": [ip], "labels": _no_alert({"nombre": name, "grupo": group}, p.alerta)}
                for p, (ip, name, group) in zip(s.ping, s.resolved_pings(), strict=True)
            ]
        if s.servicios:
            groups = []
            for srv in s.servicios:
                labels: dict[str, str] = _no_alert({"nombre": srv.nombre, "host": srv.host}, srv.alerta)
                mod = _service_module(s, srv)
                if mod:
                    labels["__param_module"] = mod
                groups.append({"targets": [srv.url], "labels": labels})
            out["servicios.yml"] = groups
        if s.externos.objetivos:
            out["externos.yml"] = externals_targets(s)
        if s.web.objetivos:
            out["web.yml"] = [
                {"targets": [w.url], "labels": _no_alert({"nombre": w.nombre}, w.alerta)}
                for w in s.web.objetivos
            ]
    return out


def externals_targets(s: Site) -> list[dict[str, Any]]:
    """Un grupo por sonda: web (http/https), ping y cada puerto TCP de los objetivos externos."""
    groups: list[dict[str, Any]] = []
    for o in s.externos.objetivos:
        base = {"nombre": o.nombre}
        if o.url:
            mod = "https_externo" if o.url.startswith("https://") else "http_externo"
            labels = {**base, "tipo": "web", "__param_module": mod}
            groups.append({"targets": [o.url], "labels": _no_alert(labels, o.alerta)})
            continue
        assert o.host
        groups.append(
            {
                "targets": [o.host],
                "labels": _no_alert({**base, "tipo": "ping", "__param_module": "icmp"}, o.alerta),
            }
        )
        for p in o.puertos:
            labels = {**base, "tipo": "tcp", "puerto": str(p), "__param_module": "tcp_externo"}
            target = f"[{o.host}]:{p}" if ":" in o.host else f"{o.host}:{p}"
            groups.append({"targets": [target], "labels": _no_alert(labels, o.alerta)})
    return groups


def _no_alert(labels: dict[str, str], alert: bool) -> dict[str, str]:
    """Etiqueta `alerta: "no"` en lo que se apaga a propósito (las reglas la excluyen)."""
    return labels if alert else {**labels, "alerta": "no"}


def _probes(s: Site) -> list[tuple[str, str, str, str]]:
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


def _pihole_params(s: Site) -> dict[str, str]:
    parts = [urlsplit(h.pihole.url) for h in s.piholes if h.pihole]
    return {
        "hosts": ",".join(p.hostname or "" for p in parts),
        "ports": ",".join(str(p.port or (443 if p.scheme == "https" else 80)) for p in parts),
        "protocols": ",".join(p.scheme for p in parts),
        "urls": ",".join(f"{p.scheme}://{p.netloc}" for p in parts),
    }


def _snmp_vars(s: Site) -> list[str]:
    vs: list[str] = []
    for a in s.modulos.snmp.auths:
        for v in (a.usuario, a.clave_auth, a.clave_priv, a.comunidad):
            if v and v not in vs:
                vs.append(v)
    return vs


def _snmp_auths(s: Site) -> str:
    auths: dict[str, Any] = {}
    for a in s.modulos.snmp.auths:
        if a.version == "v3":
            auths[a.nombre] = {
                "version": 3,
                "security_level": "authPriv",
                "username": f"${{{a.usuario}}}",
                "auth_protocol": a.protocolo_auth or "SHA256",
                "password": f"${{{a.clave_auth}}}",
                "priv_protocol": a.protocolo_priv or "AES",
                "priv_password": f"${{{a.clave_priv}}}",
            }
            if a.contexto:
                auths[a.nombre]["context_name"] = a.contexto
        else:
            auths[a.nombre] = {"version": 2, "community": f"${{{a.comunidad}}}"}
    return dump_yaml({"auths": auths}, _header(s, "Autenticaciones SNMP (solo referencias ${VAR})"))


def hosts_spec(s: Site) -> str:
    parts = []
    for h in s.hosts:
        a = h.actualizaciones
        if not a:
            continue
        spec = f"{h.id}:{h.ip}:{h.ssh_puerto}:{a.usuario}"
        if a.intervalo_min:
            spec += f":{a.intervalo_min}"
        parts.append(spec)
    return " ".join(parts)


def _dns_regex(ip: str) -> str:
    return ".*\\t" + re.escape(ip) + "$"


# --- build ------------------------------------------------------------------------------------------


def build_site(s: Site, site_root: Path) -> dict[str, str | bytes]:
    """Devuelve {ruta relativa: contenido} de todo lo generado (sin escribir nada)."""
    out: dict[str, str | bytes] = {}
    prefix = s.monitor.prefijo_contenedores
    h = present(s)
    mon = s.monitor_host

    out["prometheus/prometheus.yml"] = render_template(
        "prometheus/prometheus.yml.j2", s=s, present=h, probes=_probes(s), header=_header(s, "Prometheus")
    )
    for name, groups in targets(s).items():
        out[f"prometheus/targets/{name}"] = dump_yaml(groups, _header(s, "Objetivos de Prometheus"))

    if s.modulos.blackbox:
        out["blackbox/blackbox.yml"] = render_template(
            "blackbox/blackbox.yml.j2",
            s=s,
            ca=s.web.ca is not None,
            minecraft=any(x.modulo == "minecraft" for x in s.servicios),
            dns_regex=_dns_regex(s.dns.espera) if s.dns else "",
            header=_header(s, "blackbox_exporter"),
        )
        if s.web.ca:
            out["blackbox/ca.crt"] = (site_root / s.web.ca).read_bytes()

    out["grafana-provisioning/datasources/prometheus.yml"] = render_template(
        "grafana/datasources.yml.j2", s=s
    )
    out["grafana-provisioning/dashboards/vigia.yml"] = render_template("grafana/dashboards.yml.j2", s=s)
    if s.alertas.activo:
        out["grafana-provisioning/alerting/vigia.yml"] = alerting(s, _header(s, "Alertas de Grafana"))
    if s.branding.grafana and s.branding.logo:
        out["branding/logo.svg"] = (site_root / s.branding.logo).read_bytes()
    if s.branding.grafana and s.branding.favicon:
        out["branding/favicon.png"] = (site_root / s.branding.favicon).read_bytes()

    if s.modulos.snmp.activo:
        out["snmp/auths.yml"] = _snmp_auths(s)
        if s.printers_snmp:
            out["snmp/vigia-modulos.yml"] = (
                files("vigia").joinpath("templates", "snmp", "vigia-modulos.yml").read_bytes()
            )

    if s.modulos.netinv.activo:
        out.update(_bundled_image("netinv", "netinv"))
        if s.modulos.netinv.dispositivos:
            out["netinv/devices.yaml"] = (site_root / s.modulos.netinv.dispositivos).read_bytes()

    if s.modulos.bot.activo:
        out.update(_bot(s))

    out[f"{s.monitor.proyecto}.yml"] = render_template(
        "compose/monitor.yml.j2",
        s=s,
        prefix=prefix,
        node=mon,
        pihole=_pihole_params(s),
        snmp_vars=_snmp_vars(s),
        snmp_modules=bool(s.printers_snmp),
        smtp_env=smtp_env(s),
        alert_vars=s.alertas.provisioning_vars if s.alertas.activo else [],
        header=_header(s, f"Stack {s.monitor.proyecto} (host {mon.id})"),
    )

    for hst in s.hosts:
        if hst.id != mon.id and _has_agents(hst):
            out[f"agentes/{hst.id}.yml"] = render_template(
                "compose/agents.yml.j2",
                s=s,
                prefix=prefix,
                node=hst,
                header=_header(s, f"Agentes del host {hst.id}"),
            )

    u = s.modulos.updates_exporter
    if u.activo:
        out["updates-exporter/docker-compose.yml"] = render_template(
            "compose/updates_exporter.yml.j2",
            u=u,
            prefix=prefix,
            hosts_spec=hosts_spec(s),
            header=_header(s, f"updates-exporter (host {u.host})"),
        )
        out.update(
            {
                k.replace("updates_exporter/", "updates-exporter/"): v
                for k, v in _bundled_image("updates_exporter", "updates_exporter").items()
            }
        )

    from vigia.dashboards import dashboards_for  # noqa: PLC0415 - evita el ciclo con dashboards

    for name, content in dashboards_for(s, site_root).items():
        out[f"dashboards/{name}"] = content
    return out


def _has_agents(h: Host) -> bool:
    return bool(
        (h.node_exporter and h.node_exporter.gestion == "vigia")
        or (h.cadvisor and h.cadvisor.gestion == "vigia")
    )


def _bundled_image(name: str, dest: str) -> dict[str, str | bytes]:
    out: dict[str, str | bytes] = {}
    base = files("vigia").joinpath("images", name)
    with as_file(base) as path:
        for f in sorted(Path(path).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                out[f"{dest}/{f.relative_to(path).as_posix()}"] = f.read_bytes()
    return out


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


def write_build(content: dict[str, str | bytes], dest: Path) -> None:
    """Sustituye `destino` por lo generado (solo ficheros de vigia: se limpia entero)."""
    marker = dest / ".vigia-build"
    if dest.exists():
        if not marker.exists():
            raise RuntimeError(f"{dest} existe y no lo generó vigia: no se toca")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    marker.write_text("generado por vigia; se regenera entero en cada build\n", encoding="utf-8")
    for rel, data in sorted(content.items()):
        f = dest / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            f.write_bytes(data)
        else:
            f.write_text(data, encoding="utf-8")
