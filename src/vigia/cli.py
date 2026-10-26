"""CLI de vigia."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from vigia import __version__
from vigia.build import build_site, write_build
from vigia.model import Site, load_site

app = typer.Typer(no_args_is_help=True, help="Monitorización de redes por sitio.")

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
