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

## Decisiones en /pendientes

Cuando el sitio ya ha decidido no hacer algo (quedarse en una LTS, una etiqueta más concreta de la misma
versión, un fin de soporte lejano), esa línea no pide acción. Se declara en un fichero y `/pendientes` la pasa a un
bloque «Decidido» con el motivo: arriba queda solo lo que pide acción y nada desaparece sin verse.

El fichero es opcional, va en la carpeta del sitio y se declara con la ruta relativa a `site.yaml`:

```yaml
modulos:
  bot: {activo: true, grafana_token: BOT_GRAFANA_TOKEN, decisiones: decisiones.yaml}
```

`decisiones.yaml` es una lista:

```yaml
- seccion: imagenes            # soporte | versiones | imagenes | digest
  host: host1
  objeto: prometheus           # contenedor (imagenes, digest) o producto (soporte, versiones)
  ofrecido: v3.15.1            # lo descartado; si lo ofrecido cambia, la decisión deja de aplicar
  motivo: "LTS 3.13; la rama 3.15 pierde soporte antes"
  ref: TICKET-1                # opcional: issue o nota donde se tomó
- seccion: soporte
  host: host1
  objeto: grafana
  revisar: 2026-12-15          # sin `ofrecido`: vuelve a pendiente en esa fecha
  motivo: "soporte hasta 01-2027; subir cuando haya versión nueva"
```

- Obligatorios: `seccion`, `host`, `objeto` y `motivo`, y al menos uno de `ofrecido` o `revisar`.
- `host` es un host de `site.yaml`, por su nombre visible (el de las líneas del bot).
- `ofrecido` va entre comillas si parece un número (`"18"`): YAML convertiría `3.10` en `3.1`; sin comillas
  no valida.
- Solo admiten decisiones `soporte`, `versiones`, `imagenes` y `digest`. Las actualizaciones de sistema, los
  certificados, los discos y los consumibles siempre piden acción.
- En `digest` no hay versión ofrecida: solo `revisar`.

Una línea queda cubierta si coincide la sección, el `host` (con `nombre`), el `objeto` y, si lo lleva, `ofrecido`:

| Sección | `objeto` se compara con | `ofrecido` se compara con |
|---------|-------------------------|---------------------------|
| `soporte` | `producto` o `contenedor` | `ciclo` |
| `versiones` | `producto` o `contenedor` | `ultimo` |
| `imagenes` | `contenedor` (tipo `tag`) | `remota` |
| `digest` | `contenedor` (tipo `digest`) | no aplica |

Basta con que coincida el contenedor **o** el producto: una decisión sobre `grafana` cubre el producto del host y
el contenedor con ese nombre.

**Una decisión nunca oculta un aviso ni silencia una alerta.** Si la línea ya pasa el umbral de su alerta (⚠), se
queda en su sección con ` (decidido: <motivo>)`. Para silenciar una alerta están los silencios de Grafana.

Lo que descarta la política de rama del catálogo ([ciclos.md](ciclos.md)) sale también en «Decidido» como
`Host · contenedor local → remota — motivo (vigia)`; no hace falta escribirlo en `decisiones.yaml`. Si el sitio
tiene su propia decisión para la misma línea, se muestra la suya.

### Caducidad

Toda decisión caduca, así que el fichero solo guarda lo vigente:

- `ofrecido`: deja de aplicar cuando lo ofrecido cambia (sale otra versión).
- `revisar`: vuelve a pendiente en esa fecha; el propio día ya cuenta como vencida.

### Salida

Orden: pendientes, avisos de datos, bloque «Decidido» y, al final, la línea de obsoletas o vencidas.

```
🧭 Soporte            srv-1 · PostgreSQL 14 (bd): pierde el soporte en 14 días ⚠
✔ Decidido (no hace falta hacer nada)
  host1 · prometheus 3.13.1 → v3.15.1 — LTS 3.13; la rama 3.15 pierde soporte antes (TICKET-1)
1 decisión obsoleta o vencida: vigia decisiones --limpiar
```

- Cada línea decidida lleva ` — <motivo>` y ` (<ref>)` si hay; con `revisar` añade `; revisar el dd-mm-aaaa`.
- Si solo queda lo decidido: `Nada pendiente ✅` y debajo el bloque. Con avisos de datos (Prometheus no
  responde o falla una consulta) no se dice «Nada pendiente».
- Una decisión **obsoleta** (no cubre ninguna línea) o **vencida** no sale en el bloque; se cuenta en la
  última línea. Con datos parciales solo se cuentan las vencidas: una decisión puede parecer obsoleta solo porque
  su consulta falló.
- El bloque «Decidido» cuenta para el límite de líneas y va el último: si hay que recortar, se recorta antes
  lo decidido que lo pendiente.

### Comandos

- `uv run vigia validate`: comprueba el formato y los hosts de `decisiones.yaml` (no consulta Prometheus).
- `uv run vigia decisiones`: consulta el Prometheus del sitio y lista cada decisión como `[vigente]`,
  `[obsoleta]` o `[vencida]`.
- `uv run vigia decisiones --limpiar`: muestra el diff del fichero sin las obsoletas ni las vencidas; con `--yes` lo
  escribe. Conserva los comentarios de primer nivel (columna 0), también uno justo encima de una entrada quitada;
  si el fichero no tiene una entrada por `- ` en la columna 0, lo rechaza y se limpia a mano.

El `config.json` del bot lleva la lista ya validada (sin secretos): un cambio en `decisiones.yaml` aparece como
diferencia en `vigia deploy monitor` y se recoge al reiniciar el bot.

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

Prometheus lee `/metrics` del bot (job `bot`):

- `vigia_bot_up`.
- `vigia_bot_mensajes_total{resultado}`: atendido, descartado (otro chat), ignorado (sin texto o anterior al
  arranque), sin_respuesta (no es un comando), limitado, error (un comando falló) y fallo_envio (Telegram no
  aceptó la respuesta).
- `vigia_bot_telegram_ultimo_ok_timestamp_seconds`: última respuesta correcta de Telegram (al arrancar, la hora
  de arranque).

Si el bot cae, avisa «Exporter sin respuesta». Si sigue en marcha pero lleva más de 10 minutos sin respuesta de
Telegram (token revocado, red, API caída), «Bot sin contacto con Telegram»; ese aviso llega por correo si
Telegram no funciona. Con más de 20 respuestas por minuto el bot calla y avisa una sola vez («Demasiadas
consultas»).
