from typer.testing import CliRunner

from vigia import __version__
from vigia.cli import app


def test_version() -> None:
    res = CliRunner().invoke(app, ["version"])
    assert res.exit_code == 0
    assert __version__ in res.output
