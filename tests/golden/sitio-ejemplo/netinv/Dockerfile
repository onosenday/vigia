# netinv — inventario de dispositivos de la red
FROM python:3.12-alpine
RUN apk add --no-cache arp-scan nmap nmap-scripts \
 && pip install --no-cache-dir zeroconf==0.136.0 pyyaml==6.0.2
COPY netinv.py /app/netinv.py
CMD ["python3", "-u", "/app/netinv.py"]
