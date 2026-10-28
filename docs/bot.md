# Bot de consultas por Telegram

El bot de las alertas también responde a comandos en el mismo chat: solo consulta, nunca cambia nada.

| Comando | Qué responde |
|---------|--------------|
| `/estado` | cada host (✅/❌/❔; CPU, RAM y disco si tiene node_exporter) y las alertas activas |
| `/alertas` | alertas disparadas, desde cuándo («desde ?» si la fecha no se puede leer) |
| `/host <nombre o IP>` | ficha de un servidor: CPU, RAM, carga, temperatura, discos, contenedores |
| `/dispositivo <nombre, IP o MAC>` | si está conectado (netinv); si está encendido pero sin hora de última vez, responde «conectado» |
| `/info <nombre, IP o MAC>` | ficha del dispositivo: tipo, ubicación, fabricante, IP, MAC, primera y última vez |
| `/lista [tipo]` | dispositivos encendidos, por tipo |
| `/ayuda` | los comandos |

Solo atiende el chat de `alertas.telegram.chat_id`; lo que llegue de otro chat se descarta sin responder.
Las peticiones HTTP a Prometheus, Grafana y netinv no siguen redirecciones.

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
