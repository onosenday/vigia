"""Despliegue de lo generado: unidades (monitor, agentes, updates-exporter) y adaptadores.

Cada despliegue: copia de seguridad fechada en el host → sincronización solo de lo que gestiona vigia →
compose (setFile en OMV) → `up` → reinicio de los contenedores que releen configuración.
`fetch_remote` descarga lo remoto para el diff previo sin tocar nada;
`run_rollback` restaura la última copia.

Límite conocido (OMV): `omv-rpc setFile` recibe el JSON del stack por argv, y ese JSON incluye su campo `env`
con secretos; mientras corre, es visible en /proc del host para quien pueda leerlo. Es la interfaz de OMV:
en hosts OMV conviene `hidepid=2` en /proc o que solo haya usuarios de confianza.
"""

from __future__ import annotations

import io
import json
import re
import shlex
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from vigia.deploy.remote import Remote, RemoteError, Runner, subprocess_runner
from vigia.model import Deploy, DeployOMV, DeploySynology, Host, Site
from vigia.tareas import TEXTFILE_DIR, textfile_activo

__all__ = [
    "Remote",
    "RemoteError",
    "Unit",
    "expected",
    "fetch_remote",
    "read_env_file",
    "run_deploy",
    "run_rollback",
    "units",
]

BACKUPS = "/root/vigia-backups"
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
"""Carpetas que vigia gestiona enteras (se vacían y se vuelven a copiar, dentro de la misma carpeta:
los contenedores montan por inodo y recrearla los dejaría apuntando a la vieja)."""
RELOAD = ["prometheus", "blackbox", "grafana", "snmp-exporter", "bot"]
MAX_REMOTE_FILE = 20 * 1024 * 1024
MAX_REMOTE_TOTAL = 100 * 1024 * 1024


@dataclass(frozen=True)
class Unit:
    name: str
    host: Host
    deploy: Deploy
    project: str
    compose_file: str
    """Ruta en `build/` del compose de la unidad."""
    dirs: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    """Ficheros sueltos que se copian (relativos a la carpeta del stack)."""
    prefix: str = ""
    """Prefijo de las rutas en `build/` (agentes/, updates-exporter/)."""
    restart: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    """Variables que necesita el compose (para el `.env` de los adaptadores compose/synology)."""
    textfile: bool = False
    """Su node_exporter lee la carpeta de tareas: se crea antes del `up`."""


def units(s: Site, build: Mapping[str, bytes]) -> dict[str, Unit]:
    out: dict[str, Unit] = {}
    pre = s.monitor.prefijo_contenedores
    mon = s.monitor_host
    if s.monitor.deploy:
        dirs = [d for d in MONITOR_DIRS if any(k.startswith(d + "/") for k in build)]
        secrets = [v for v in [s.modulos.pihole_exporter.secreto] if v]
        for a in s.modulos.snmp.auths:
            secrets += [v for v in (a.usuario, a.clave_auth, a.clave_priv, a.comunidad) if v]
        if s.alertas.activo:
            secrets += s.alertas.env_vars
        if s.modulos.bot.activo and s.modulos.bot.grafana_token:
            secrets.append(s.modulos.bot.grafana_token)
        out["monitor"] = Unit(
            "monitor",
            mon,
            s.monitor.deploy,
            s.monitor.proyecto,
            f"{s.monitor.proyecto}.yml",
            dirs=dirs,
            files=["prometheus/prometheus.yml"],
            restart=[pre + c for c in RELOAD],
            secrets=secrets,
            textfile=textfile_activo(mon),
        )
    for h in s.hosts:
        if h.deploy and f"agentes/{h.id}.yml" in build:
            out[f"agentes:{h.id}"] = Unit(
                f"agentes:{h.id}",
                h,
                h.deploy,
                f"{h.id}-agentes",
                f"agentes/{h.id}.yml",
                textfile=textfile_activo(h),
            )
    u = s.modulos.updates_exporter
    if u.activo and u.deploy and u.host:
        files = sorted(
            k.removeprefix("updates-exporter/")
            for k in build
            if k.startswith("updates-exporter/") and k != "updates-exporter/docker-compose.yml"
        )
        out["updates"] = Unit(
            "updates",
            s.get_host(u.host),
            u.deploy,
            "updates-exporter",
            "updates-exporter/docker-compose.yml",
            files=files,
            prefix="updates-exporter/",
        )
    return out


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE por línea, con comillas opcionales. Nunca se ejecuta (no es `source`)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            out[k] = v
    return out


