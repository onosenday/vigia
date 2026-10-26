"""Redes Docker de cada host: nombran las interfaces br-<id> de node_exporter (docker:<red>)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from vigia.deploy.remote import Remote, Runner, subprocess_runner
from vigia.model import Site

_CMD = (
    "DOCKER_HOST=${DOCKER_HOST:-unix:///var/run/docker.sock} "
    "docker network ls --no-trunc --filter driver=bridge --format '{{.ID}} {{.Name}}'"
)
_LINE = re.compile(r"^([0-9a-f]{12})[0-9a-f]* ([A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")


def collect(s: Site, secrets: Mapping[str, str], runner: Runner = subprocess_runner) -> list[dict[str, str]]:
    """Lee las redes bridge de los hosts con Docker y acceso SSH (en el orden del sitio)."""
    out: list[dict[str, str]] = []
    for h in s.hosts:
        if not (h.ssh and h.profile.docker and h.node_exporter):
            continue
        remote = Remote(h, secrets, runner)
        text = remote.run(_CMD, sudo=bool(h.ssh.sudo_secreto)).decode("utf-8", "replace")
        nets = []
        for line in text.splitlines():
            m = _LINE.match(line.strip())
            if m and m.group(2) != "bridge":  # la red por defecto es docker0
                nets.append({"host": h.id, "id": m.group(1), "nombre": m.group(2)})
        out += sorted(nets, key=lambda n: n["nombre"])
    return out
