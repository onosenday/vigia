"""Alertas de Grafana (provisioning de ficheros): reglas, contact point, política y plantilla con marca.

Se genera en Python y no con Jinja porque las plantillas de notificación de Grafana también usan `{{ }}`.
Grafana interpola `$VAR` en estos ficheros con el entorno del contenedor: los secretos y las direcciones de
correo solo aparecen como `$VAR`, y ningún texto propio lleva `$` (se usa `.Labels`, no `$labels`).
Solo se alerta de infraestructura del site.yaml; los dispositivos de netinv no generan avisos.
"""

from __future__ import annotations

from typing import Any, Literal

import yaml

from vigia import ciclos, tareas
from vigia.model import Site
from vigia.render import Raw, dump_yaml


class EnvRef(str):
    """`$VAR` que interpola Grafana, entre comillas. Ojo: Grafana vuelve a tipar el valor sustituido (un
    número deja de ser texto), así que solo se usa para valores que nunca son numéricos."""

    __slots__ = ()


yaml.SafeDumper.add_representer(
    EnvRef, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", str(v), style='"')
)

PROBE_JOBS = ("web", "servicio", "ping", "dns", "externo")
DATASOURCE_UID = "prometheus"
FS_EXCLUDED = "tmpfs|ramfs|overlay|squashfs|nsfs|devtmpfs|fuse.+"


Gravedad = Literal["critical", "warning", "info"]
Categoria = Literal["incidencia", "mantenimiento"]

CLASIFICACION: dict[str, tuple[Gravedad, Categoria]] = {
    "vigia-caido": ("critical", "incidencia"),
    "vigia-exporter": ("warning", "incidencia"),
    "vigia-impresora-error": ("warning", "incidencia"),
    "vigia-tarea-retrasada": ("warning", "incidencia"),
    "vigia-tarea-error": ("warning", "incidencia"),
    "vigia-tarea-sin-datos": ("warning", "incidencia"),
    "vigia-certificado": ("warning", "mantenimiento"),
    "vigia-disco": ("warning", "mantenimiento"),
    "vigia-consumible": ("warning", "mantenimiento"),
    "vigia-soporte-caducado": ("critical", "mantenimiento"),
    "vigia-soporte-caduca": ("warning", "mantenimiento"),
    "vigia-version-mayor": ("info", "mantenimiento"),
    "vigia-ciclo-desconocido": ("info", "mantenimiento"),
    "vigia-catalogo-viejo": ("info", "mantenimiento"),
    "vigia-seguridad-pendiente": ("warning", "mantenimiento"),
    "vigia-script-anticuado": ("info", "mantenimiento"),
    "vigia-actualizaciones-sin-datos": ("warning", "incidencia"),
}
"""Gravedad y categoría de cada regla, como etiquetas `gravedad` y `categoria`. `incidencia`: algo falla
ahora (`/alertas`); `mantenimiento`: algo pide una acción planificada (`/pendientes`). Los avisos `info` se
repiten con `alertas.repetir_info` en vez de `alertas.repetir`."""


def _rule(uid: str, title: str, expr: str, op: str, value: float, for_: str, summary: str) -> dict[str, Any]:
    gravedad, categoria = CLASIFICACION[uid]
    return {
        "uid": uid,
        "title": title,
        "condition": "B",
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": DATASOURCE_UID,
                "model": {"refId": "A", "expr": expr, "instant": True, "range": False},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "threshold",
                    "expression": "A",
                    "conditions": [{"evaluator": {"type": op, "params": [value]}}],
                },
            },
        ],
        "noDataState": "OK",
        "execErrState": "Error",
        "for": for_,
        "annotations": {"summary": summary},
        "labels": {"vigia": "si", "gravedad": gravedad, "categoria": categoria},
        "isPaused": False,
    }