SECRET_NAME = re.compile(r"PASS|PWD|TOKEN|SECRET|KEY|CLAVE|COMMUNITY|COMUNIDAD|AUTH|PRIV", re.I)


def secret_names(s: Site) -> set[str]:
    """Variables que el sitio usa como secreto."""
    out = {v for v in [s.modulos.pihole_exporter.secreto] if v}
    for a in s.modulos.snmp.auths:
        out |= {v for v in (a.usuario, a.clave_auth, a.clave_priv, a.comunidad) if v}
    out |= set(s.alertas.secret_vars)
    if s.modulos.bot.grafana_token:
        out.add(s.modulos.bot.grafana_token)
    for h in s.hosts:
        if h.ssh:
            out |= set(h.ssh.sudo_secreto) | ({h.ssh.secreto} if h.ssh.secreto else set())
    return out


def check_no_secrets(
    build: Mapping[str, bytes], secrets: Mapping[str, str], names: set[str] | None = None
) -> list[str]:
    """Ficheros de `build/` que contienen el valor de algún secreto (deben ser ninguno).

    Secreto = variable que el sitio usa como tal (`names`) o cuyo nombre lo indica (PASS, TOKEN, KEY…);
    el resto del fichero de entorno (hosts, usuarios) puede aparecer en lo generado.
    """
    valores = {
        v for k, v in secrets.items() if len(v) >= 4 and (k in (names or set()) or SECRET_NAME.search(k))
    }
    return sorted(k for k, data in build.items() if any(v.encode() in data for v in valores))


# --- piezas de script ------------------------------------------------------------------------------

q = shlex.quote


def _payload(u: Unit, build: Mapping[str, bytes], secrets: Mapping[str, str]) -> dict[str, bytes]:
    files = expected(u, build)
    if not isinstance(u.deploy, DeployOMV) and u.secrets:
        faltan = [v for v in u.secrets if not secrets.get(v)]
        if faltan:
            raise RemoteError(f"faltan valores en el fichero de entorno: {faltan}")
        files[".env"] = "".join(f"{k}={secrets[k]}\n" for k in u.secrets).encode()
    return files


def _stack_dir(u: Unit) -> str | None:
    return u.deploy.dir


def _backup_script(u: Unit) -> str:
    d = _stack_dir(u)
    base = f"{BACKUPS}/{u.project}"
    lines = [
        f"mkdir -p {q(base)} && chmod 700 {q(BACKUPS)}",
        f"bak=$(mktemp -d {q(base)}/$(date +%Y%m%d-%H%M%S)-XXXX)",
    ]
    if d:
        # sin copia comprobada no se sigue (set -e): tar y su lectura deben salir bien
        lines.append(
            f'if [ -d {q(d)} ]; then tar -C {q(str(Path(d).parent))} -czf "$bak/dir.tgz" {q(Path(d).name)}; '
            'tar -tzf "$bak/dir.tgz" >/dev/null; fi'
        )
    if isinstance(u.deploy, DeployOMV):
        rpc = json.dumps({"uuid": u.deploy.uuid})
        lines.append(f'omv-rpc -u admin Compose getFile {q(rpc)} > "$bak/file.json"')
    lines += ['chmod -R go-rwx "$bak"', f'ln -sfn "$bak" {q(base)}/ultimo', 'echo "copia: $bak"']
    return "\n".join(lines)


