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
    _assert_invalid(example_data, "fuera de las subredes")


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


def test_snmp_v3_protocolo_desconocido(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["snmp"]["auths"][0]["protocolo_auth"] = "SHA1"
    _assert_invalid(example_data, "protocolo_auth")


def test_snmp_protocolos_en_v2c(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["snmp"]["auths"][2]["protocolo_auth"] = "SHA"
    _assert_invalid(example_data, "solo valen para v3")


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


@pytest.mark.parametrize("rango", [">=0.1,<0.2", ">=9.0", "==0.0.1"])
def test_version_fuera_de_rango_no_carga(example_data: dict[str, Any], rango: str) -> None:
    example_data["vigia"] = rango
    with pytest.raises(ValidationError, match="está instalada"):
        Site.model_validate(example_data)


def test_rango_no_valido(example_data: dict[str, Any]) -> None:
    example_data["vigia"] = ">=0.2,,<<0.3"
    with pytest.raises(ValidationError, match="no válido"):
        Site.model_validate(example_data)


def test_rango_de_la_serie() -> None:
    from vigia.newsite import version_range

    assert version_range("0.2.0") == ">=0.2,<0.3"
    assert version_range("1.10.3") == ">=1.10,<1.11"


def test_subredes_extra(example_data: dict[str, Any]) -> None:
    example_data["red"]["subredes_extra"] = [{"red": "10.98.0.0/24", "nombre": "Planta 2"}]
    example_data["hosts"].append({"id": "nodo-p2", "tipo": "linux", "ip": "10.98.0.5"})
    s = Site.model_validate(example_data)
    assert s.red.network_of("10.98.0.5") == "10.98.0.0/24"
    assert [c for c, _ in s.red.networks] == ["10.99.0.0/24", "10.98.0.0/24"]


def test_subredes_solapadas(example_data: dict[str, Any]) -> None:
    example_data["red"]["subredes_extra"] = [{"red": "10.99.0.128/25", "nombre": "Solapada"}]
    _assert_invalid(example_data, "solapadas")


def test_bot_inactivo_por_defecto(example_data: dict[str, Any]) -> None:
    example_data["modulos"].pop("bot", None)
    assert not _validate(example_data).modulos.bot.activo


def test_bot_sin_telegram(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN"}
    del example_data["alertas"]["telegram"]
    _assert_invalid(example_data, "bot activo sin alertas por Telegram")


def test_bot_sin_token_de_grafana(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True}
    _assert_invalid(example_data, "bot activo sin `grafana_token`")


def test_bot_zona_no_valida(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN", "zona": "../etc"}
    _assert_invalid(example_data, "String should match pattern")


def test_bot_valido(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN"}
    b = _validate(example_data).modulos.bot
    assert (b.zona, b.puerto) == ("Europe/Madrid", 9466)


def test_bot_zona_inexistente(example_data: dict[str, Any]) -> None:
    bot = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN", "zona": "Europe/Madri"}
    example_data["modulos"]["bot"] = bot
    _assert_invalid(example_data, "zona horaria desconocida")


def test_bot_zona_que_es_una_carpeta(example_data: dict[str, Any]) -> None:
    bot = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN", "zona": "America"}
    example_data["modulos"]["bot"] = bot
    _assert_invalid(example_data, "zona horaria desconocida")


def test_bot_zona_utc(example_data: dict[str, Any]) -> None:
    example_data["modulos"]["bot"] = {"activo": True, "grafana_token": "BOT_GRAFANA_TOKEN", "zona": "UTC"}
    assert _validate(example_data).modulos.bot.zona == "UTC"


def _con_tareas(d: dict[str, Any]) -> dict[str, Any]:
    d["hosts"][2]["node_exporter"]["textfile"] = True  # nodo2
    d["tareas"] = [{"nombre": "copias-bd", "host": "nodo2", "max_horas": 26}]
    return d


def test_tareas_validas(example_data: dict[str, Any]) -> None:
    s = _validate(_con_tareas(example_data))
    assert s.tareas[0].max_horas == 26
    assert s.get_host("nodo2").node_exporter.textfile  # type: ignore[union-attr]


def test_textfile_solo_en_node_exporter(example_data: dict[str, Any]) -> None:
    example_data["hosts"][4]["windows_exporter"]["textfile"] = True  # puesto1
    _assert_invalid(example_data, "Extra inputs are not permitted")


def test_tarea_host_desconocido(example_data: dict[str, Any]) -> None:
    _con_tareas(example_data)["tareas"][0]["host"] = "nodo9"
    _assert_invalid(example_data, "tarea copias-bd: host desconocido")


def test_tarea_host_sin_textfile(example_data: dict[str, Any]) -> None:
    _con_tareas(example_data)["tareas"][0]["host"] = "nodo1"
    _assert_invalid(example_data, "tarea copias-bd: nodo1 no tiene node_exporter con `textfile: true`")


def test_tareas_repetidas(example_data: dict[str, Any]) -> None:
    d = _con_tareas(example_data)
    d["tareas"].append(dict(d["tareas"][0]))
    _assert_invalid(d, "tareas repetidas")


@pytest.mark.parametrize("horas", [0, 745])
def test_tarea_max_horas_fuera_de_rango(example_data: dict[str, Any], horas: int) -> None:
    _con_tareas(example_data)["tareas"][0]["max_horas"] = horas
    _assert_invalid(example_data, "max_horas")
