"""CLI de vigia."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import ValidationError

from vigia import __version__
from vigia.build import build_site, write_build
from vigia.model import Site, load_site

if TYPE_CHECKING:
    from vigia.deploy import Unit

# sin variables locales en las trazas: podrían contener secretos
app = typer.Typer(
    no_args_is_help=True, help="Monitorización de redes por sitio.", pretty_exceptions_show_locals=False
)

SiteOpt = Annotated[
    Path, typer.Option("--site", "-s", help="site.yaml del sitio", exists=True, dir_okay=False)
]


@app.callback()
def main() -> None:
    """Monitorización de redes por sitio."""


@app.command()
def version() -> None:
    """Muestra la versión del paquete."""
    typer.echo(__version__)


def _load(site: Path) -> Site:
    try:
        return load_site(site)
    except ValidationError as e:
        typer.echo(f"{site}: no es válido", err=True)
        for err in e.errors():
            where = ".".join(str(x) for x in err["loc"]) or "(sitio)"
            typer.echo(f"  - {where}: {err['msg']}", err=True)
        raise typer.Exit(1) from None
    except (OSError, ValueError) as e:
        typer.echo(f"{site}: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def validate(site: SiteOpt = Path("site.yaml")) -> None:
    """Valida el site.yaml."""
    s = _load(site)
    for warning in s.warnings():
        typer.echo(f"aviso: {warning}", err=True)
    typer.echo(
        f"«{s.sitio.nombre}»: válido ({len(s.hosts)} hosts, {len(s.servicios)} servicios, "
        f"{len(s.web.objetivos)} webs, {len(s.ping)} pings)"
    )


@app.command()
def build(
    site: SiteOpt = Path("site.yaml"),
    output: Annotated[Path, typer.Option("--output", "-o", help="carpeta generada")] = Path("build"),
) -> None:
    """Genera en `build/` todo lo desplegable del sitio."""
    s = _load(site)
    content = build_site(s, site.parent)
    dest = output if output.is_absolute() else site.parent / output
    write_build(content, dest)
    typer.echo(f"«{s.sitio.nombre}»: {len(content)} ficheros en {dest}")


@app.command()
def diff(
    against: Annotated[
        Path, typer.Option("--against", "-a", help="carpeta de referencia", exists=True, file_okay=False)
    ],
    site: SiteOpt = Path("site.yaml"),
    mapping: Annotated[
        list[str] | None,
        typer.Option("--map", "-m", help="generado=referencia, para ficheros con otro nombre"),
    ] = None,
    only_common: Annotated[bool, typer.Option(help="ignora ficheros que solo estén en un lado")] = False,
) -> None:
    """Diff semántico entre lo que se generaría y una carpeta de referencia."""
    from vigia.diffing import compare, read_dir  # noqa: PLC0415

    s = _load(site)
    gen = {k: v if isinstance(v, bytes) else v.encode("utf-8") for k, v in build_site(s, site.parent).items()}
    eq = dict(x.split("=", 1) for x in (mapping or []))
    diffs = compare(gen, read_dir(against), eq)
    if only_common:
        diffs = [d for d in diffs if d.kind == "distinto"]
    for d in diffs:
        typer.echo(f"[{d.kind}] {d.path}")
        if d.detail:
            typer.echo("    " + d.detail.replace("\n", "\n    "))
    typer.echo(f"«{s.sitio.nombre}»: {len(diffs)} diferencias")
    raise typer.Exit(1 if diffs else 0)


EnvOpt = Annotated[
    Path | None,
    typer.Option(
        "--env-file",
        help="fichero de entorno del sitio (por defecto, el `.env` más cercano subiendo desde site.yaml "
        "hasta la raíz del repo)",
    ),
]


def _find_env_file(site: Path) -> Path:
    """`.env` junto a site.yaml o en una carpeta superior, sin salir del repo git del sitio."""
    d = site.resolve().parent
    while True:
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
        if (d / ".git").exists() or d.parent == d:
            return site.parent / ".env"
        d = d.parent


UnitArg = Annotated[str, typer.Argument(help="unidad: monitor, agentes:<host> o updates")]


def _built(s: Site, site: Path) -> dict[str, bytes]:
    return {k: v if isinstance(v, bytes) else v.encode() for k, v in build_site(s, site.parent).items()}


def _deploy_context(
    site: Path, env_file: Path | None, unit: str
) -> tuple[Site, dict[str, bytes], dict[str, str], Unit]:
    from vigia.deploy import check_no_secrets, read_env_file, secret_names, units  # noqa: PLC0415

    s = _load(site)
    built = _built(s, site)
    secrets = read_env_file(env_file or _find_env_file(site))
    leaks = check_no_secrets(built, secrets, secret_names(s))
    if leaks:
        typer.echo(f"ABORTADO: lo generado contiene el valor de un secreto en: {leaks}", err=True)
        raise typer.Exit(2)
    us = units(s, built)
    if unit not in us:
        typer.echo(f"unidad desconocida {unit!r}; hay: {', '.join(us) or 'ninguna'}", err=True)
        raise typer.Exit(1)
    return s, built, secrets, us[unit]


@app.command("units")
def list_units(site: SiteOpt = Path("site.yaml")) -> None:
    """Lista las unidades desplegables del sitio."""
    from vigia.deploy import units  # noqa: PLC0415

    s = _load(site)
    for name, u in units(s, _built(s, site)).items():
        typer.echo(f"{name:22} {u.deploy.adaptador:9} {u.host.id} ({u.host.ip})")


@app.command()
def deploy(
    unit: UnitArg,
    site: SiteOpt = Path("site.yaml"),
    env_file: EnvOpt = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="aplica de verdad (sin esto solo muestra el diff)")
    ] = False,
) -> None:
    """Muestra qué cambiaría en el host y, con --yes, lo despliega (con copia de seguridad previa)."""
    from vigia.deploy import RemoteError, expected, fetch_remote, run_deploy  # noqa: PLC0415
    from vigia.diffing import compare  # noqa: PLC0415

    s, built, secrets, u = _deploy_context(site, env_file, unit)
    try:
        diffs = compare(expected(u, built), fetch_remote(u, secrets))
        typer.echo(f"«{s.sitio.nombre}» · {unit} en {u.host.id}: {len(diffs)} diferencias con lo desplegado")
        for d in diffs:
            typer.echo(f"[{d.kind}] {d.path}")
            if d.detail:
                typer.echo("    " + d.detail.replace("\n", "\n    "))
        if not yes:
            typer.echo("(solo diff: añade --yes para desplegar)")
            return
        typer.echo(run_deploy(u, built, secrets))
    except RemoteError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def rollback(
    unit: UnitArg,
    site: SiteOpt = Path("site.yaml"),
    env_file: EnvOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="restaura de verdad")] = False,
) -> None:
    """Restaura la última copia de seguridad de la unidad en su host."""
    from vigia.deploy import RemoteError, rollback_script, run_rollback  # noqa: PLC0415

    _, _, secrets, u = _deploy_context(site, env_file, unit)
    if not yes:
        typer.echo(rollback_script(u))
        typer.echo("(solo muestra el script: añade --yes para restaurar)")
        return
    try:
        typer.echo(run_rollback(u, secrets))
    except RemoteError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def bridges(site: SiteOpt = Path("site.yaml"), env_file: EnvOpt = None) -> None:
    """Lee las redes Docker de los hosts y las guarda en bridges.yaml (junto a site.yaml)."""
    from vigia.bridges import collect  # noqa: PLC0415
    from vigia.deploy import RemoteError, read_env_file  # noqa: PLC0415
    from vigia.render import dump_yaml  # noqa: PLC0415

    s = _load(site)
    try:
        nets = collect(s, read_env_file(env_file or _find_env_file(site)))
    except RemoteError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    dest = site.parent / "bridges.yaml"
    dest.write_text(
        dump_yaml(nets, "# Redes Docker por host (salida de `vigia bridges`): nombran las br-<id>."),
        encoding="utf-8",
    )
    typer.echo(f"{len(nets)} redes en {dest}")


@app.command("grafana-brand")
def grafana_brand(
    site: SiteOpt = Path("site.yaml"),
    env_file: EnvOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="aplica el cambio")] = False,
) -> None:
    """Pone el nombre del sitio a la organización de Grafana (lo único de la marca que va por API)."""
    from vigia.deploy import read_env_file  # noqa: PLC0415
    from vigia.grafana import GrafanaError, brand  # noqa: PLC0415

    s = _load(site)
    try:
        typer.echo(brand(s, read_env_file(env_file or _find_env_file(site)), yes))
    except GrafanaError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