def _clear_managed(d: str, sub: str, only_if: str | None = None) -> str:
    """Vacía `d/sub` (crea la carpeta si falta) solo si de verdad es una carpeta real dentro de `d`.

    Sin seguir enlaces (`find -P`) y comprobando con realpath que no se sale del stack.
    """
    t = f"{d}/{sub}"
    cond = f"[ -d {q(only_if)} ] && " if only_if else ""
    return (
        f"if {cond}true; then mkdir -p {q(t)}; "
        f"[ ! -L {q(t)} ] || {{ echo 'enlace inesperado: {t}' >&2; exit 1; }}; "
        f'[ "$(realpath {q(t)})" = "$(realpath {q(d)})/{sub}" ] '
        f'|| {{ echo "ruta fuera del stack: {t}" >&2; exit 1; }}; '
        f"find -P {q(t)} -mindepth 1 -delete; fi"
    )


def _sync_script(u: Unit, up: str) -> str:
    d = _stack_dir(u)
    if not d:
        return ""
    lines = [f"mkdir -p {q(d)}"]
    for sub in u.dirs:
        lines.append(_clear_managed(d, sub, only_if=up + "/" + sub))
        t = f"{d}/{sub}"
        lines.append(
            f"if [ -d {q(up + '/' + sub)} ]; then cp -r {q(up + '/' + sub)}/. {q(t)}/; "
            f"chmod -R a+rX {q(t)}; fi"
        )
    for f in u.files:
        t = f"{d}/{f}"
        lines.append(f"mkdir -p {q(str(Path(t).parent))} && cp {q(up + '/' + f)} {q(t)}")
        if f.endswith(".sh"):
            lines.append(f"chmod 755 {q(t)}")
    return "\n".join(lines)


_SETFILE = """python3 - "$1" "$2" "$3" <<'PY'
import json, subprocess, sys
body, uuid, name = sys.argv[1:4]
rpc = lambda m, p: subprocess.run(['omv-rpc', '-u', 'admin', 'Compose', m, json.dumps(p)],
                                  check=True, capture_output=True, text=True).stdout
cur = json.loads(rpc('getFile', {'uuid': uuid}))
assert cur['name'] == name, cur['name']
cur['body'] = open(body).read()
cur.setdefault('description', '')
rpc('setFile', cur)
print('setFile OK')
PY"""


_ENVCHECK = """python3 - "$@" <<'PY'
import json, re, subprocess, sys
uuid, names = sys.argv[1], sys.argv[2:]
cur = json.loads(subprocess.run(['omv-rpc', '-u', 'admin', 'Compose', 'getFile', json.dumps({'uuid': uuid})],
                                check=True, capture_output=True, text=True).stdout)
faltan = [n for n in names if not re.search('^' + n + '=.', cur.get('env') or '', re.M)]
if faltan:
    sys.exit('ABORTADO: el Environment del stack en OMV no tiene: ' + ' '.join(faltan)
             + ' (añádelas en la UI de OMV antes de desplegar)')
PY"""


def _env_check_script(u: Unit) -> str:
    """OMV: el env del stack lo mantiene el usuario en la UI. Sin las variables que usa el compose, Grafana no
    provisiona sus alertas y se para: se comprueba antes de tocar nada (solo nombres, nunca valores)."""
    if not (isinstance(u.deploy, DeployOMV) and u.secrets):
        return ""
    names = " ".join(q(n) for n in u.secrets)
    return f"set -- {q(u.deploy.uuid)} {names}\n{_ENVCHECK}"


