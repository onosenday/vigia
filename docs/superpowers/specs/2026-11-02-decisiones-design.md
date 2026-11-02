# Decisiones en /pendientes

Fecha: 2026-11-02 · Estado: aprobado (diseño)

## Problema

`/pendientes` lista todo lo que Prometheus marca como mantenimiento: soporte, versiones mayores e imágenes nuevas.
Cuando el sitio ya ha decidido no hacer algo (quedarse en una LTS, una etiqueta más concreta de la misma versión,
un fin de soporte lejano), la línea sigue saliendo igual que lo que sí pide acción, y el usuario no sabe si tiene
que hacer algo o no.

## Objetivo

- Arriba, solo lo que pide acción.
- Lo decidido, al final, en un bloque «Decidido», con el motivo: nada desaparece sin verse.
- Toda decisión caduca, así que el fichero solo guarda lo vigente y no crece con el tiempo.

## Fichero `decisiones.yaml`

Es opcional y va en la carpeta del sitio. Se declara en `site.yaml` igual que `netinv.dispositivos`:
`modulos.bot.decisiones: decisiones.yaml` (ruta relativa al sitio). Es una lista:

```yaml
- seccion: imagenes            # soporte | versiones | imagenes | digest
  host: host1
  objeto: prometheus           # contenedor (imagenes, digest) o producto (soporte, versiones)
  ofrecido: v3.15.1            # versión descartada; si lo ofrecido cambia, la decisión deja de aplicar
  motivo: "LTS 3.13; la rama 3.15 pierde soporte antes"
  ref: TICKET-1                # opcional: issue o nota donde se tomó la decisión
- seccion: soporte
  host: host1
  objeto: grafana
  revisar: 2026-12-15          # sin `ofrecido`: vuelve a pendiente en esa fecha
  motivo: "soporte hasta 01-2027; subir cuando haya versión nueva"
```

- Obligatorios: `seccion`, `host`, `objeto` y `motivo`, y al menos uno de `ofrecido` o `revisar`.
- `host` tiene que ser un host de `site.yaml` (por su nombre visible, como en el resto de líneas del bot).
- Las secciones admitidas son las cuatro en las que decidir tiene sentido. Las actualizaciones de sistema, los
  certificados, los discos y los consumibles siempre piden acción, así que no admiten decisiones.

## Coincidencia

Una línea de `/pendientes` queda cubierta por una decisión si se cumplen todas estas condiciones:

| Sección | `objeto` se compara con | `ofrecido` se compara con |
|---------|-------------------------|---------------------------|
| `soporte` | `producto` (y `contenedor` si lo hay) | `ciclo` |
| `versiones` | `producto` (y `contenedor` si lo hay) | `ultimo` |
| `imagenes` | `contenedor` (tipo `tag`) | `remota` |
| `digest` | `contenedor` (tipo `digest`) | (no aplica: solo `revisar`) |

- `host` se compara con `nombre`.
- Si la decisión lleva `ofrecido`, tiene que coincidir. Si lleva `revisar`, la fecha tiene que ser posterior a hoy
  (en la zona del bot).
- Para el objeto, basta con que coincida el contenedor **o** el producto: así una decisión sobre `grafana` cubre
  tanto el producto del host como el contenedor con ese nombre.

## Salida del bot

- Las líneas cubiertas salen de su sección y van a un bloque final, `✔ Decidido (no hace falta hacer nada)`, con la
  línea original, ` — <motivo>` (las líneas de soporte ya llevan `:`) y ` (<ref>)` si lo hay. Las que llevan `revisar` añaden `; revisar el dd-mm-aaaa`.
- **Una decisión nunca oculta un aviso.** Si la línea ya pasa el umbral de su alerta (⚠), se queda en su sección y
  se le añade ` (decidido: <motivo>)`.
- Si una sección se queda sin líneas, desaparece, como ahora.
- Si solo queda lo decidido: `Nada pendiente ✅` y, debajo, el bloque «Decidido».
- Decisiones **obsoletas** (las que no cubren ninguna línea) o **vencidas** (con `revisar` pasado): no salen en el
  bloque. Al final se añade una línea: `N decisiones obsoletas o vencidas: vigia decisiones --limpiar`.
- El bloque «Decidido» cuenta para el límite de líneas de `/pendientes` y va después de las demás secciones, así
  que, si hay que recortar, se recorta lo decidido antes que lo pendiente.

## CLI

- `vigia decisiones`: consulta el Prometheus del sitio (como el resto de comandos que leen datos vivos) y lista
  cada decisión como vigente, obsoleta o vencida.
- `vigia decisiones --limpiar`: muestra el diff del fichero sin las obsoletas ni las vencidas; con `--yes` lo
  escribe, sin tocar los comentarios del resto del fichero.
- `vigia validate`: comprueba el formato y los hosts. No consulta Prometheus.

## Despliegue

`bot_config()` añade `decisiones` al `config.json` del bot: la lista ya validada, con las fechas en ISO. No lleva
secretos. Un cambio en `decisiones.yaml` aparece como diferencia en `vigia deploy monitor`.

## Fuera de alcance

- El dashboard «Mantenimiento» de Grafana: sigue mostrándolo todo.
- Las alertas: una decisión no silencia ninguna (para eso están los silencios de Grafana).
- Crear decisiones desde Telegram: el bot sigue siendo solo de lectura.

## Pruebas

- Modelo: campos obligatorios, `ofrecido` o `revisar`, secciones válidas, host inexistente y fechas.
- `pendientes()` con un Prometheus falso: línea cubierta que pasa al bloque, decisión obsoleta, decisión vencida,
  una decisión que no oculta un ⚠, todo decidido (`Nada pendiente ✅` + bloque) y el recorte.
- `bot_config()`: incluye las decisiones, o una lista vacía si no hay fichero.
- `vigia decisiones --limpiar`: diff y escritura que conserva los comentarios.
