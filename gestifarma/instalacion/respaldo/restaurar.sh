#!/bin/sh
# Restaura Gestifarma desde un respaldo. La app tiene que estar detenida: lo hace ./gestifarma.sh restaurar.
# Uso:
#   restaurar.sh [id|latest] [local|remoto]   base y fotos de ese respaldo (por defecto, el último del disco)
#   restaurar.sh --base-previa                la base como quedó en el último respaldo (vuelta atrás de una actualización)
set -eu

DATOS="${RESPALDO_DATOS:-/datos}"
TRABAJO="${RESPALDO_TRABAJO:-/trabajo}"
DISCO="${RESPALDO_DISCO_MONTADO:-/respaldo}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') restaurar: $*"; }

restaurar_base() { # $1: archivo de pg_dump
	log "Restaurando la base de datos"
	pg_restore --clean --if-exists --no-owner --single-transaction --dbname="${PGDATABASE:-gestifarma}" "$1"
}

if [ "${1:-}" = "--base-previa" ]; then
	if [ ! -f "$TRABAJO/base.dump" ]; then
		log "No hay una copia previa de la base en $TRABAJO"
		exit 1
	fi
	restaurar_base "$TRABAJO/base.dump"
	log "Listo: la base volvió al estado del último respaldo"
	exit 0
fi

id="${1:-latest}"
case "${2:-local}" in
local) repo="$DISCO/gestifarma" ;;
remoto) repo="${RESPALDO_REMOTO:?No hay copia fuera del local configurada (RESPALDO_REMOTO)}" ;;
*)
	log "Origen desconocido: $2 (usar local o remoto)"
	exit 2
	;;
esac

destino="$TRABAJO/restaurar"
rm -rf "$destino"
mkdir -p "$destino"
log "Recuperando el respaldo $id"
restic -r "$repo" restore "$id" --host gestifarma --target "$destino"
if [ ! -f "$destino$TRABAJO/base.dump" ]; then
	log "El respaldo $id no tiene la base de datos"
	exit 1
fi
restaurar_base "$destino$TRABAJO/base.dump"
log "Restaurando las fotos"
mkdir -p "$DATOS"
find "$DATOS" -mindepth 1 -delete
cp -a "$destino$DATOS/." "$DATOS/"
rm -rf "$destino"
log "Listo: base y fotos restauradas desde el respaldo $id"
