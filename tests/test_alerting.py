"""Alertas: reglas según lo que hay en el sitio, secretos solo como $VAR y nada de `$` propio."""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from vigia.build import build_site
from vigia.deploy import secret_names
from vigia.model import Site

from .conftest import EXAMPLE

ALERTING = "grafana-provisioning/alerting/vigia.yml"


def _build(data: dict[str, Any]) -> dict[str, Any]:
    return build_site(Site.model_validate(data), EXAMPLE)


def _rules(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(out[ALERTING])
    return {r["uid"]: r for r in doc["groups"][0]["rules"]}


def test_reglas_del_ejemplo(example_data: dict[str, Any]) -> None:
    rules = _rules(_build(example_data))
    assert set(rules) == {
        "vigia-caido",
        "vigia-certificado",
        "vigia-disco",
        "vigia-exporter",
        "vigia-consumible",
        "vigia-impresora-error",
    }
    assert 'alerta!="no"' in rules["vigia-caido"]["data"][0]["model"]["expr"]
    assert rules["vigia-certificado"]["data"][1]["model"]["conditions"][0]["evaluator"] == {
        "type": "lt",
        "params": [15],
    }


def test_sin_web_ni_nodos_no_hay_reglas_de_certificado_ni_disco(example_data: dict[str, Any]) -> None:
    example_data["web"] = {}
    example_data.pop("externos", None)
    for h in example_data["hosts"]:
        h.pop("node_exporter", None)
        h.pop("windows_exporter", None)
        h.pop("cadvisor", None)
    example_data["hosts"] = [h for h in example_data["hosts"] if h.get("tipo") != "windows"]
    rules = _rules(_build(example_data))
    assert set(rules) == {"vigia-caido", "vigia-exporter", "vigia-consumible", "vigia-impresora-error"}


def test_inactivo_no_genera_nada(example_data: dict[str, Any]) -> None:
    example_data["alertas"]["activo"] = False
    out = _build(example_data)
    assert ALERTING not in out
    assert "GF_SMTP" not in out["ejemplo_monitor.yml"]


def test_activo_sin_canal_falla(example_data: dict[str, Any]) -> None:
    example_data["alertas"] = {"activo": True}
    with pytest.raises(ValidationError, match="sin canal"):
        Site.model_validate(example_data)


def test_solo_variables_y_sin_dolar_propio(example_data: dict[str, Any]) -> None:
    text = _build(example_data)[ALERTING]
    dollars = re.findall(r"\$[A-Za-z0-9_{]*", text)
    assert sorted(set(dollars)) == [
        "$ALERTAS_CORREO_DESTINO",
        "$ALERTAS_TELEGRAM_TOKEN",
    ]
    assert "[Ejemplo]" in text
    # Grafana re-tipa lo que interpola: el chat id va literal y como texto
    assert "chatid: '-1000000000001'" in text


def test_compose_pasa_las_variables_a_grafana(example_data: dict[str, Any]) -> None:
    compose = _build(example_data)["ejemplo_monitor.yml"]
    assert '"GF_SMTP_PASSWORD=${ALERTAS_SMTP_CLAVE}"' in compose
    assert '"ALERTAS_TELEGRAM_TOKEN=${ALERTAS_TELEGRAM_TOKEN}"' in compose


def test_token_y_clave_son_secretos(example_data: dict[str, Any]) -> None:
    names = secret_names(Site.model_validate(example_data))
    assert {"ALERTAS_TELEGRAM_TOKEN", "ALERTAS_SMTP_CLAVE"} <= names


def test_marca_no_alertar_en_objetivos(example_data: dict[str, Any]) -> None:
    hosts = yaml.safe_load(_build(example_data)["prometheus/targets/hosts.yml"])
    marcados = [g["labels"]["nombre"] for g in hosts if g["labels"].get("alerta") == "no"]
    assert marcados == ["Impresora planta 1"]


def test_reglas_de_impresora(example_data: dict[str, Any]) -> None:
    rules = _rules(_build(example_data))
    assert {"vigia-consumible", "vigia-impresora-error"} <= set(rules)
    cons = rules["vigia-consumible"]
    assert cons["data"][1]["model"]["conditions"][0]["evaluator"] == {"type": "lt", "params": [15]}
    assert 'prtMarkerSuppliesType!~"waste.*"' in cons["data"][0]["model"]["expr"]
    err = rules["vigia-impresora-error"]["data"][0]["model"]["expr"]
    assert "jammed" in err and "inputTrayEmpty" not in err and "lowToner" not in err
    example_data["alertas"]["umbrales"]["consumible_pct"] = 25
    rules = _rules(_build(example_data))
    assert rules["vigia-consumible"]["data"][1]["model"]["conditions"][0]["evaluator"]["params"] == [25]


def test_sin_impresoras_snmp_no_hay_reglas_de_impresora(example_data: dict[str, Any]) -> None:
    for h in example_data["hosts"]:
        if h["tipo"] == "impresora":
            h.pop("snmp", None)
    out = _build(example_data)
    assert not {"vigia-consumible", "vigia-impresora-error"} & set(_rules(out))
    assert "snmp/vigia-modulos.yml" not in out
    assert "vigia-modulos" not in out["ejemplo_monitor.yml"]
    assert "impresoras.json" not in {k.split("/")[-1] for k in out}


def test_impresora_dormida_no_avisa_de_exporter(example_data: dict[str, Any]) -> None:
    out = _build(example_data)
    assert 'alerta!="no"' in _rules(out)["vigia-exporter"]["data"][0]["model"]["expr"]
    snmp = yaml.safe_load(out["prometheus/targets/snmp.yml"])
    by_name = {g["labels"]["nombre"]: g["labels"] for g in snmp}
    assert by_name["Impresora planta 1"]["alerta"] == "no"  # su ping lleva alerta: false
    assert by_name["Impresora planta 1"]["__param_module"] == "printer_mib,hrDevice,vigia_impresora"
    assert "alerta" not in by_name["NAS"]
