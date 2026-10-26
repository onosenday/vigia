"""CLI de vigia."""

import typer

from vigia import __version__

app = typer.Typer(no_args_is_help=True, help="Monitorización de redes por sitio.")


@app.callback()
def main() -> None:
    """Monitorización de redes por sitio."""


@app.command()
def version() -> None:
    """Muestra la versión del paquete."""
    typer.echo(__version__)
