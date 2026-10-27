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
  umbrales: {caido: 5m, exporter_caido: 5m, certificado_dias: 15, disco_pct: 90, disco_durante: 15m}
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

Los avisos se agrupan por `nombre`: si un servidor se cae, la sonda y su exporter llegan en el mismo mensaje.
Lo que se apaga a propósito se marca con `alerta: false` en su entrada de `ping`, `servicios` o
`web.objetivos`: sigue en los paneles, pero no avisa. Solo se alerta de la infraestructura de `site.yaml`;
los dispositivos que descubre netinv (móviles, televisores) nunca generan avisos.

## Telegram

1. En Telegram, habla con **@BotFather** → `/newbot` → nombre y usuario del bot. Un bot **solo para alertas**
   de este sitio. Guarda el token en el fichero de entorno (`ALERTAS_TELEGRAM_TOKEN`).
2. Escríbele cualquier cosa al bot (o añádelo al grupo que recibirá los avisos).
3. Saca el chat id tú mismo (el token va en la URL: no lo pegues en ningún sitio):
   `curl -s https://api.telegram.org/bot<TOKEN>/getUpdates` → `message.chat.id` (en grupos, negativo).
   Ponlo en `alertas.telegram.chat_id` de `site.yaml`, entre comillas.
4. Rotación: en @BotFather, `/revoke` sobre el bot, nuevo token al fichero de entorno y redesplegar.

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

Prueba: en Grafana, *Alerting ▸ Contact points ▸ vigia ▸ Test*. Los cambios en reglas o contact point se hacen
en `site.yaml`; en la UI aparecen como provisionados y no se pueden editar.
