# Bot de consultas por Telegram

El bot de las alertas también responde a comandos en el mismo chat: solo consulta, nunca cambia nada.

| Comando | Qué responde |
|---------|--------------|
| `/estado` | cada host (✅/❌/❔; CPU, RAM y disco si tiene node_exporter) y las alertas activas |
| `/alertas` | alertas disparadas, desde cuándo («desde ?» si la fecha no se puede leer) |
| `/pendientes` | mantenimiento: certificados, consumibles, discos, fin de soporte, versiones mayores, actualizaciones e imágenes nuevas (ver abajo) |
| `/host <nombre o IP>` | ficha de un servidor: CPU, RAM, carga, temperatura, discos, contenedores y versión y soporte de su sistema |
| `/dispositivo <nombre, IP o MAC>` | si está conectado; si está encendido pero sin hora de última vez, responde «conectado» |
| `/info <nombre, IP o MAC>` | ficha del dispositivo: tipo, ubicación, fabricante, IP, MAC, primera y última vez |
| `/lista [tipo]` | dispositivos encendidos, por tipo |
| `/ayuda` | los comandos |

Solo atiende el chat de `alertas.telegram.chat_id`; lo que llegue de otro chat se descarta sin responder.
Los dispositivos salen de las métricas de netinv en Prometheus. Las peticiones HTTP (Prometheus, Grafana y
Telegram) no siguen redirecciones: el token de Grafana no viaja a otro host.

## /pendientes

Lo que pide una acción planificada; lo que falla ahora está en `/alertas`. Sale de Prometheus con las mismas
expresiones que las alertas, agrupado por categoría y en el orden de `hosts:`:

```
🔐 Certificados       web-1: caduca en 9 días ⚠
🖨 Consumibles        Impresora: Tóner negro 8% ⚠ · Tóner cian 19% próximo
💽 Discos             nas-1 /srv 92% ⚠
🧭 Soporte            srv-1 · PostgreSQL 14 (bd): pierde el soporte en 14 días ⚠
⬆ Versiones mayores  srv-2 · Debian 11 → 13
🛡 Actualizaciones    srv-1: 12 (3 de seguridad) ⚠
🐳 Imágenes           srv-1 · grafana 13.0.2 → 13.3.0
```

⚠ marca lo que ya pasa el umbral de su alerta; «próximo», lo que está dentro del margen de
`modulos.bot.proximo` (más amplio que los umbrales):

```yaml
modulos:
  bot:
    proximo: {certificado_dias: 45, consumible_pct: 30, disco_pct: 80, soporte_dias: 180}   # por defecto
```

Las versiones mayores, las actualizaciones y las imágenes nuevas salen todas (también las que watchtower
aplicará: los avisos de imágenes son solo para lo que queda fuera de él, ver [imagenes.md](imagenes.md)).

## Activarlo

1. Alertas por Telegram configuradas (ver [alertas.md](alertas.md)). En @BotFather, el bot con *Group
   Privacy* activado (en el grupo solo recibe `/comandos`) y *Allow Groups* desactivado.
2. Token de Grafana de solo lectura: *Administración ▸ Usuarios y acceso ▸ Cuentas de servicio ▸ Añadir*,
   rol **Viewer**, y *Añadir token*. Guárdalo en el fichero de entorno del sitio (`BOT_GRAFANA_TOKEN`) y, en
   OMV, también en el *Environment* del stack del monitor (`vigia deploy` aborta si falta).
3. En `site.yaml`:

   ```yaml
   modulos:
     bot: {activo: true, grafana_token: BOT_GRAFANA_TOKEN}   # zona: Europe/Madrid, puerto: 9466
   ```

   `zona` ha de ser un nombre de la base de datos IANA (`Europe/Madrid`, `America/Bogota`…); otro valor
   no valida.
4. `uv run vigia deploy monitor` (diff) y, si está bien, `--yes`.
5. Prueba: `/estado` en el grupo; un mensaje privado al bot no debe recibir respuesta.

El código del bot va dentro de su imagen (`vigia-bot:local`). `vigia deploy` la reconstruye
(`up -d --build`) cuando la unidad tiene `dir`. En OMV sin `dir`, el *Up* de la UI no reconstruye: tras
actualizar vigia hay que pulsar *Build* o *Pull* en el stack. El `config.json` va montado y se recoge al
reiniciar.

## Salud

Prometheus lee `/metrics` del bot (job `bot`): `vigia_bot_up` y `vigia_bot_mensajes_total{resultado}`
(atendido, descartado, limitado, error). Si el bot cae, avisa la regla «Exporter sin respuesta».
