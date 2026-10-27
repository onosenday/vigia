---
name: vigia
description: Operar la monitorización de una red con vigia (Prometheus, Grafana, blackbox, SNMP, inventario) desde el site.yaml del sitio - añadir o quitar equipos y servicios, cambiar branding o puertos, desplegar con diff previo, copia y rollback, y diagnosticar. Usar al trabajar en un repo de sitio de vigia (tiene site.yaml y pyproject con la dependencia vigia) o cuando el usuario pida vigilar algo nuevo en su red.
---

# vigia: operar un sitio

Un **sitio** es una red vigilada. Su repo tiene `site.yaml` (fuente de verdad), `assets/` (logo, favicon,
CA interna), `bridges.yaml`, opcionalmente `devices.yaml`, y un fichero de entorno con los secretos (nunca
versionado; sus nombres en `.env.example`). Todo lo que corre en los hosts **se genera** desde `site.yaml`:
nunca se edita a mano en el host ni en `build/`.

## Flujo de cualquier cambio

1. Editar `site.yaml` (y `assets/` si toca).
2. `uv run vigia validate`: errores y avisos (puertos por defecto, SNMP v2c, nmap…). Ningún error se ignora.
3. `uv run vigia units`: qué unidades hay (`monitor`, `agentes:<host>`, `updates`).
4. `uv run vigia deploy <unidad>` **sin `--yes`**: muestra el diff contra lo que corre en el host. Revisar que
   solo cambia lo esperado.
5. Presentar al usuario el diff resumido, el impacto (reinicios, cortes) y el rollback, y **esperar su OK**.
6. `uv run vigia deploy <unidad> --yes`: copia comprobada en `/root/vigia-backups/<stack>/<fecha>/`,
   sincroniza, `up`, reinicia lo que relee configuración.
7. Verificar: el mismo `deploy` sin `--yes` debe dar **0 diferencias**; objetivos `up` por job iguales que
   antes (consulta a Prometheus `sum by (job) (up)`), Grafana `/api/health`, lo caído es lo que ya lo estaba.
8. Commit del repo del sitio con lo desplegado.

Rollback: `uv run vigia rollback <unidad>` (muestra el script) y con `--yes` lo ejecuta.

Si se cambió el propio paquete vigia en local: `uv sync --reinstall-package vigia` en el repo del sitio.

## Reglas que no se saltan

- **Secretos**: en `site.yaml` solo nombres de variables (`secreto: PIHOLE_PASSWORDS`). No leer el fichero de
  entorno ni mostrar sus valores; si falta uno, pedírselo al usuario. vigia aborta si un valor secreto aparece
  en lo generado.
- **Descubrimiento activo** (netinv con arp-scan/nmap, escaneos de puertos): solo con `autorizacion`
  (responsable, fecha, referencia) en `site.yaml`. En redes ajenas, por escrito del responsable de la red.
- **Datos de personas**: nombres de dispositivos o de usuarios no van a alertas, issues ni servicios externos.
  Si el sitio trata datos sensibles (salud, clientes), su `CLAUDE.md` manda.
- **Equipos cuyos discos hibernan** (`discos_hibernan: true`): solo sondas a URLs que respondan **200**
  (`espera_200: true`; un 403/404 suele escribir en un log y despierta los discos) y consultas espaciadas
  (`actualizaciones.intervalo_min`). Antes de añadir una sonda, comprobar el código con lo que ya mide
  Prometheus, no lanzando peticiones nuevas.
- **Puertos expuestos**: nunca el puerto por defecto de un servicio (Grafana 3000, Prometheus 9090…).
- Cambios en hosts siempre con OK explícito para esa operación; un OK no vale para la siguiente.

## Añadir cosas

- **Equipo**: entrada en `hosts:` con `tipo` (perfil: linux, omv, raspbian, proxmox, synology, qnap, truenas,
  windows, router, switch, ap, impresora, sai, otro). El orden de `hosts:` es el orden en los paneles.
  - Linux/OMV/Proxmox: `node_exporter: {puerto: 9100}` (`gestion: externo` si ya está instalado).
  - Windows: `windows_exporter: {puerto: 9182, gestion: externo}` (se instala aparte, MSI oficial).
  - NAS, switches, impresoras, SAI: `snmp: {auth: <nombre>}` y la autenticación en `modulos.snmp.auths`
    (v3 authPriv por defecto; v2c solo si el equipo no admite v3).
  - Con Docker: `cadvisor: {puerto: …}`; si no es el host del monitor, `ssh:` y `deploy:` para sus agentes.
  - Para vigilarlo por ping: añadirlo a `ping:` (`- host: <id>`).
- **Servicio por IP:puerto**: `servicios:` con `url`, `nombre`, `host` (agrupa en paneles).
- **Web por nombre** (tras proxy inverso): `web.objetivos`; con CA interna, `web.ca: assets/ca.crt`.
- **Algo que se apaga a propósito**: `alerta: false` en su entrada de `ping`, `servicios` o `web.objetivos`
  (sigue en los paneles, no avisa).
- **Alertas**: bloque `alertas` (Telegram y correo; solo nombres de variables, también las direcciones de
  correo). Guía en `docs/alertas.md` del paquete. En OMV, las variables nuevas las añade el usuario al
  *Environment* del stack en la UI antes del deploy. Probar con *Contact points ▸ vigia ▸ Test*.
- **Redes Docker nuevas** en un host: `uv run vigia bridges` (relee y reescribe `bridges.yaml`).

## Lo aprendido sobre las plataformas

- **OpenMediaVault**: los stacks de Compose viven en `/etc/openmediavault/config.xml` (`omv-rpc Compose
  getFile/setFile`); los ficheros de la carpeta del stack se regeneran desde ahí. vigia usa `setFile`
  conservando `env` y `override`; un stack creado por CLI no aparece en la UI.
- **Carpetas montadas en contenedores**: se sincronizan **por dentro** (vaciar y copiar), nunca borrando y
  recreando la carpeta: el bind mount apunta al inodo y el contenedor se quedaría con la vieja.
- **Synology DSM**: docker en `/usr/local/bin/docker` y con sudo; el sistema (md0) suele estar en RAID1 sobre
  todos los discos, así que cualquier escritura de log los despierta.
- **sudo remoto**: la contraseña va por stdin (`sudo -k -S`), nunca en argv. `sshpass -e` (variable
  `SSHPASS`) si el host no admite clave.
- **Grafana OSS**: el white-labeling completo (título de la pestaña, pantalla de login) es de Enterprise. vigia
  pone nombre de instancia, tema, portada, logo y favicon (montados sobre ficheros de la imagen: por eso la
  versión va fija y Grafana fuera de watchtower) y el nombre de la organización (`vigia grafana-brand`).
- **Prometheus**: tras cambiar objetivos, una consulta instantánea puede seguir mostrando el viejo durante 5
  min (ventana de lookback); para saber qué se sondea de verdad, `/api/v1/targets`.
- **Versiones**: `monitor.imagenes` con etiqueta fija. Subir una versión es un cambio más (diff, OK,
  verificación del branding).

## Diagnóstico rápido

- `vigia deploy <unidad>` sin `--yes` ≠ 0 diferencias → alguien tocó el host a mano o falta desplegar.
- Objetivo `down` nuevo → ¿cambió el puerto o la ruta? ¿un firewall? Comparar con `probe_http_status_code`.
- Paneles vacíos para un host → ¿el `nombre` del host coincide con la etiqueta `nombre` de sus métricas?
