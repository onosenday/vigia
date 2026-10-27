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
```

| Tipo | Qué mide |
|------|----------|
| `url` (https) | que responda 2xx (sigue redirecciones), tiempo, código HTTP y **validez y caducidad del certificado**; un certificado inválido es un fallo, nunca se ignora |
| `url` (http) | que responda 2xx o 3xx (sin seguir redirecciones); aviso de `vigia validate`: mejor la URL https |
| `host` | ping (ICMP) |
| `host` + `puertos` | que se pueda abrir una conexión TCP a cada puerto; no se envía nada |

Entran en las alertas «Caído» y «Certificado a punto de caducar» y tienen su panel, «Externos».

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
