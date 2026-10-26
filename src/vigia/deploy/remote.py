"""Ejecución remota por SSH sin secretos en argv.

- Clave SSH: `ssh -o BatchMode=yes`. Contraseña: `sshpass -e` con la contraseña en la variable `SSHPASS`
  del proceso hijo (nunca en la línea de comandos).
- sudo: `sudo -S` con la contraseña como primera línea de stdin.
- Los comandos remotos se construyen con `shlex.quote` para cada valor; nunca `shell=True` en local.
"""

from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from vigia.model import Host


class Runner(Protocol):
    def __call__(self, argv: list[str], stdin: bytes, env: Mapping[str, str]) -> tuple[int, bytes, bytes]: ...


def subprocess_runner(argv: list[str], stdin: bytes, env: Mapping[str, str]) -> tuple[int, bytes, bytes]:
    p = subprocess.run(argv, input=stdin, capture_output=True, env={**os.environ, **env}, timeout=900)  # noqa: S603
    return p.returncode, p.stdout, p.stderr


class RemoteError(RuntimeError):
    pass


@dataclass
class Remote:
    host: Host
    secrets: Mapping[str, str]
    """Valores del fichero de entorno del sitio (solo los que hagan falta salen de aquí)."""
    runner: Runner = field(default=subprocess_runner)

    def _ssh_argv(self) -> tuple[list[str], dict[str, str]]:
        ssh = self.host.ssh
        if ssh is None:
            raise RemoteError(f"host {self.host.id}: falta `ssh` (usuario y forma de entrar) en site.yaml")
        # el host tiene que estar ya en known_hosts: nunca se acepta una clave de host nueva
        base = [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=yes",
            "-p",
            str(self.host.ssh_puerto),
        ]
        env: dict[str, str] = {}
        pre: list[str] = []
        if ssh.clave:
            base[1:1] = ["-o", "BatchMode=yes"]
        else:
            assert ssh.secreto
            env["SSHPASS"] = self._secret(ssh.secreto)
            pre = ["sshpass", "-e"]
            base[1:1] = ["-o", "PreferredAuthentications=password,keyboard-interactive"]
        return [*pre, *base, f"{ssh.usuario}@{self.host.ip}"], env

    def _secret(self, name: str) -> str:
        v = self.secrets.get(name, "")
        if not v:
            raise RemoteError(f"falta el valor de {name} en el fichero de entorno del sitio")
        return v

    def _sudo_password(self) -> str | None:
        ssh = self.host.ssh
        if ssh is None or not ssh.sudo_secreto:
            return None
        for name in ssh.sudo_secreto:
            if self.secrets.get(name):
                return self.secrets[name]
        raise RemoteError(f"host {self.host.id}: ninguna de {ssh.sudo_secreto} tiene valor")

    def run(self, script: str, *, sudo: bool = False, stdin: bytes = b"") -> bytes:
        """Ejecuta `script` (bash) en el host y devuelve su stdout. Falla si el código no es 0."""
        argv, env = self._ssh_argv()
        remote = "bash -c " + shlex.quote(script)
        if sudo:
            pw = self._sudo_password()
            if pw is None:
                remote = "sudo -n " + remote
            else:
                # -k: siempre pide (y consume) la contraseña, aunque sudo la tenga en caché
                remote = "sudo -k -S -p '' " + remote
                stdin = pw.encode() + b"\n" + stdin
        try:
            code, out, err = self.runner([*argv, remote], stdin, env)
        except subprocess.TimeoutExpired:
            raise RemoteError(
                f"{self.host.id}: sin respuesta a tiempo (el despliegue puede haber quedado a medias)"
            ) from None
        except OSError as e:
            raise RemoteError(f"no se pudo ejecutar {argv[0]}: {e.strerror}") from None
        if code != 0:
            raise RemoteError(
                f"{self.host.id}: código {code}: {err.decode('utf-8', 'replace').strip()[-800:]}"
            )
        return out

    def upload(self, files: Mapping[str, bytes]) -> str:
        """Sube `files` a una carpeta temporal privada (700) del usuario SSH y devuelve su ruta."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for rel, data in sorted(files.items()):
                info = tarfile.TarInfo(rel)
                info.size = len(data)
                info.mode = 0o600 if rel.endswith(".env") else 0o644
                if rel.endswith(".sh"):
                    info.mode = 0o755
                tar.addfile(info, io.BytesIO(data))
        out = self.run(
            'd=$(mktemp -d /tmp/vigia.XXXXXX) && chmod 700 "$d" && tar -C "$d" -xzf - && echo "$d"',
            stdin=buf.getvalue(),
        )
        path = out.decode().strip()
        if not re.fullmatch(r"/tmp/vigia\.[A-Za-z0-9]{6}", path):  # noqa: S108 - la crea mktemp en el host
            raise RemoteError(f"ruta temporal inesperada: {path!r}")
        return path