def _up_script(u: Unit, up: str) -> str:
    dep = u.deploy
    if isinstance(dep, DeployOMV):
        setfile = f"set -- {q(up + '/compose.yml')} {q(dep.uuid)} {q(dep.stack)}\n{_SETFILE}"
        if dep.dir:
            d = dep.dir
            upc = (
                f"docker compose --project-directory {q(d)} -f {q(d + '/' + dep.stack + '.yml')} "
                f"--env-file {q(d + '/' + dep.stack + '.env')} up -d --build"
            )
        else:
            rpc = json.dumps({"uuid": dep.uuid, "command": "up -d", "command2": ""})
            upc = f"omv-rpc -u admin Compose doCommand {q(rpc)} >/dev/null"
        return f"{setfile}\n{upc}"
    docker = "/usr/local/bin/docker" if isinstance(dep, DeploySynology) else "docker"
    proj = dep.proyecto or u.project
    d = dep.dir
    return (
        f"cp {q(up + '/compose.yml')} {q(d + '/' + proj + '.yml')}\n"
        + (f"install -m 600 {q(up + '/.env')} {q(d + '/.env')}\n" if u.secrets else "")
        + f"{docker} compose -p {q(proj)} --project-directory {q(d)} -f {q(d + '/' + proj + '.yml')} "
        + (f"--env-file {q(d + '/.env')} " if u.secrets else "")
        + "up -d --build"
    )


def _restart_script(u: Unit) -> str:
    if not u.restart:
        return ""
    docker = "/usr/local/bin/docker" if isinstance(u.deploy, DeploySynology) else "docker"
    names = " ".join(q(c) for c in u.restart)
    return (
        f'for c in {names}; do {docker} inspect "$c" >/dev/null 2>&1 && {docker} restart "$c" >/dev/null'
        ' && echo "reiniciado $c"; done; true'
    )


def _textfile_script(u: Unit) -> str:
    """Carpeta de las tareas (idempotente). Sin root (compose sin sudo) avisa y sigue: la alerta «Tarea sin
    datos» lo hará visible."""
    if not u.textfile:
        return ""
    d = q(TEXTFILE_DIR)
    return (
        f"install -d -m 755 {d} 2>/dev/null || "
        f'echo "aviso: no se pudo crear {TEXTFILE_DIR}; '
        f'créala como root (install -d -m 755 {TEXTFILE_DIR})" >&2'
    )


def _needs_sudo(u: Unit) -> bool:
    return isinstance(u.deploy, DeployOMV | DeploySynology) or bool(u.host.ssh and u.host.ssh.sudo_secreto)


def deploy_script(u: Unit, up: str) -> str:
    parts = [
        "set -euo pipefail",
        f"trap 'rm -rf {q(up)}' EXIT",  # la subida (con el fichero de entorno) no queda en /tmp ni si falla
        _env_check_script(u),
        _backup_script(u),
        _sync_script(u, up),
        _textfile_script(u),
        _up_script(u, up),
        _restart_script(u),
        "echo desplegado",
    ]
    return "\n".join(p for p in parts if p)


def run_deploy(
    u: Unit, build: Mapping[str, bytes], secrets: Mapping[str, str], runner: Runner = subprocess_runner
) -> str:
    r = Remote(u.host, secrets, runner)
    up = r.upload(_payload(u, build, secrets))
    return r.run(deploy_script(u, up), sudo=_needs_sudo(u)).decode("utf-8", "replace")


