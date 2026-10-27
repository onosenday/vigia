from __future__ import annotations

import io
import json
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from vigia.build import build_site
from vigia.deploy import (
    check_no_secrets,
    deploy_script,
    fetch_script,
    read_env_file,
    rollback_script,
    run_deploy,
    units,
)
from vigia.model import Site

from .conftest import EXAMPLE

SECRETS = {
    "NODO2_SUDO": "sudo-sintetico-123",
    "PIHOLE_PASSWORDS": "pihole-sintetico-456",
    "SNMP_NAS_USUARIO": "u",
    "SNMP_NAS_AUTH": "auth-sintetica",
    "SNMP_NAS_PRIV": "priv-sintetica",
    "SNMP_COMUNIDAD": "comunidad-sintetica",
    "ALERTAS_TELEGRAM_TOKEN": "123456:token-sintetico",
    "ALERTAS_SMTP_USUARIO": "alertas@ejemplo.lan",
    "ALERTAS_SMTP_CLAVE": "smtp-sintetica-789",
    "ALERTAS_SMTP_REMITENTE": "alertas@ejemplo.lan",
    "ALERTAS_CORREO_DESTINO": "sistemas@ejemplo.lan",
}


def _built(data: dict[str, Any]) -> tuple[Site, dict[str, bytes]]:
    s = Site.model_validate(data)
    return s, {k: v if isinstance(v, bytes) else v.encode() for k, v in build_site(s, EXAMPLE).items()}


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bytes, dict[str, str]]] = []

    def __call__(self, argv: list[str], stdin: bytes, env: Mapping[str, str]) -> tuple[int, bytes, bytes]:
        self.calls.append((argv, stdin, dict(env)))
        if "mktemp" in argv[-1]:
            return 0, b"/tmp/vigia.abc123\n", b""
        return 0, b"desplegado\n", b""


def test_unidades(example_data: dict[str, Any]) -> None:
    s, built = _built(example_data)
    assert set(units(s, built)) == {"monitor", "agentes:nodo2", "updates"}


@pytest.mark.parametrize("name", ["monitor", "agentes:nodo2", "updates"])
def test_scripts_validos_en_bash(example_data: dict[str, Any], name: str) -> None:
    s, built = _built(example_data)
    u = units(s, built)[name]
    for script in (deploy_script(u, "/tmp/vigia.x"), rollback_script(u), fetch_script(u)):
        subprocess.run(["bash", "-n"], input=script.encode(), check=True)


def test_secretos_nunca_en_argv(example_data: dict[str, Any]) -> None:
    s, built = _built(example_data)
    runner = FakeRunner()
    run_deploy(units(s, built)["agentes:nodo2"], built, SECRETS, runner)
    run_deploy(units(s, built)["monitor"], built, SECRETS, runner)
    for argv, _, _ in runner.calls:
        texto = " ".join(argv)
        for v in SECRETS.values():
            if len(v) > 3:
                assert v not in texto
    # sudo de nodo2: la contraseña va como primera línea de stdin
    sudo = [c for c in runner.calls if "sudo -k -S" in c[0][-1]]
    assert sudo and sudo[0][1].startswith(b"sudo-sintetico-123\n")


def test_env_remoto_solo_con_las_variables_necesarias(example_data: dict[str, Any]) -> None:
    s, built = _built(example_data)
    runner = FakeRunner()
    run_deploy(units(s, built)["monitor"], built, SECRETS, runner)
    upload = next(c for c in runner.calls if "mktemp" in c[0][-1])
    with tarfile.open(fileobj=io.BytesIO(upload[1]), mode="r:gz") as tar:
        env = tar.getmember(".env")
        assert env.mode == 0o600
        f = tar.extractfile(env)
        assert f is not None
        contenido = f.read().decode()
    assert "PIHOLE_PASSWORDS=pihole-sintetico-456" in contenido
    assert "ALERTAS_SMTP_CLAVE=smtp-sintetica-789" in contenido
    assert "NODO2_SUDO" not in contenido


def test_ssh_con_contrasena_por_entorno(example_data: dict[str, Any]) -> None:
    example_data["hosts"][2]["ssh"] = {
        "usuario": "admin",
        "clave": False,
        "secreto": "NODO2_SUDO",
        "sudo_secreto": ["NODO2_SUDO"],
    }
    s, built = _built(example_data)
    runner = FakeRunner()
    run_deploy(units(s, built)["agentes:nodo2"], built, SECRETS, runner)
    argv, _, env = runner.calls[0]
    assert argv[:2] == ["sshpass", "-e"]
    assert env["SSHPASS"] == "sudo-sintetico-123"


