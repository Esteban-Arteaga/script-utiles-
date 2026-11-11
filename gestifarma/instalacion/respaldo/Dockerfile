# Respaldos cifrados de Gestifarma: pg_dump de la base y las fotos, guardados con restic
# (cifrado AES-256, incremental: cada noche solo se agrega lo nuevo).
FROM restic/restic:0.17.3 AS restic

FROM postgres:17-alpine
COPY --from=restic /usr/bin/restic /usr/bin/restic
RUN apk add --no-cache curl
COPY entrypoint.sh respaldar.sh restaurar.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/respaldar.sh /usr/local/bin/restaurar.sh

ENTRYPOINT ["entrypoint.sh"]
CMD []