def rules(s: Site) -> list[dict[str, Any]]:
    u = s.alertas.umbrales
    out = []
    if s.modulos.blackbox and (s.ping or s.servicios or s.web.objetivos or s.dns or s.externos.objetivos):
        jobs = "|".join(PROBE_JOBS)
        out.append(
            _rule(
                "vigia-caido",
                "Caído",
                f'max by (job, nombre, instance) (1 - probe_success{{job=~"{jobs}", alerta!="no"}})',
                "gt",
                0,
                u.caido,
                '{{ index .Labels "nombre" }} no responde ({{ index .Labels "job" }}: '
                '{{ index .Labels "instance" }})',
            )
        )
    if s.modulos.blackbox and (s.web.objetivos or any(o.url for o in s.externos.objetivos)):
        out.append(
            _rule(
                "vigia-certificado",
                "Certificado a punto de caducar",
                "min by (nombre, instance) ("
                '(probe_ssl_earliest_cert_expiry{job=~"web|externo", alerta!="no"} - time()) / 86400)',
                "lt",
                u.certificado_dias,
                "1h",
                '{{ index .Labels "nombre" }}: el certificado caduca pronto'
                "{{ with .Values.A }} (en {{ humanize .Value }} días){{ end }}",
            )
        )
    disk = []
    if any(h.node_exporter for h in s.hosts):
        sel = f'fstype!~"{FS_EXCLUDED}"'
        disk.append(
            f"max by (nombre, mountpoint) (100 * (1 - node_filesystem_avail_bytes{{{sel}}} "
            f"/ node_filesystem_size_bytes{{{sel}}}))"
        )
    if any(h.windows_exporter for h in s.hosts):
        disk.append(
            'max by (nombre, volume) (100 * (1 - windows_logical_disk_free_bytes{volume=~"[A-Z]:"} '
            '/ windows_logical_disk_size_bytes{volume=~"[A-Z]:"}))'
        )
    if disk:
        out.append(
            _rule(
                "vigia-disco",
                "Disco casi lleno",
                " or ".join(disk),
                "gt",
                u.disco_pct,
                u.disco_durante,
                '{{ index .Labels "nombre" }}: '
                '{{ index .Labels "mountpoint" }}{{ index .Labels "volume" }} casi lleno'
                "{{ with .Values.A }} ({{ humanize .Value }} %){{ end }}",
            )
        )
    if s.printers_snmp:
        out += printer_rules(s)
    if s.tareas:
        out += task_rules(s)
    if hay_versiones(s):
        out += support_rules(s)
    if s.modulos.updates_exporter.activo:
        out += updates_rules(s)
    out.append(
        _rule(
            "vigia-exporter",
            "Exporter sin respuesta",
            f'max by (job, nombre, instance) (1 - up{{job!~"{"|".join(PROBE_JOBS)}", alerta!="no"}})',
            "gt",
            0,
            u.exporter_caido,
            'Prometheus no puede leer {{ index .Labels "job" }} de {{ index .Labels "nombre" }} '
            '({{ index .Labels "instance" }})',
        )
    )
    return out


PRINTER_ERRORS = (
    "noPaper",
    "noToner",
    "doorOpen",
    "jammed",
    "offline",
    "serviceRequested",
    "inputTrayMissing",
    "outputTrayMissing",
    "markerSupplyMissing",
    "outputFull",
    "overduePreventMaint",
)
"""Errores de hrPrinterDetectedErrorState que avisan. Los «bajo» de papel y tóner los cubre la regla de
consumibles; `inputTrayEmpty` tampoco avisa: es normal tener una bandeja sin usar."""


def printer_rules(s: Site) -> list[dict[str, Any]]:
    pj = 'job="snmp", tipo="impresora"'
    supplies = (
        f"min by (nombre, prtMarkerSuppliesDescription) (100 * prtMarkerSuppliesLevel{{{pj}, "
        f'prtMarkerSuppliesType!~"waste.*"}} / (prtMarkerSuppliesMaxCapacity{{{pj}}} > 0) >= 0)'
    )
    errors = (
        f"max by (nombre, vigia_impresora_error) (vigia_impresora_error{{{pj}, "
        f'vigia_impresora_error=~"{"|".join(PRINTER_ERRORS)}"}})'
    )
    return [
        _rule(
            "vigia-consumible",
            "Consumible de impresora bajo",
            supplies,
            "lt",
            s.alertas.umbrales.consumible_pct,
            "30m",
            # la descripción acaba en «;SN…» (número de serie del cartucho): fuera del aviso
            '{{ index .Labels "nombre" }}: '
            '{{ reReplaceAll ";.*" "" (index .Labels "prtMarkerSuppliesDescription") }}'
            "{{ with .Values.A }} al {{ humanize .Value }} %{{ end }}",
        ),
        _rule(
            "vigia-impresora-error",
            "Error de impresora",
            errors,
            "gt",
            0,
            "10m",
            '{{ index .Labels "nombre" }}: {{ index .Labels "vigia_impresora_error" }}',
        ),
    ]


