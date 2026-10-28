from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from vigia.bot.config import load
from vigia.build import build_site
from vigia.model import Site

from .conftest import EXAMPLE


def _out(data: dict[str, Any]) -> tuple[Site, dict[str, str | bytes]]:
    s = Site.model_validate(data)
    return s, build_site(s, EXAMPLE)


def test_bot_en_el_build(example_data: dict[str, Any]) -> None:
    s, out = _out(example_data)
    assert {"bot/Dockerfile", "bot/__main__.py", "bot/comandos.py", "bot/config.json"} <= set(out)
    assert not any("__pycache__" in k for k in out)
    cfg = json.loads(out["bot/config.json"])
    assert [h["id"] for h in cfg["hosts"]] == [h.id for h in s.hosts]
    assert cfg["chat_id"] == -1000000000001
    assert (cfg["prometheus"], cfg["grafana"]) == ("http://prometheus:9090", "http://grafana:3000")


def test_servicio_del_bot(example_data: dict[str, Any]) -> None:
    _, out = _out(example_data)
    bot = yaml.safe_load(out["ejemplo_monitor.yml"])["services"]["bot"]
    assert bot["read_only"] is True and bot["cap_drop"] == ["ALL"] and "ports" not in bot
    assert bot["user"] == "65534:65534" and bot["container_name"] == "ejm-bot"
    assert "TELEGRAM_TOKEN=${ALERTAS_TELEGRAM_TOKEN}" in bot["environment"]
    assert "GRAFANA_TOKEN=${BOT_GRAFANA_TOKEN}" in bot["environment"]
    assert bot["volumes"] == ["./bot:/etc/vigia-bot:ro"]


def test_job_de_prometheus(example_data: dict[str, Any]) -> None:
    _, out = _out(example_data)
    jobs = yaml.safe_load(out["prometheus/prometheus.yml"])["scrape_configs"]
    job = next(j for j in jobs if j["job_name"] == "bot")
    assert job["static_configs"] == [{"targets": ["bot:9466"], "labels": {"nombre": "Bot de Telegram"}}]


def test_config_generada_la_lee_el_bot(example_data: dict[str, Any], tmp_path: Path) -> None:
    s, out = _out(example_data)
    p = tmp_path / "config.json"
    p.write_text(str(out["bot/config.json"]), encoding="utf-8")
    c = load(p, {"TELEGRAM_TOKEN": "123:abc"})
    assert [h.nombre for h in c.hosts] == [h.display_name for h in s.hosts]


def test_sin_bot(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"]["activo"] = False
    _, out = _out(example_data)
    assert not any(k.startswith("bot/") for k in out)
    assert "vigia-bot" not in str(out["ejemplo_monitor.yml"])
    assert "job_name: bot" not in str(out["prometheus/prometheus.yml"])
