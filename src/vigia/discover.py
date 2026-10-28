"""`vigia descubrir`: propuesta de hosts para site.yaml a partir de lo que hay en la red.

Solo con `modulos.netinv.autorizacion` en site.yaml y `--yes`. Pasos:
1. Candidatos: los equipos que ya conoce netinv (sin MAC aleatorias) o, sin netinv, un barrido de la subred
   del sitio desde este equipo (ping y conexión TCP a unos pocos puertos).
2. Sondeo de los puertos típicos de infraestructura en cada candidato (conexión TCP, sin enviar datos salvo
   un GET a /metrics en el 9100 para distinguir node_exporter de una impresora).
3. Clasificación por puertos, fabricante, pistas de netinv y título y cabecera `Server` de su web (un GET a /,
   sin seguir redirecciones). Solo se proponen equipos con pinta de infraestructura; los clientes (móviles,
   puestos, televisores) no se proponen: se listan comentados, con IP y puertos (sin nombres).
4. Comprobación de los hosts del sitio (ping y TCP): los que no responden se avisan en la propuesta.

Las IPs de este mismo equipo (p. ej. la de un túnel VPN) nunca se proponen.

Nunca toca site.yaml: escribe una propuesta (fuera de git: puede llevar nombres de equipos en comentarios)
con ids genéricos por tipo.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from vigia.model import DeviceType, Site

INFRA_PORTS = (
    22,
    53,
    80,
    88,
    135,
    389,
    443,
    445,
    631,
    636,
    3389,
    3493,
    5000,
    5001,
    5985,
    5986,
    8006,
    8080,
    8443,
    9100,
    9182,
)
"""Puertos que se sondean: SSH, DNS, web, Kerberos, RPC, LDAP(S), SMB, IPP, RDP, NUT (SAI), DSM, WinRM,
Proxmox y node/windows_exporter."""
SWEEP_PORTS = (22, 80, 135, 443, 445, 3389, 5985, 9100)
"""Barrido sin netinv: un equipo cuenta como vivo si responde al ping o a uno de estos (Windows suele filtrar
ICMP y no abrir web)."""
WEB_PORTS = {80: False, 8080: False, 5000: False, 443: True, 8443: True, 5001: True}
"""Puertos web cuyo título y cabecera Server se leen (puerto: HTTPS)."""
WINRM = {5985, 5986}
DC_PORTS = {88, 389, 636}
"""Kerberos y LDAP: con RPC o SMB, un controlador de dominio (un puesto no los abre)."""
MAX_ADDRESSES = 1024

PRINTER_VENDORS = r"\b(hp|hewlett|brother|epson|canon|kyocera|ricoh|xerox|lexmark|konica|oki|sharp)\b"
UPS_VENDORS = r"\b(apc|american power|schneider|eaton|riello|salicru|cyberpower|socomec|legrand)\b"
NET_VENDORS = (
    r"\b(ubiquiti|tp-link|tplink|cisco|mikrotik|routerboard|netgear|aruba|zyxel|d-link|juniper|fortinet)\b"
)
ROUTER_VENDORS = r"\b(sagemcom|arcadyan|askey|technicolor|mitrastar|avm|fritz|zte|huawei|draytek)\b"
# Pistas de la web del equipo (título y cabecera Server) si no se ve el fabricante (p. ej. por VPN)
WEB_AP = r"\b(access point|gwn[0-9]*|eap[0-9]+|uap|unifi ap|omada ap)\b"
WEB_SWITCH = r"\b(web switch|smart switch|managed switch|jetstream|procurve|easy smart)\b"
WEB_ROUTER = r"\b(vigor[0-9]*|draytek|livebox|fritz!?box|routeros|pfsense|opnsense)\b"
WEB_PRINTER = r"\b(laserjet|officejet|deskjet|imagerunner|workcentre|versalink|ecosys|bizhub|jetdirect)\b"


@dataclass
class Seen:
    ip: str
    ports: set[int] = field(default_factory=set)
    vendor: str = ""
    names: list[str] = field(default_factory=list)
    hints: str = ""
    """SO y título web que vio netinv, y título y cabecera Server leídos al sondear."""
    web: str = ""
    """Título web leído al sondear (para el comentario de la propuesta)."""
    node_metrics: bool = False
    last_seen: float = 0
    live: bool = True
    """Respondió al sondeo; si no, sus puertos son los que vio netinv (apagado o dormido)."""


@dataclass(frozen=True)
class Proposal:
    seen: Seen
    tipo: DeviceType
    notes: tuple[str, ...] = ()


@dataclass
class Result:
    proposals: list[Proposal]
    clients: int
    known: int
    source: str
    client_seen: list[Seen] = field(default_factory=list)
    silent: list[tuple[str, str]] = field(default_factory=list)
    """Hosts del sitio que no responden: (id, ip)."""


# --- clasificación -----------------------------------------------------------------------------------


def classify(d: Seen) -> tuple[DeviceType, tuple[str, ...]] | None:
    """Tipo de equipo de infraestructura o None si parece un cliente (o no se sabe qué es)."""
    text = " ".join([d.vendor, d.hints, *d.names]).lower()
    p = d.ports

    def has(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    if 8006 in p:
        return DeviceType.proxmox, ()
    if has(r"synology|diskstation"):
        return DeviceType.synology, ()
    if has(r"qnap"):
        return DeviceType.qnap, ()
    if has(r"truenas|freenas"):
        return DeviceType.truenas, ()
    if has(r"openmediavault"):
        return DeviceType.omv, ()
    if 9182 in p:
        return DeviceType.windows, ()
    if p & WINRM:
        return DeviceType.windows, ("WinRM abierto: servidor Windows sin windows_exporter",)
    if p & DC_PORTS and p & {135, 445}:
        return DeviceType.windows, ("Kerberos/LDAP: parece un controlador de dominio",)
    if 3493 in p or has(UPS_VENDORS):
        return DeviceType.sai, ()
    if 631 in p or (9100 in p and not d.node_metrics) or (has(PRINTER_VENDORS) and p & {80, 443, 515}):
        return DeviceType.impresora, ()
    if d.node_metrics:
        tipo = DeviceType.raspbian if has(r"raspberry") else DeviceType.linux
        return tipo, ("node_exporter ya responde en :9100",)
    if has(ROUTER_VENDORS) and p & {22, 80, 443}:
        return DeviceType.router, ()
    if has(NET_VENDORS) and p & {22, 80, 443}:
        if has(r"\b(uap|eap|access point|unifi ap)\b"):
            return DeviceType.ap, ()
        return DeviceType.switch, ("revisar: router, switch o punto de acceso",)
    if has(WEB_PRINTER):
        return DeviceType.impresora, ("por su web",)
    if has(WEB_AP):
        return DeviceType.ap, ("por su web",)
    if has(WEB_SWITCH):
        return DeviceType.switch, ("por su web",)
    if has(WEB_ROUTER):
        return DeviceType.router, ("por su web",)
    if 22 in p and not (p & {3389, 445}):
        return DeviceType.linux, ("SSH sin node_exporter: revisar qué es",)
    return None


# --- recogida ----------------------------------------------------------------------------------------


def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ping(ip: str) -> bool:
    r = subprocess.run(  # noqa: S603 - argumentos fijos, IP validada
        ["ping", "-c", "1", "-W", "1", "-q", ip],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def _node_metrics(ip: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(f"http://{ip}:9100/metrics", timeout=timeout) as r:  # noqa: S310
            return b"node_" in r.read(65536)
    except (OSError, ValueError):
        return False


def _web_hint(ip: str, port: int, tls: bool, timeout: float) -> tuple[str, str]:
    """(título, cabecera Server) de GET / sin seguir redirecciones; ("", "") si no responde."""
    try:
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # equipos con certificado propio: solo se lee el título
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                ip, port, timeout=timeout, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        try:
            conn.request("GET", "/", headers={"User-Agent": "vigia-descubrir"})
            r = conn.getresponse()
            server = r.getheader("Server") or ""
            body = r.read(32768).decode("utf-8", "replace")
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ValueError):
        return "", ""
    m = re.search(r"<title[^>]*>([^<]{1,200})", body, re.IGNORECASE)
    return (m.group(1).strip() if m else ""), server.strip()


def local_ips() -> set[str]:
    """IPs de este equipo (no se proponen: p. ej. la de un túnel VPN dentro de la subred del sitio)."""
    try:
        r = subprocess.run(["ip", "-o", "addr", "show"], capture_output=True, text=True, check=False)  # noqa: S607
    except OSError:
        return set()
    return set(re.findall(r"\binet6? ([0-9a-fA-F.:]+)/", r.stdout))


def alive(ip: str, timeout: float) -> bool:
    return _ping(ip) or any(_tcp_open(ip, p, timeout) for p in SWEEP_PORTS)


def alive_ips(ips: list[str], timeout: float, workers: int = 64) -> set[str]:
    if not ips:
        return set()
    with ThreadPoolExecutor(workers) as ex:
        return {ip for ip, ok in zip(ips, ex.map(lambda i: alive(i, timeout), ips), strict=True) if ok}


def from_netinv(url: str, timeout: float = 10) -> list[Seen]:
    """Equipos de netinv con IP y MAC no aleatoria (las aleatorias son móviles)."""
    if urlsplit(url).scheme != "http":
        raise ValueError("netinv se consulta por http")
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - URL construida desde el sitio
        data = json.loads(r.read(20 * 1024 * 1024))
    out = []
    for d in data.values():
        if not isinstance(d, dict) or not d.get("ip") or d.get("aleatoria"):
            continue
        try:
            ip = str(ipaddress.ip_address(d["ip"]))
        except ValueError:
            continue
        seen_ports = [str(x) for x in d.get("puertos") or []]
        hints = " ".join(str(x) for x in [d.get("so") or "", *(d.get("modelo") or []), *seen_ports])
        out.append(
            Seen(
                ip=ip,
                ports={int(m.group(1)) for x in seen_ports if (m := re.match(r"([0-9]{1,5})/tcp\b", x))},
                vendor=str(d.get("fabricante") or ""),
                names=[str(n) for n in d.get("nombres") or []],
                hints=hints,
                last_seen=float(d.get("visto_ultima") or 0),
            )
        )
    return _latest_by_ip(out)


def _latest_by_ip(devices: list[Seen]) -> list[Seen]:
    """Una IP puede quedar en dos MAC (una caducada): se queda la vista más reciente."""
    best: dict[str, Seen] = {}
    for d in devices:
        if d.ip not in best or d.last_seen > best[d.ip].last_seen:
            best[d.ip] = d
    return list(best.values())


def sweep(subnet: str, timeout: float, workers: int = 128) -> list[Seen]:
    net = ipaddress.ip_network(subnet)
    if net.num_addresses > MAX_ADDRESSES:
        raise ValueError(f"subred demasiado grande para barrer ({net.num_addresses} direcciones)")

    ips = [str(h) for h in net.hosts()]
    found = alive_ips(ips, timeout, workers)
    return [Seen(ip=ip) for ip in ips if ip in found]


def probe(devices: list[Seen], timeout: float, workers: int = 128) -> None:
    """Puertos de infraestructura abiertos y node_exporter en :9100 (modifica `devices`)."""
    jobs = [(d, p) for d in devices for p in INFRA_PORTS]
    found: dict[str, set[int]] = {d.ip: set() for d in devices}
    with ThreadPoolExecutor(workers) as ex:
        for (d, p), ok in zip(jobs, ex.map(lambda j: _tcp_open(j[0].ip, j[1], timeout), jobs), strict=True):
            if ok:
                found[d.ip].add(p)
    for d in devices:
        d.live = bool(found[d.ip])
        d.ports |= found[d.ip]
        if 9100 in found[d.ip]:
            d.node_metrics = _node_metrics(d.ip, timeout * 4)
    web_jobs = [(d, port, tls) for d in devices for port, tls in WEB_PORTS.items() if port in found[d.ip]]
    with ThreadPoolExecutor(workers) as ex:
        hints = ex.map(lambda j: _web_hint(j[0].ip, j[1], j[2], timeout * 4), web_jobs)
        for (d, _, _), (title, server) in zip(web_jobs, hints, strict=True):
            if title or server:
                d.hints = f"{d.hints} web={title} server={server}".strip()
                d.web = d.web or title


def site_ips(s: Site) -> set[str]:
    """IPs que el sitio ya conoce (hosts, VIPs, pings y servicios por IP)."""
    out = {ip for h in s.hosts for ip in h.ips} | {v.ip for v in s.vips}
    out |= {ip for ip, _, _ in s.resolved_pings()}
    for srv in s.servicios:
        host = urlsplit(srv.url).hostname if "://" in srv.url else srv.url.rsplit(":", 1)[0]
        if host:
            out.add(host)
    return out


def discover(
    s: Site,
    source: str,
    timeout: float = 0.6,
    fetch: Callable[[str], list[Seen]] = from_netinv,
    scan: Callable[[str, float], list[Seen]] = sweep,
    prober: Callable[[list[Seen], float], None] = probe,
    subnet: str | None = None,
) -> Result:
    """`source`: netinv, local o auto (netinv si el sitio lo tiene activo). `subnet`: solo esa del sitio."""
    n = s.modulos.netinv
    if source == "auto":
        source = "netinv" if n.activo else "local"
    if source == "netinv":
        if not n.activo:
            raise ValueError("el sitio no tiene netinv activo: usa --fuente local")
        devices = fetch(f"http://{s.monitor_host.ip}:{n.puerto}/devices.json")
    else:
        devices = [d for c in subnets_to_scan(s, subnet) for d in scan(c, timeout)]
    wanted = set(subnets_to_scan(s, subnet))
    devices = [d for d in devices if s.red.network_of(d.ip) in wanted]
    known = site_ips(s)
    own = local_ips()
    new = [d for d in devices if d.ip not in known and d.ip not in own]
    prober(new, timeout)
    proposals, clients = [], []
    for d in sorted(new, key=lambda x: ipaddress.ip_address(x.ip)):
        c = classify(d)
        if c is None:
            clients.append(d)
        else:
            proposals.append(Proposal(d, c[0], c[1]))
    host_ips = [(h.id, ip) for h in s.hosts for ip in h.ips if s.red.network_of(ip) in wanted]
    answered = {d.ip for d in devices} if source == "local" else set()
    answered |= alive_ips(sorted({ip for _, ip in host_ips} - answered), timeout)
    silent = [(h, ip) for h, ip in host_ips if ip not in answered]
    known_seen = sum(1 for d in devices if d.ip in known)
    return Result(proposals, len(clients), known_seen, source, clients, silent)


# --- propuesta ---------------------------------------------------------------------------------------


def _comment(v: str) -> str:
    """Texto visto en la red (no fiable) para un comentario YAML: una línea, imprimible y corto."""
    return re.sub(r"[^\w .,:;()/+@-]", "", v.replace("\n", " "), flags=re.UNICODE)[:70].strip()


def render(s: Site, r: Result) -> str:
    used = {h.id for h in s.hosts} | {v.id for v in s.vips}
    counters: dict[str, int] = {}
    lines = [
        f"# Propuesta de `vigia descubrir` para «{_comment(s.sitio.nombre)}» (fuente: {r.source}).",
        "# NO se versiona: los comentarios llevan nombres vistos en la red.",
        "# Copia a site.yaml lo que proceda, cambia los ids y revisa el tipo; luego `vigia validate`.",
        f"# {len(r.proposals)} equipos propuestos · {r.clients} clientes sin proponer · "
        f"{r.known} ya en el sitio",
        "",
        "hosts:",
    ]
    ids = []
    for p in r.proposals:
        base = p.tipo.value
        n = counters.get(base, 0)
        while True:
            n += 1
            id_ = f"{base}-{n}"
            if id_ not in used:
                break
        counters[base] = n
        used.add(id_)
        ids.append(id_)
        seen = ", ".join(_comment(x) for x in [*p.seen.names[:3], p.seen.vendor] if x and _comment(x))
        ports = " ".join(str(x) for x in sorted(p.seen.ports))
        lines.append(f"  # {seen or 'sin nombre'} · puertos: {ports or '-'}")
        if p.seen.web and _comment(p.seen.web):
            lines.append(f"  # web: {_comment(p.seen.web)}")
        if not p.seen.live:
            lines.append("  # no respondía al sondear: puertos vistos antes por netinv (¿apagado o dormido?)")
        for note in p.notes:
            lines.append(f"  # {note}")
        lines += [f"  - id: {id_}", f"    tipo: {base}", f"    ip: {p.seen.ip}"]
        if p.seen.node_metrics:
            lines.append("    node_exporter: {puerto: 9100, gestion: externo}")
        if 9182 in p.seen.ports:
            lines.append("    windows_exporter: {puerto: 9182, gestion: externo}")
        elif p.tipo.value == "windows":
            lines.append("    # windows_exporter: {puerto: 9182, gestion: externo}   # tras instalarlo")
        if p.tipo.value in ("synology", "qnap", "switch", "impresora", "sai"):
            lines.append("    # snmp: {auth: <nombre>}   # si admite SNMP v3 (modulos.snmp.auths)")
    if not r.proposals:
        lines[-1] = "hosts: []"
    lines += (["", "ping:"] + [f"  - host: {i}" for i in ids]) if ids else ["", "ping: []"]
    if r.client_seen:
        lines += ["", "# clientes sin proponer (IP: puertos abiertos; revisar a mano):"]
        lines += [f"#   {d.ip}: {' '.join(map(str, sorted(d.ports))) or '-'}" for d in r.client_seen]
    if r.silent:
        lines += ["", "# en el sitio, sin respuesta (¿apagado o con otra IP?):"]
        lines += [f"#   {h} ({ip})" for h, ip in r.silent]
    return "\n".join(lines) + "\n"


def subnets_to_scan(s: Site, subnet: str | None) -> list[str]:
    nets = [c for c, _ in s.red.networks]
    if subnet is None:
        return nets
    norm = str(ipaddress.ip_network(subnet))
    if norm not in nets:
        raise ValueError(f"{subnet} no es una subred del sitio ({', '.join(nets)})")
    return [norm]


def plan(s: Site, source: str, subnet: str | None = None) -> str:
    """Qué haría `descubrir` (sin --yes)."""
    n = s.modulos.netinv
    src = ("netinv" if n.activo else "local") if source == "auto" else source
    first = (
        f"leer los equipos de netinv (http://{s.monitor_host.ip}:{n.puerto}/devices.json)"
        if src == "netinv"
        else f"barrer {', '.join(subnets_to_scan(s, subnet))} desde este equipo "
        f"(ping y TCP a {', '.join(map(str, SWEEP_PORTS))})"
    )
    return (
        f"vigia descubrir en «{s.sitio.nombre}»:\n"
        f"  1. {first}\n"
        f"  2. conectar por TCP a {', '.join(map(str, INFRA_PORTS))}\n"
        "     en los equipos que no están en el sitio (y leer el título de su web)\n"
        "  3. comprobar que los hosts del sitio responden (ping y TCP)\n"
        "  4. proponer los de infraestructura en un fichero fuera de git\n"
        "Añade --yes para lanzarlo."
    )


def is_ignored(path: str, cwd: str) -> bool | None:
    """True/False si `path` está en un repo git (ignorado o no); None si no hay repo."""
    r = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", path],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if r.returncode == 128:
        return None
    return r.returncode == 0