def task_rules(s: Site) -> list[dict[str, Any]]:
    tarea = '{{ index .Labels "nombre" }}: la tarea {{ index .Labels "tarea" }}'
    return [
        _rule(
            "vigia-tarea-retrasada",
            "Tarea sin éxito reciente",
            tareas.retraso(s),
            "gt",
            0,
            "5m",
            tarea + " no termina bien desde hace demasiado"
            '{{ with .Values.A }} ({{ printf "%.1f" .Value }} h de más){{ end }}',
        ),
        _rule(
            "vigia-tarea-error",
            "Tarea con error",
            tareas.ultimo_error(s),
            "gt",
            0,
            "0s",
            tarea + " acabó con error en su última ejecución",
        ),
        _rule(
            "vigia-tarea-sin-datos",
            "Tarea sin datos",
            tareas.sin_datos(s),
            "gt",
            0,
            "1h",
            tarea + " no tiene ninguna ejecución correcta registrada (¿script instalado? ¿textfile activo?)",
        ),
    ]


def hay_versiones(s: Site) -> bool:
    """Hay alguna fuente de versiones instaladas (node_os_info o el updates-exporter)."""
    return any(h.node_exporter for h in s.hosts) or s.modulos.updates_exporter.activo


def updates_rules(s: Site) -> list[dict[str, Any]]:
    """Actualizaciones de los hosts que sondea el updates-exporter (docs/actualizaciones.md)."""
    quien = '{{ index .Labels "nombre" }}'
    return [
        _rule(
            "vigia-seguridad-pendiente",
            "Actualizaciones de seguridad pendientes",
            "max by (nombre) (vigia_actualizaciones_seguridad)",
            "gt",
            0,
            s.alertas.umbrales.seguridad_durante,
            quien + ": actualizaciones de seguridad sin aplicar{{ with .Values.A }} ({{ .Value }}){{ end }}",
        ),
        _rule(
            "vigia-script-anticuado",
            "Script de actualizaciones antiguo",
            "max by (nombre) (vigia_updexp_formato)",
            "lt",
            2,
            "1h",
            quien + ": su script del updates-exporter es antiguo y no informa de versiones (reinstálalo)",
        ),
        _rule(
            "vigia-actualizaciones-sin-datos",
            "Actualizaciones sin comprobar",
            "max by (nombre) (1 - vigia_updexp_ok)",
            "gt",
            0,
            "24h",
            quien + ": el updates-exporter no puede consultar sus actualizaciones",
        ),
    ]


def support_rules(s: Site) -> list[dict[str, Any]]:
    """Fin de soporte y versión mayor nueva, con las series de ciclos.reglas (docs/ciclos.md)."""
    u = s.alertas.umbrales
    por = "nombre, producto, producto_nombre, ciclo, version"
    quien = '{{ index .Labels "nombre" }}: {{ index .Labels "producto_nombre" }} {{ index .Labels "ciclo" }}'
    return [
        _rule(
            "vigia-soporte-caducado",
            "Sistema sin soporte",
            f"-max by ({por}) ({ciclos.RESTANTE})",
            "gt",
            0,
            "1h",
            quien + " ya no tiene soporte"
            "{{ with .Values.A }} (desde hace {{ humanize .Value }} días){{ end }}",
        ),
        _rule(
            "vigia-soporte-caduca",
            "Fin de soporte cercano",
            f"max by ({por}) ({ciclos.RESTANTE} >= 0)",
            "lt",
            u.soporte_dias,
            "1h",
            quien + " pierde el soporte pronto{{ with .Values.A }} (en {{ humanize .Value }} días){{ end }}",
        ),
        _rule(
            "vigia-version-mayor",
            "Versión mayor disponible",
            f"max by ({por}, ultimo) ({ciclos.MAYOR})",
            "gt",
            0,
            "1h",
            quien + ': ya existe la {{ index .Labels "ultimo" }}',
        ),
        _rule(
            "vigia-ciclo-desconocido",
            "Versión fuera del catálogo",
            f"max by ({por}) ({ciclos.PRODUCTO_CICLO} unless on (producto, ciclo) {ciclos.INFO})",
            "gt",
            0,
            "1h",
            '{{ index .Labels "nombre" }}: la versión {{ index .Labels "version" }} de '
            '{{ index .Labels "producto_nombre" }} no está en el catálogo de vigia (¿actualizar vigia?)',
        ),
        _rule(
            "vigia-catalogo-viejo",
            "Catálogo de ciclos antiguo",
            f"max by (producto) ((time() - {ciclos.COMPROBADO}) / 86400"
            f" and on (producto) {ciclos.PRODUCTO_CICLO})",
            "gt",
            u.catalogo_dias,
            "1h",
            'el catálogo de {{ index .Labels "producto" }} se comprobó hace '
            "{{ with .Values.A }}{{ humanize .Value }} {{ end }}días: actualiza vigia",
        ),
    ]


