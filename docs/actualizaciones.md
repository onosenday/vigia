# Actualizaciones y versiones de los hosts (updates-exporter)

El updates-exporter es un contenedor que entra por SSH en cada host con `actualizaciones`, recoge cuántas
actualizaciones tiene pendientes y qué versión de sistema y de producto lleva, y lo publica de dos formas:

- `/updates.json`: el agregado por host (lo leen, por ejemplo, los widgets de Homepage).
- `/metrics.txt`: lo mismo para Prometheus (job `actualizaciones`).

## En el sitio

```yaml
hosts:
  - id: nas-1
    tipo: omv
    actualizaciones: {}                       # usuario updexp por defecto
  - id: nas-2
    tipo: synology
    actualizaciones: {intervalo_min: 21600}   # como mucho cada 6 h (discos que hibernan)
modulos:
  updates_exporter:
    activo: true
    host: srv-1                # dónde corre el contenedor
    claves: /ruta/en/srv-1/keys   # carpeta con la clave privada dedicada (id_ed25519), nunca en git
```

## En cada host

Cada host ejecuta un script fijo: el *forced-command* de la clave dedicada. Ese script es lo único que
puede hacer el exporter allí. Está en `updates-exporter/host-scripts/` de lo generado:

| Script | Hosts | Requiere sudo para |
|--------|-------|--------------------|
| `apt-updates-json.sh` | Debian, Raspberry Pi OS, OMV, Proxmox VE | `/usr/bin/apt-get update` |
| `syno-updates-json.sh` | Synology DSM | `/usr/syno/bin/synoupgrade` |

Instalación en un host Debian/OMV (como root). `<PUBKEY>` es la clave pública dedicada:

```sh
useradd -m -s /bin/sh updexp
install -m 0755 apt-updates-json.sh /usr/local/bin/apt-updates-json.sh
install -d -m 0700 -o updexp -g updexp /home/updexp/.ssh
echo 'command="/usr/local/bin/apt-updates-json.sh",restrict <PUBKEY>' > /home/updexp/.ssh/authorized_keys
chown updexp:updexp /home/updexp/.ssh/authorized_keys && chmod 600 /home/updexp/.ssh/authorized_keys
echo 'updexp ALL=(root) NOPASSWD: /usr/bin/apt-get update' > /etc/sudoers.d/updexp && chmod 440 /etc/sudoers.d/updexp
usermod -aG _ssh updexp   # solo en OMV, que limita el SSH al grupo _ssh
```

En DSM, lo mismo con `syno-updates-json.sh`: el home está en `/var/services/homes/updexp` y necesita permisos
`0711`. Además, DSM puede borrar estos ficheros al actualizarse.

Para comprobarlo desde el host del exporter: `ssh -i keys/id_ed25519 updexp@<host> x` devuelve el JSON.

### Formato v2 y cómo actualizar los scripts

Desde vigia 0.5 los scripts emiten el formato v2. Añade `os_id`, `os_version` y `productos` (OMV, Proxmox VE,
DSM, con su versión) sin quitar lo que había, así que lo que lee `updates.json` sigue funcionando. Un host
con el script v1 sigue informando de sus actualizaciones, pero no de sus versiones. La alerta «Script de
actualizaciones antiguo» lo señala. Para pasar a v2 basta con volver a instalar el script:

```sh
install -m 0755 apt-updates-json.sh /usr/local/bin/apt-updates-json.sh
```

## Métricas

| Serie | Qué es |
|-------|--------|
| `vigia_updexp_ok{nombre}` | 1 si el host respondió (o hay caché dentro de su `intervalo_min`) |
| `vigia_updexp_formato{nombre}` | Versión del formato del script del host |
| `vigia_actualizaciones_pendientes{nombre}` | Paquetes pendientes (en DSM, 1 si hay actualización) |
| `vigia_actualizaciones_seguridad{nombre}` | De ellos, de seguridad (solo apt) |
| `vigia_producto_info{nombre, producto, version}` | Producto y versión: la fuente de OMV, Proxmox y DSM en [ciclos.md](ciclos.md) |

## Alertas

| Regla | Cuándo avisa |
|-------|--------------|
| Actualizaciones de seguridad pendientes | hay alguna sin aplicar durante `umbrales.seguridad_durante` (72h) |
| Script de actualizaciones antiguo | el host aún tiene el script v1 |
| Actualizaciones sin comprobar | el exporter no puede consultar el host durante 24 h |
