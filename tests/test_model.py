from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from vigia.model import Site


def _validate(d: dict[str, Any]) -> Site:
    return Site.model_validate(d)


def _assert_invalid(d: dict[str, Any], text: str) -> None:
    with pytest.raises(ValidationError) as e:
        _validate(d)
    assert text in str(e.value)


def test_example_is_valid(example_data: dict[str, Any]) -> None:
    s = _validate(example_data)
    assert s.monitor_host.id == "nodo1"
    assert [p[1] for p in s.resolved_pings()][:2] == ["router", "VIP DNS"]


def test_unknown_field(example_data: dict[str, Any]) -> None:
    example_data["hosts"][1]["password"] = "x"
    _assert_invalid(example_data, "Extra inputs are not permitted")


def test_ip_outside_subnet(example_data: dict[str, Any]) -> None:
    example_data["hosts"][1]["ip"] = "192.0.2.10"
    _assert_invalid(example_data, "fuera de la subred")


def test_duplicate_ids(example_data: dict[str, Any]) -> None:
    example_data["hosts"][2]["id"] = "nodo1"
    _assert_invalid(example_data, "ids repetidos")


def test_netinv_without_authorization(example_data: dict[str, Any]) -> None:
    del example_data["modulos"]["netinv"]["autorizacion"]
    _assert_invalid(example_data, "autorizacion")


def test_secret_only_by_name(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["pihole_exporter"]["secreto"] = "mi clave secreta"
    _assert_invalid(example_data, "String should match pattern")


def test_url_with_credentials(example_data: dict[str, Any]) -> None:
    example_data["servicios"][0]["url"] = "http://admin:clave@10.99.0.11:8000"
    _assert_invalid(example_data, "usuario ni contraseña")


def test_hibernating_without_200(example_data: dict[str, Any]) -> None:
    example_data["servicios"][1]["espera_200"] = False
    _assert_invalid(example_data, "hiberna")


def test_cadvisor_on_type_without_docker(example_data: dict[str, Any]) -> None:
    example_data["hosts"][4]["cadvisor"] = {"puerto": 9338}
    _assert_invalid(example_data, "no ejecuta Docker")


def test_snmp_v3_incomplete(example_data: dict[str, Any]) -> None:
    del example_data["modulos"]["snmp"]["auths"][0]["clave_priv"]
    _assert_invalid(example_data, "authPriv")


def test_path_outside_site(example_data: dict[str, Any]) -> None:
    example_data["branding"]["logo"] = "../../etc/passwd"
    _assert_invalid(example_data, "fuera del sitio")


@pytest.mark.parametrize("text", ["Sitio ${HOME}", "a{{ 7*7 }}", "x\ny", "<script>", "a`id`"])
def test_dangerous_text(example_data: dict[str, Any], text: str) -> None:
    example_data["branding"]["nombre"] = text
    _assert_invalid(example_data, "String should match pattern")


def test_warnings(example_data: dict[str, Any]) -> None:
    warnings = _validate(example_data).warnings()
    assert any("v2c" in a for a in warnings)