def _templates(s: Site) -> str:
    brand = s.branding.nombre  # Text: sin `$`, llaves ni `<>`
    return (
        '{{ define "vigia.titulo" }}[' + brand + "] "
        '{{ if eq .Status "firing" }}Problema{{ else }}Resuelto{{ end }}'
        "{{ with .CommonLabels.nombre }}: {{ . }}{{ end }}{{ end }}\n"
        '{{ define "vigia.mensaje" }}'
        "{{ range .Alerts.Firing }}🔴 {{ .Labels.alertname }}: {{ .Annotations.summary }}\n{{ end }}"
        "{{ range .Alerts.Resolved }}✅ {{ .Labels.alertname }}: {{ .Annotations.summary }}\n{{ end }}"
        "{{ end }}\n"
    )


def _receivers(s: Site) -> list[dict[str, Any]]:
    a = s.alertas
    out: list[dict[str, Any]] = []
    if a.telegram:
        out.append(
            {
                "uid": "vigia-telegram",
                "type": "telegram",
                "settings": {
                    "bottoken": EnvRef(f"${a.telegram.token}"),
                    "chatid": a.telegram.chat_id,
                    "message": '{{ template "vigia.titulo" . }}\n{{ template "vigia.mensaje" . }}',
                },
                "disableResolveMessage": False,
            }
        )
    if a.correo:
        out.append(
            {
                "uid": "vigia-correo",
                "type": "email",
                "settings": {
                    "addresses": EnvRef(f"${a.correo.destinatarios}"),
                    "singleEmail": True,
                    "subject": '{{ template "vigia.titulo" . }}',
                    "message": '{{ template "vigia.mensaje" . }}',
                },
                "disableResolveMessage": False,
            }
        )
    return out


def alerting(s: Site, header: Raw) -> str:
    """Fichero único de grafana-provisioning/alerting/ (vacío de alertas si no hay reglas)."""
    a = s.alertas
    data = {
        "apiVersion": 1,
        "groups": [
            {
                "orgId": 1,
                "name": "vigia",
                "folder": s.branding.carpeta,
                "interval": "1m",
                "rules": rules(s),
            }
        ],
        "templates": [{"orgId": 1, "name": "vigia", "template": _templates(s)}],
        "contactPoints": [{"orgId": 1, "name": "vigia", "receivers": _receivers(s)}],
        "policies": [
            {
                "orgId": 1,
                "receiver": "vigia",
                "group_by": ["nombre"],
                "group_wait": "30s",
                "group_interval": "5m",
                "repeat_interval": a.repetir,
                "routes": [
                    {
                        "receiver": "vigia",
                        "object_matchers": [["gravedad", "=", "info"]],
                        "repeat_interval": a.repetir_info,
                    }
                ],
            }
        ],
    }
    return dump_yaml(data, header)


def smtp_env(s: Site) -> list[str]:
    """Variables GF_SMTP_* del contenedor de Grafana (los valores sensibles, como ${VAR} de compose)."""
    c = s.alertas.correo
    if not (s.alertas.activo and c):
        return []
    return [
        "GF_SMTP_ENABLED=true",
        f"GF_SMTP_HOST={c.smtp}",
        f"GF_SMTP_USER=${{{c.usuario}}}",
        f"GF_SMTP_PASSWORD=${{{c.clave}}}",
        f"GF_SMTP_FROM_ADDRESS=${{{c.remitente}}}",
        f"GF_SMTP_FROM_NAME=Alertas {s.branding.nombre}",
    ]
