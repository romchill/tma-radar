# syntax=docker/dockerfile:1
#
# Временный публичный адрес, чтобы открыть мини-апп на телефоне.
# Обычный ssh-клиент: туннель поднимается удалённым пробросом порта через 443,
# поэтому проходит там, где закрыт фирменный порт Cloudflare.
FROM alpine:3.20

RUN apk add --no-cache openssh-client

COPY infra/tunnel-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
