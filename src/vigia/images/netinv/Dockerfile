# netinv — inventario de dispositivos de la red
FROM python:3.12-alpine3.24@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7
RUN apk add --no-cache arp-scan nmap nmap-scripts \
 && pip install --no-cache-dir zeroconf==0.136.0 pyyaml==6.0.2
COPY netinv.py /app/netinv.py
CMD ["python3", "-u", "/app/netinv.py"]
