# Alertas (Telegram y correo)

vigia provisiona en Grafana cuatro reglas, un contact point `vigia` (Telegram, correo o los dos), la política
de avisos y una plantilla con la marca del sitio (`[Oficina] Problema: Nodo 1`). Todo sale de `site.yaml`:

```yaml
alertas:
  activo: true
  telegram: {token: ALERTAS_TELEGRAM_TOKEN, chat_id: "-1001234567890"}
  correo:
    smtp: smtp.gmail.com:587
    usuario: ALERTAS_SMTP_USUARIO
    clave: ALERTAS_SMTP_CLAVE          # contraseña de aplicación, no la de la cuenta
    remitente: ALERTAS_SMTP_REMITENTE
    destinatarios: ALERTAS_CORREO_DESTINO   # varias, separadas por ;
  umbrales: {caido: 5m, exporter_caido: 5m, certificado_dias: 15, disco_pct: 90, disco_durante: 15m,
             consumible_pct: 15}
  repetir: 12h
```

Todos los valores son **nombres de variables** del fichero de entorno del sitio, salvo `chat_id`. Las
direcciones de correo también van en el entorno: son datos personales y no van en `site.yaml`.
`chat_id` va literal porque Grafana vuelve a tipar lo que interpola (`$VAR`) y un número no le sirve como chat
id. No es secreto (sin el token no sirve de nada); usa un **grupo** para que no sea el id de una persona.

## Reglas

| Regla | Qué vigila | Cuándo avisa |
|-------|------------|--------------|
| Caído | sondas ping, servicio, web y DNS | `probe_success = 0` durante `caido` |
| Certificado a punto de caducar | webs por nombre | quedan menos de `certificado_dias` |
| Disco casi lleno | node_exporter y windows_exporter | por encima de `disco_pct` durante `disco_durante` |
| Exporter sin respuesta | cualquier `up` que no sea una sonda | `up = 0` durante `exporter_caido` |
| Consumible de impresora bajo | tóner, tinta, tambor… de las impresoras con `snmp` (no los depósitos de residuos) | por debajo de `consumible_pct` durante 30 min |
| Error de impresora | sin papel o tóner, puerta abierta, atasco, desconectada, servicio, bandeja o consumible ausente, salida llena, mantenimiento vencido | activo durante 10 min |

Los avisos se agrupan por `nombre`: si un servidor se cae, la sonda y su exporter llegan en el mismo mensaje.
Lo que se apaga (o se duerme, como muchas impresoras) se marca con `alerta: false` en su entrada de `ping`, `servicios` o
`web.objetivos`: sigue en los paneles, pero no avisa (en un ping, tampoco avisa si su exporter calla). Solo se alerta de la infraestructura de `site.yaml`;
los dispositivos que descubre netinv (móviles, televisores) nunca generan avisos.

## Telegram

1. En Telegram, habla con **@BotFather** → `/newbot` → nombre y usuario del bot. Un bot **solo para alertas**
   de este sitio. Guarda el token en el fichero de entorno (`ALERTAS_TELEGRAM_TOKEN`).
2. Crea el grupo que recibirá los avisos (ver abajo) y añade el bot. Para avisos solo a ti, basta con
   escribirle algo al bot en privado.
3. Saca el chat id tú mismo (el token va en la URL: no lo pegues en ningún sitio):
   `curl -s https://api.telegram.org/bot<TOKEN>/getUpdates` → `chat.id` del grupo (negativo; en privado,
   positivo). Ponlo en `alertas.telegram.chat_id` de `site.yaml`, entre comillas, y redespliega.
4. Rotación: en @BotFather, `/revoke` sobre el bot, nuevo token al fichero de entorno y redesplegar.

### Grupo privado para compartir los avisos

Para que lleguen a varias personas, el destino es un grupo privado, no el bot: el bot solo envía al `chat_id`
configurado, así que quien lo encuentre y le escriba no recibe nada.

1. **Crear el grupo**: *Nuevo grupo* → nombre (p. ej. «Alertas <sitio>») → añadir el bot y a las personas.
   Un grupo nuevo es privado: sin nombre público no aparece en búsquedas.
2. **Cerrar la entrada**: en *Editar ▸ Permisos*, quitar a los miembros «Añadir miembros». Si se invita por
   enlace, crearlo con «Solicitar aprobación del administrador».
3. **chat id**: el del grupo (paso 3 de arriba). Ojo: si Telegram convierte el grupo en **supergrupo** (al
   activar el historial visible para nuevos miembros, enlaces con aprobación, más de 200 miembros…), el id
   cambia a uno que empieza por `-100` y los avisos dejan de llegar: volver a sacar el id y redesplegar.
4. **Cerrar el bot**: en @BotFather → `/mybots` → el bot → *Bot Settings* → *Allow Groups?* → **Turn groups
   off**, después de añadirlo al grupo. Sigue en ese grupo, pero nadie puede meterlo en otros.
5. **Modo privacidad** (*Group Privacy*): dejarlo **activado**, que es lo normal. En la lista de miembros el
   bot sale como «sin acceso a los mensajes»: no lee la conversación del grupo, solo los comandos (`/…`) y
   las menciones. Para enviar avisos no necesita más.
6. **Altas y bajas**: se añade o se echa a la persona del grupo; no hay que tocar `site.yaml`.

El bot de alertas no se comparte con nadie más que a través del grupo, y el token no sale del fichero de
entorno. Si más adelante el bot ha de **responder** a consultas, hace falta un programa que lea sus mensajes:
que atienda solo a ids de Telegram autorizados, que solo consulte (nada que cambie sistemas) y que sea el único
lector del bot (a partir de ahí `getUpdates` a mano deja de servir para sacar ids).

## Correo con Gmail

La cuenta necesita verificación en dos pasos; en *Cuenta de Google ▸ Seguridad ▸ Contraseñas de aplicaciones*
se crea una para «vigia» y va en `ALERTAS_SMTP_CLAVE`. `smtp: smtp.gmail.com:587` (STARTTLS).
Si una contraseña lleva `$`, escríbela como `$$` en el fichero de entorno (compose interpola `$`).

## Despliegue

- Adaptadores `compose` y `synology`: vigia escribe las variables en el fichero de entorno del stack
  (permisos 600).
- **OpenMediaVault**: vigia no toca el campo *Environment* del stack. Añade allí las variables (en la UI,
  *Services ▸ Compose ▸ Files ▸ <stack> ▸ Environment*) **antes** de desplegar. `vigia deploy` comprueba que
  están (solo los nombres) y aborta sin tocar nada si falta alguna: con un token vacío Grafana no provisiona
  las alertas y **se para**.

Prueba: en Grafana, *Alerting ▸ Contact points ▸ vigia ▸ Test*. Por API (Grafana 12 o posterior):
`POST /apis/notifications.alerting.grafana.app/v1beta1/namespaces/default/receivers/<uid>/test` con la
integración (`uid`, `type`, `settings`, `secureFields`) y una alerta de ejemplo; el endpoint antiguo
`/api/alertmanager/grafana/config/api/v1/receivers/test` ya no existe. Los cambios en reglas o contact point se hacen
en `site.yaml`; en la UI aparecen como provisionados y no se pueden editar.
