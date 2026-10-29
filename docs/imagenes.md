# Imágenes nuevas de los contenedores (What's Up Docker)

En cada host con `imagenes`, vigia despliega [What's Up Docker](https://getwud.app) junto a sus agentes.
Lee el socket de Docker en solo lectura y, cada `modulos.imagenes.cron`, consulta los registros para ver si
hay una imagen nueva de cada contenedor. No actualiza nada: no tiene *triggers*.

## En el sitio

```yaml
hosts:
  - id: srv-1
    tipo: linux
    cadvisor: {puerto: 9338}
    imagenes: {puerto: 9339}                  # su interfaz web y /metrics
modulos:
  imagenes:
    clave: WUD_ADMIN_CLAVE                    # contraseña del usuario `vigia` de su interfaz web
    cron: "17 */6 * * *"                      # por defecto, cada 6 h
alertas:
  umbrales: {imagen_durante: 168h}
```

- Desde What's Up Docker 9.6 la interfaz web exige un administrador. vigia lo crea con usuario `vigia` y la
  contraseña de la variable `clave` (fichero de entorno del sitio, como los demás secretos). Las métricas no
  la piden (`WUD_PROMETHEUS_AUTH=false`), igual que cAdvisor o node_exporter.
- No monta el socket de Docker: lo lee a través de `wud-socket` (docker-socket-proxy) que solo deja consultar
  contenedores, imágenes, eventos e info y rechaza cualquier POST. Montar el socket en `:ro` no bastaría: no
  limita la API y con ella se podría crear un contenedor privilegiado. What's Up Docker corre además con el
  sistema de ficheros de solo lectura, sin capacidades y con su puerto solo en la IP del host.
- Cada 6 h para no gastar el límite de consultas de Docker Hub sin cuenta. Se vigilan también los *digests*
  de las etiquetas que no son versiones (`latest`, `stable`…).

## Avisos

| Regla | Cuándo avisa |
|-------|--------------|
| Versión nueva de una imagen | la etiqueta es una versión y en el registro hay otra más nueva (`grafana:13.0.2` → `13.3.0`). watchtower nunca cambia de etiqueta: hay que hacerlo a mano |
| Imagen nueva sin aplicar | misma etiqueta con otro *digest* (un `latest` nuevo) durante `imagen_durante` (7 días). watchtower lo habría aplicado ya: si no, ese contenedor está fuera de watchtower |

Los dos son informativos (`info`, categoría `mantenimiento`) y se repiten cada `alertas.repetir_info`.

## Métricas

Prometheus lee `/metrics` (job `imagenes`) y se queda solo con `wud_containers`, con estas etiquetas:
`nombre` (host), `contenedor`, `imagen`, `tipo` (`tag`, `digest` o `unknown`), `local`, `remota` y `nueva`
(`true`/`false`).
