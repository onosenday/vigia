from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from vigia.model import Site


def _valida(d: dict[str, Any]) -> Site:
    return Site.model_validate(d)


def _falla(d: dict[str, Any], texto: str) -> None:
    with pytest.raises(ValidationError) as e:
        _valida(d)
    assert texto in str(e.value)


def test_ejemplo_valido(datos_ejemplo: dict[str, Any]) -> None:
    s = _valida(datos_ejemplo)
    assert s.monitor_host.id == "nodo1"
    assert [p[1] for p in s.ping_resuelto()][:2] == ["router", "VIP DNS"]


def test_campo_desconocido(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["hosts"][1]["password"] = "x"
    _falla(datos_ejemplo, "Extra inputs are not permitted")


def test_ip_fuera_de_subred(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["hosts"][1]["ip"] = "192.0.2.10"
    _falla(datos_ejemplo, "fuera de la subred")


def test_ids_repetidos(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["hosts"][2]["id"] = "nodo1"
    _falla(datos_ejemplo, "ids repetidos")


def test_netinv_sin_autorizacion(datos_ejemplo: dict[str, Any]) -> None:
    del datos_ejemplo["modulos"]["netinv"]["autorizacion"]
    _falla(datos_ejemplo, "autorizacion")


def test_secreto_solo_por_nombre(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["modulos"]["pihole_exporter"]["secreto"] = "mi clave secreta"
    _falla(datos_ejemplo, "String should match pattern")


def test_url_con_credenciales(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["servicios"][0]["url"] = "http://admin:clave@10.99.0.11:8000"
    _falla(datos_ejemplo, "usuario ni contraseña")


def test_hiberna_sin_200(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["servicios"][1]["espera_200"] = False
    _falla(datos_ejemplo, "hiberna")


def test_cadvisor_en_tipo_sin_docker(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["hosts"][4]["cadvisor"] = {"puerto": 9338}
    _falla(datos_ejemplo, "no ejecuta Docker")


def test_snmp_v3_incompleto(datos_ejemplo: dict[str, Any]) -> None:
    del datos_ejemplo["modulos"]["snmp"]["auths"][0]["clave_priv"]
    _falla(datos_ejemplo, "authPriv")


def test_ruta_fuera_del_sitio(datos_ejemplo: dict[str, Any]) -> None:
    datos_ejemplo["branding"]["logo"] = "../../etc/passwd"
    _falla(datos_ejemplo, "fuera del sitio")


@pytest.mark.parametrize("nombre", ["Sitio ${HOME}", "a{{ 7*7 }}", "x\ny", "<script>", "a`id`"])
def test_texto_peligroso(datos_ejemplo: dict[str, Any], nombre: str) -> None:
    datos_ejemplo["branding"]["nombre"] = nombre
    _falla(datos_ejemplo, "String should match pattern")


def test_avisos(datos_ejemplo: dict[str, Any]) -> None:
    avisos = _valida(datos_ejemplo).avisos()
    assert any("v2c" in a for a in avisos)