def test_detecta_secreto_en_build() -> None:
    assert check_no_secrets({"a.yml": b"clave: pihole-sintetico-456"}, SECRETS) == ["a.yml"]
    assert check_no_secrets({"a.yml": b"clave: ${PIHOLE_PASSWORDS}"}, SECRETS) == []
    # una IP o un usuario del fichero de entorno no son secretos
    assert check_no_secrets({"a.yml": b"host: 10.99.0.11"}, {"NODO2_HOST": "10.99.0.11"}) == []
    assert check_no_secrets({"a.yml": b"x: 10.99.0.11"}, {"OTRA": "10.99.0.11"}, {"OTRA"}) == ["a.yml"]


def test_lee_fichero_de_entorno(tmp_path: Path) -> None:
    f = tmp_path / "entorno"
    f.write_text("# comentario\nA=1\nexport B='dos'\nC=\"tres\"\nmal linea\n1X=no\n", encoding="utf-8")
    assert read_env_file(f) == {"A": "1", "B": "dos", "C": "tres"}


@pytest.mark.parametrize("ruta", ["/", "/srv", "/etc", "/srv/x/..", "/srv//x", "/srv/x/", "/srv/./x", "/a"])
def test_rutas_remotas_peligrosas(example_data: dict[str, Any], ruta: str) -> None:
    example_data["monitor"]["deploy"]["dir"] = ruta
    with pytest.raises(ValueError):
        Site.model_validate(example_data)


def test_rollback_vacia_lo_gestionado_y_exige_copia(example_data: dict[str, Any]) -> None:
    s, built = _built(example_data)
    script = rollback_script(units(s, built)["monitor"])
    assert "find -P" in script and "falta" in script and "realpath" in script


def test_diff_oculta_secretos() -> None:
    from vigia.diffing import mask

    assert mask("PIHOLE_PASSWORD=algo") == "PIHOLE_PASSWORD: ***"
    assert mask("basic_auth.password: 'x' → 'y'") == "basic_auth.password: ***"
    assert mask("nombre: \x1b[31mrojo") == "nombre: [31mrojo"


def test_bridges(example_data: dict[str, Any]) -> None:
    from vigia.bridges import collect

    class Docker(FakeRunner):
        def __call__(self, argv: list[str], stdin: bytes, env: Mapping[str, str]) -> tuple[int, bytes, bytes]:
            self.calls.append((argv, stdin, dict(env)))
            out = "0123456789abcdef bridge\nfedcba9876543210ff web_default\nmala línea\n"
            return 0, out.encode(), b""

    s = Site.model_validate(example_data)
    nets = collect(s, SECRETS, Docker())
    assert nets == [
        {"host": "nodo1", "id": "fedcba987654", "nombre": "web_default"},
        {"host": "nodo2", "id": "fedcba987654", "nombre": "web_default"},
    ]


def _omv_monitor(example_data: dict[str, Any]) -> Any:
    example_data["monitor"]["deploy"] = {
        "adaptador": "omv",
        "stack": "ejemplo_monitor",
        "uuid": "00000000-0000-4000-8000-000000000001",
        "dir": "/opt/vigia/ejemplo",
    }
    s, built = _built(example_data)
    return units(s, built)["monitor"]


def test_omv_comprueba_el_env_del_stack_antes_de_tocar_nada(example_data: dict[str, Any]) -> None:
    script = deploy_script(_omv_monitor(example_data), "/tmp/vigia.x")
    subprocess.run(["bash", "-n"], input=script.encode(), check=True)
    assert script.index("ABORTADO: el Environment") < script.index("vigia-backups")
    assert "ALERTAS_TELEGRAM_TOKEN" in script
    assert not any(v in script for v in SECRETS.values() if len(v) >= 4)


@pytest.mark.parametrize(("env", "ok"), [("PIHOLE_PASSWORDS=x\n", False), (None, True)])
def test_comprobacion_env_omv(
    example_data: dict[str, Any], tmp_path: Path, env: str | None, ok: bool
) -> None:
    u = _omv_monitor(example_data)
    if env is None:
        env = "".join(f"{n}=valor\n" for n in u.secrets)
    rpc = tmp_path / "omv-rpc"
    rpc.write_text(f"#!/bin/sh\ncat <<'J'\n{json.dumps({'env': env})}\nJ\n", encoding="utf-8")
    rpc.chmod(0o755)
    from vigia.deploy import _env_check_script  # noqa: PLC0415

    r = subprocess.run(
        ["bash", "-c", _env_check_script(u)],
        capture_output=True,
        text=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        check=False,
    )
    assert (r.returncode == 0) is ok, r.stderr
    if not ok:
        assert "ALERTAS_SMTP_CLAVE" in r.stderr
