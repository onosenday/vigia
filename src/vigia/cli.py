"""CLI de vigia."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from vigia import __version__
from vigia.build import construir, escribir
from vigia.model import Site, cargar

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


def _cargar(site: Path) -> Site:
    try:
        return cargar(site)
    except ValidationError as e:
        typer.echo(f"{site}: no es válido", err=True)
        for err in e.errors():
            donde = ".".join(str(x) for x in err["loc"]) or "(sitio)"
            typer.echo(f"  - {donde}: {err['msg']}", err=True)
        raise typer.Exit(1) from None
    except (OSError, ValueError) as e:
        typer.echo(f"{site}: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def validate(site: SiteOpt = Path("site.yaml")) -> None:
    """Valida el site.yaml."""
    s = _cargar(site)
    for aviso in s.avisos():
        typer.echo(f"aviso: {aviso}", err=True)
    typer.echo(
        f"«{s.sitio.nombre}»: válido ({len(s.hosts)} hosts, {len(s.servicios)} servicios, "
        f"{len(s.web.objetivos)} webs, {len(s.ping)} pings)"
    )


@app.command()
def build(
    site: SiteOpt = Path("site.yaml"),
    salida: Annotated[Path, typer.Option("--salida", "-o", help="carpeta generada")] = Path("build"),
) -> None:
    """Genera en `build/` todo lo desplegable del sitio."""
    s = _cargar(site)
    contenido = construir(s, site.parent)
    destino = salida if salida.is_absolute() else site.parent / salida
    escribir(contenido, destino)
    typer.echo(f"«{s.sitio.nombre}»: {len(contenido)} ficheros en {destino}")


@app.command()
def diff(
    contra: Annotated[
        Path, typer.Option("--contra", "-c", help="carpeta de referencia", exists=True, file_okay=False)
    ],
    site: SiteOpt = Path("site.yaml"),
    equivale: Annotated[
        list[str] | None,
        typer.Option("--equivale", "-e", help="generado=referencia, para ficheros con otro nombre"),
    ] = None,
    solo_comunes: Annotated[bool, typer.Option(help="ignora ficheros que solo estén en un lado")] = False,
) -> None:
    """Diff semántico entre lo que se generaría y una carpeta de referencia."""
    from vigia.diffing import comparar, leer_carpeta  # noqa: PLC0415

    s = _cargar(site)
    gen = {k: v if isinstance(v, bytes) else v.encode("utf-8") for k, v in construir(s, site.parent).items()}
    eq = dict(x.split("=", 1) for x in (equivale or []))
    difs = comparar(gen, leer_carpeta(contra), eq)
    if solo_comunes:
        difs = [d for d in difs if d.tipo == "distinto"]
    for d in difs:
        typer.echo(f"[{d.tipo}] {d.ruta}")
        if d.detalle:
            typer.echo("    " + d.detalle.replace("\n", "\n    "))
    typer.echo(f"«{s.sitio.nombre}»: {len(difs)} diferencias")
    raise typer.Exit(1 if difs else 0)
