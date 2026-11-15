# netinv — inventario de dispositivos de la red
FROM python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
RUN apk add --no-cache arp-scan nmap nmap-scripts \
 && pip install --no-cache-dir zeroconf==0.136.0 pyyaml==6.0.2
COPY netinv.py /app/netinv.py
CMD ["python3", "-u", "/app/netinv.py"]
