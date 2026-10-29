"""Configuración del bot: config.json que genera `vigia build` y tokens del entorno del contenedor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HostCfg:
    id: str
    nombre: str
    """Nombre visible: el valor de la etiqueta `nombre` en Prometheus."""
    ip: str
    tipo: str


@dataclass(frozen=True)
class Proximo:
    """Márgenes de /pendientes (`modulos.bot.proximo`)."""

    certificado_dias: int = 45
    consumible_pct: int = 30
    disco_pct: int = 80
    soporte_dias: int = 180


@dataclass(frozen=True)
class Config:
    sitio: str
    chat_id: int
    zona: str
    puerto: int
    prometheus: str
    grafana: str
    netinv: bool
    disco_pct: int
    hosts: tuple[HostCfg, ...]
    """En el orden de `hosts:` del site.yaml."""
    telegram_token: str = field(repr=False)
    grafana_token: str = field(repr=False)
    certificado_dias: int = 15
    consumible_pct: int = 15
    proximo: Proximo = Proximo()


def load(path: Path, env: Mapping[str, str]) -> Config:
    d = json.loads(path.read_text(encoding="utf-8"))
    token = env.get("TELEGRAM_TOKEN", "")
    if not token:
        raise ValueError("falta TELEGRAM_TOKEN en el entorno del contenedor")
    return Config(
        sitio=str(d["sitio"]),
        chat_id=int(d["chat_id"]),
        zona=str(d["zona"]),
        puerto=int(d["puerto"]),
        prometheus=str(d["prometheus"]),
        grafana=str(d["grafana"]),
        netinv=bool(d["netinv"]),
        disco_pct=int(d["disco_pct"]),
        hosts=tuple(
            HostCfg(str(h["id"]), str(h["nombre"]), str(h["ip"]), str(h["tipo"])) for h in d["hosts"]
        ),
        telegram_token=token,
        grafana_token=env.get("GRAFANA_TOKEN", ""),
        certificado_dias=int(d.get("certificado_dias", 15)),
        consumible_pct=int(d.get("consumible_pct", 15)),
        proximo=Proximo(
            **{k: int(v) for k, v in d.get("proximo", {}).items() if k in Proximo.__dataclass_fields__}
        ),
    )