def rollback_script(u: Unit) -> str:
    base = f"{BACKUPS}/{u.project}/ultimo"
    lines = [
        "set -euo pipefail",
        f"b=$(readlink -f {q(base)})",
        '[ -d "$b" ] || { echo "sin copia" >&2; exit 1; }',
        f'case "$b" in {q(BACKUPS + "/" + u.project)}/*) ;; '
        f'*) echo "copia fuera de {BACKUPS}" >&2; exit 1;; esac',
    ]
    d = _stack_dir(u)
    if d:
        lines.append('[ -f "$b/dir.tgz" ] || { echo "falta $b/dir.tgz" >&2; exit 1; }')
        lines.append('tar -tzf "$b/dir.tgz" >/dev/null')
        # lo gestionado se vacía antes: lo añadido después de la copia no debe quedarse
        lines += [_clear_managed(d, sub) for sub in u.dirs]
        lines.append(f'tar -C {q(str(Path(d).parent))} --no-same-owner -xzf "$b/dir.tgz"')
    dep = u.deploy
    if isinstance(dep, DeployOMV):
        lines.append('omv-rpc -u admin Compose setFile "$(cat "$b/file.json")" >/dev/null')
        if dep.dir:
            lines.append(
                f"docker compose --project-directory {q(dep.dir)} -f {q(dep.dir + '/' + dep.stack + '.yml')} "
                f"--env-file {q(dep.dir + '/' + dep.stack + '.env')} up -d --build"
            )
        else:
            rpc = json.dumps({"uuid": dep.uuid, "command": "up -d", "command2": ""})
            lines.append(f"omv-rpc -u admin Compose doCommand {q(rpc)} >/dev/null")
    else:
        docker = "/usr/local/bin/docker" if isinstance(dep, DeploySynology) else "docker"
        proj = dep.proyecto or u.project
        lines.append(
            f"{docker} compose -p {q(proj)} --project-directory {q(dep.dir)} "
            f"-f {q(dep.dir + '/' + proj + '.yml')} up -d --build"
        )
    restart = _restart_script(u)
    if restart:
        lines.append(restart)
    lines.append('echo "restaurado desde $b"')
    return "\n".join(lines)


def run_rollback(u: Unit, secrets: Mapping[str, str], runner: Runner = subprocess_runner) -> str:
    r = Remote(u.host, secrets, runner)
    return r.run(rollback_script(u), sudo=_needs_sudo(u)).decode("utf-8", "replace")


def fetch_script(u: Unit) -> str:
    """Empaqueta (tar.gz por stdout) lo que hay ahora en el host para esta unidad. Solo lectura."""
    d = _stack_dir(u)
    lines = ["set -euo pipefail", "t=$(mktemp -d)", "trap 'rm -rf \"$t\"' EXIT"]
    dep = u.deploy
    if isinstance(dep, DeployOMV):
        rpc = json.dumps({"uuid": dep.uuid})
        lines.append(
            f"omv-rpc -u admin Compose getFile {q(rpc)} | python3 -c "
            + q("import json,sys; sys.stdout.write(json.load(sys.stdin)['body'])")
            + ' > "$t/compose.yml"'
        )
    elif d:
        proj = dep.proyecto or u.project
        lines.append(f'cp {q(d + "/" + proj + ".yml")} "$t/compose.yml" 2>/dev/null || true')
    if d:
        for sub in [*u.dirs, *u.files]:
            lines.append(
                f'if [ -e {q(d + "/" + sub)} ]; then mkdir -p "$t/$(dirname {q(sub)})"; '
                f'cp -r {q(d + "/" + sub)} "$t"/{q(sub)}; fi'
            )
    lines.append('tar -C "$t" -czf - .')
    return "\n".join(lines)


def fetch_remote(u: Unit, secrets: Mapping[str, str], runner: Runner = subprocess_runner) -> dict[str, bytes]:
    """Devuelve lo que hay ahora en el host para la unidad (para compararlo con lo generado)."""
    r = Remote(u.host, secrets, runner)
    data = r.run(fetch_script(u), sudo=_needs_sudo(u))
    out: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():  # solo en memoria (nunca extract): sin riesgo de rutas fuera
            if not m.isfile():
                continue
            total += m.size
            if m.size > MAX_REMOTE_FILE or total > MAX_REMOTE_TOTAL:
                raise RemoteError(f"lo devuelto por {u.host.id} es demasiado grande ({m.name})")
            name = "".join(c for c in m.name.removeprefix("./") if c.isprintable())
            f = tar.extractfile(m)
            if f:
                out[name] = f.read()
    return out


def expected(u: Unit, build: Mapping[str, bytes]) -> dict[str, bytes]:
    """Lo que la unidad debería tener en el host, con las mismas rutas que devuelve `plan`."""
    files = {"compose.yml": build[u.compose_file]}
    for d in u.dirs:
        files.update({k: v for k, v in build.items() if k.startswith(d + "/")})
    for f in u.files:
        files[f] = build[u.prefix + f]
    return files
