#!/bin/sh
# Programa el respaldo diario con cron. Si se le pasa un comando (por ejemplo restaurar.sh), lo ejecuta.
set -eu

if [ "$#" -gt 0 ]; then
	exec "$@"
fi

horario="${RESPALDO_HORARIO:-30 23 * * *}"
umask 077
# cron no hereda las variables del contenedor: se guardan para el respaldo programado.
export -p >/etc/respaldo.env
echo "$horario . /etc/respaldo.env && /usr/local/bin/respaldar.sh programado >/proc/1/fd/1 2>&1" >/etc/crontabs/root
echo "Respaldo programado: $horario (hora del servidor)."
exec crond -f -l 6
