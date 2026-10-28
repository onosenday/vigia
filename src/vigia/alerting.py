"""Alertas de Grafana (provisioning de ficheros): reglas, contact point, política y plantilla con marca.

Se genera en Python y no con Jinja porque las plantillas de notificación de Grafana también usan `{{ }}`.
Grafana interpola `$VAR` en estos ficheros con el entorno del contenedor: los secretos y las direcciones de
correo solo aparecen como `$VAR`, y ningún texto propio lleva `$` (se usa `.Labels`, no `$labels`).
Solo se alerta de infraestructura del site.yaml; los dispositivos de netinv no generan avisos.
"""

from __future__ import annotations

from typing import Any

import yaml

from vigia import tareas
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


def _rule(uid: str, title: str, expr: str, op: str, value: float, for_: str, summary: str) -> dict[str, Any]:
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
        "labels": {"vigia": "si"},
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
