"""Alta de un sitio nuevo: esqueleto del repo con site.yaml válido, CLAUDE.md y la skill de vigia."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import jinja2
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from vigia import __version__
from vigia.model import FQDN_RE, IP, DeviceType, Id, Text, UserName, load_site
from vigia.render import jinja_env

SKILL_REL = Path(".claude/skills/vigia/SKILL.md")

GITIGNORE = """# vigia: generado, entorno y copias locales
.venv/
build/
baseline/
propuesta.yaml
__pycache__/
.env
.env.*
!.env.example
"""

ENV_EXAMPLE = """# Secretos del sitio (copiar a .env, no versionado).
# Aquí solo los nombres; los valores, nunca.
# Token de cuenta de servicio de Grafana (rol Admin) para `vigia grafana-brand`:
GRAFANA_TOKEN=
# Contraseña de sudo de cada host que la necesite (se referencia en site.yaml: ssh.sudo_secreto):
# MONITOR_SUDO=
# Alertas (site.yaml: alertas). Bot de Telegram solo para este sitio y contraseña de aplicación del SMTP:
# ALERTAS_TELEGRAM_TOKEN=
# ALERTAS_SMTP_USUARIO=
# ALERTAS_SMTP_CLAVE=
# ALERTAS_SMTP_REMITENTE=
# ALERTAS_CORREO_DESTINO=
"""


class NewSite(BaseModel):
    """Parámetros del alta, validados con los mismos tipos que site.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Id
    nombre: Text
    marca: Text
    subred: Annotated[str, AfterValidator(lambda v: str(ipaddress.ip_network(v)))]
    dominio: Annotated[str, StringConstraints(pattern=FQDN_RE)]
    monitor_id: Id
    monitor_ip: IP
    monitor_tipo: DeviceType = DeviceType.linux
    usuario: UserName
    sensible: bool = False
    vigia_path: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._/~-]{1,200}$")] | None = None


@dataclass(frozen=True)
class Created:
    root: Path
    files: list[str]


def skill_text() -> str:
    return files("vigia").joinpath("claude", "skills", "vigia", "SKILL.md").read_text(encoding="utf-8")


def install_skill(root: Path) -> list[Path]:
    """Instala (o actualiza) en `.claude/skills/` del sitio todas las skills del paquete, con sus ficheros."""
    written = []
    for skill in files("vigia").joinpath("claude", "skills").iterdir():
        if not skill.is_dir():
            continue
        for f in skill.iterdir():
            if not f.is_file() or f.name.endswith((".pyc", ".pyo")):
                continue
            dest = root / ".claude" / "skills" / skill.name / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read_bytes())
            written.append(dest)
    return sorted(written)


def _pyproject(p: NewSite) -> str:
    if p.vigia_path:
        source = f'vigia = {{ path = "{p.vigia_path}" }}'
    else:
        source = f'vigia = {{ git = "https://github.com/onosenday/vigia.git", tag = "v{__version__}" }}'
    return f"""[project]
name = "monitor-{p.id}"
version = "0"
description = "Sitio «{p.nombre}» de vigia"
requires-python = ">=3.12"
dependencies = ["vigia"]

[tool.uv]
package = false

[tool.uv.sources]
{source}
"""


def version_range(version: str = __version__) -> str:
    """Rango de la serie actual (0.2.x → `>=0.2,<0.3`): las de una misma serie no rompen el site.yaml."""
    major, minor = (int(x) for x in version.split(".")[:2])
    return f">={major}.{minor},<{major}.{minor + 1}"


def create(p: NewSite, root: Path) -> Created:
    """Crea el esqueleto en `root` (que no debe tener ya un site.yaml) y comprueba que el sitio es válido."""
    if (root / "site.yaml").exists():
        raise FileExistsError(f"{root}/site.yaml ya existe: no se sobrescribe")
    root.mkdir(parents=True, exist_ok=True)
    ctx = p.model_dump()
    ctx["monitor_tipo"] = p.monitor_tipo.value
    ctx["vigia_rango"] = version_range()
    site_yaml = jinja_env().get_template("site/site.yaml.j2").render(**ctx)
    # CLAUDE.md es texto (no YAML): los valores ya están validados y acotados por los tipos
    md_env = jinja2.Environment(  # noqa: S701 - markdown, no HTML
        loader=jinja2.PackageLoader("vigia", "templates"),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    claude_md = md_env.get_template("site/CLAUDE.md.j2").render(**ctx)
    out = {
        "site.yaml": site_yaml,
        "CLAUDE.md": claude_md,
        ".gitignore": GITIGNORE,
        ".env.example": ENV_EXAMPLE,
        "pyproject.toml": _pyproject(p),
        "assets/.gitkeep": "",
    }
    written = []
    for rel, text in out.items():
        f = root / rel
        if f.exists():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        written.append(rel)
    if not (root / SKILL_REL).exists():
        install_skill(root)
        written.append(str(SKILL_REL))
    load_site(root / "site.yaml")  # lo generado tiene que validar
    return Created(root, written)
