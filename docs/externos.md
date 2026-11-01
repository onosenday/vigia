# Externos: equipos y webs fuera de la red del sitio

Para vigilar lo que está en internet (un servidor alquilado, la web pública, un servicio en la nube) sin
instalar nada en el destino ni abrir ningún puerto: el monitor sondea **hacia fuera** con blackbox.

```yaml
externos:
  intervalo: 60s                  # mínimo 60s
  objetivos:
    - {nombre: Web corporativa, url: "https://www.example.org/"}
    - {nombre: Servidor externo, host: servidor.example.net, puertos: [443]}
    - {nombre: SSH del servidor, host: ssh.example.net, puertos: [22], puertos_sensibles: true, alerta: false}
    - {nombre: Router de la oficina, host: vpn.example.org, puertos: [1723],
       puertos_cerrados: [443, 8443, 22], puertos_sensibles: true}
```

| Tipo | Qué mide |
|------|----------|
| `url` (https) | que responda 2xx (sigue redirecciones), tiempo, código HTTP y **validez y caducidad del certificado**; un certificado inválido es un fallo, nunca se ignora |
| `url` (http) | que responda 2xx o 3xx (sin seguir redirecciones); aviso de `vigia validate`: mejor la URL https |
| `host` | ping (ICMP) |
| `host` + `puertos` | que se pueda abrir una conexión TCP a cada puerto; no se envía nada |
| `host` + `puertos_cerrados` | lo contrario: que **no** se pueda; si alguno acepta la conexión, alerta «Puerto expuesto» |

Entran en las alertas «Caído» y «Certificado a punto de caducar» y tienen su panel, «Externos».

## Puertos que deben estar cerrados

Las sondas normales solo avisan si algo deja de responder, no si algo aparece. `puertos_cerrados` vigila lo
segundo: un router o un servidor que, tras una actualización de firmware o un cambio a mano, vuelve a dejar abierta
a internet su web de gestión, su VPN SSL, SSH o una base de datos. Cada puerto es una conexión TCP que se cierra
sin enviar nada; si se establece, salta «Puerto expuesto» (crítica) y el panel «Externos» lo marca **EXPUESTO**
en la tabla «Puertos que deben estar cerrados».

- Solo con `host`; un puerto no puede estar a la vez en `puertos` y en `puertos_cerrados`; como mucho 20 por objetivo.
- Los de administración y bases de datos piden también `puertos_sensibles: true`.
- **NAT loopback**: si el monitor está dentro de la red y sondea la IP pública de su **propio** router, la conexión
  no viene de internet. Según el router, el resultado no vale: con NAT loopback puede contestar la interfaz de
  gestión interna (falso «expuesto») o reenviar a un equipo de dentro; sin él, todo parece cerrado (falso «cerrado»).
  Compruébalo una vez desde fuera (p. ej. con datos móviles) antes de fiarte, o vigila la IP pública desde un
  monitor de otro sitio.

## Seguridad

- **Solo salida**: nada se instala en el destino ni se abre en la red del sitio. Las sondas son un GET sin cuerpo
  ni credenciales (User-Agent `vigia`), un ping o una conexión TCP que se cierra sin enviar datos.
- **Solo destinos públicos**: `vigia validate` rechaza IPs privadas, loopback, link-local (incluida la de
  metadatos de nube, 169.254.169.254), CGNAT y reservadas; nombres internos (`.lan`, `.local`, `.internal`…);
  nombres del dominio del sitio e IPs de sus subredes (eso va en `ping`, `servicios` o `web`).
- **Puertos sensibles**: SSH, RDP, SMB, Telnet, FTP, VNC, WinRM, Docker y bases de datos solo con
  `puertos_sensibles: true` en ese objetivo. Si un puerto así responde desde internet, ya es un hallazgo: mejor
  cerrarlo que vigilarlo.
- **Frecuencia y tamaño acotados**: intervalo mínimo de 60 s y como mucho 50 objetivos, para no parecer un
  escaneo a los ojos del destino.
- Un nombre DNS se resuelve al sondear: vigila solo nombres de dominios propios o de confianza.

Para métricas de equipos remotos (CPU, RAM, discos) hace falta otro mecanismo con túnel y mTLS; está en diseño
(modelo de amenazas antes de implementarlo).
