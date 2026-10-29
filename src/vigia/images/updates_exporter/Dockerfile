FROM alpine:3.20
# openssh-client para el sondeo. El httpd de busybox YA NO viene en el busybox
# base de Alpine (3.20); vive en el paquete busybox-extras.
RUN apk add --no-cache openssh-client busybox-extras jq
COPY collect.sh metrics.sh entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/collect.sh /usr/local/bin/metrics.sh /usr/local/bin/entrypoint.sh
EXPOSE 8099
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
