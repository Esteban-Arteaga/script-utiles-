#!/bin/sh
# Respaldo cifrado de Gestifarma: la base de datos (pg_dump) y las fotos, guardadas con restic.
# Uso: respaldar.sh [motivo]   (programado, manual, actualizacion, instalacion)
#
# Guarda una copia en el disco de respaldo (/respaldo) y, si está configurado RESPALDO_REMOTO, otra fuera
# del local. Deja el resultado en /estado/ultimo-respaldo.json y, si hay MONITOR_URL, avisa si salió bien
# o mal (sin datos de recetas ni de pacientes). La copia de la base queda en /trabajo/base.dump para
# poder volver atrás una actualización.
set -u

MOTIVO="${1:-manual}"
DATOS="${RESPALDO_DATOS:-/datos}"
TRABAJO="${RESPALDO_TRABAJO:-/trabajo}"
DISCO="${RESPALDO_DISCO_MONTADO:-/respaldo}"
ESTADO="${RESPALDO_ESTADO:-/estado}"
REMOTO="${RESPALDO_REMOTO:-}"
REPO_LOCAL="$DISCO/gestifarma"
# La marca la deja el instalador en el disco externo: si falta, el disco no está montado y no se
# respalda sobre el disco interno sin avisar.
MARCA="$DISCO/.gestifarma-respaldo"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') respaldo: $*"; }

respaldar_en() { # $1: repositorio de restic
	repo="$1"
	if ! restic -r "$repo" cat config >/dev/null 2>&1; then
		log "Creando el repositorio de respaldos"
		restic -r "$repo" init || return 1
	fi
	restic -r "$repo" backup --host gestifarma --tag "$MOTIVO" "$TRABAJO/base.dump" "$DATOS" || return 1
	restic -r "$repo" forget --host gestifarma --keep-daily 7 --keep-weekly 4 --keep-monthly 12 || return 1
	# Los domingos, en el respaldo programado: libera espacio y verifica que el repositorio esté sano.
	if [ "$MOTIVO" = programado ] && [ "$(date +%u)" = 7 ]; then
		restic -r "$repo" prune || return 1
		restic -r "$repo" check || return 1
	fi
}

mkdir -p "$TRABAJO" "$ESTADO"
exec 9>"$TRABAJO/.respaldo.lock"
if ! flock -w 3600 9; then
	log "Hay otro respaldo en curso desde hace una hora: se cancela este."
	exit 1
fi

inicio=$(date +%s)
base=error
disco_local=omitido
copia_externa=omitido
log "Inicio ($MOTIVO)"

if pg_dump --format=custom --file="$TRABAJO/base.dump.tmp" && mv "$TRABAJO/base.dump.tmp" "$TRABAJO/base.dump"; then
	base=ok
else
	log "ERROR: no se pudo exportar la base de datos"
fi

if [ "$base" = ok ]; then
	if [ ! -f "$MARCA" ]; then
		disco_local=error
		log "ERROR: no está el disco de respaldo (falta $MARCA). ¿Está conectado y montado?"
	elif respaldar_en "$REPO_LOCAL"; then
		disco_local=ok
	else
		disco_local=error
		log "ERROR: falló el respaldo en el disco local"
	fi
	if [ -n "$REMOTO" ]; then
		if respaldar_en "$REMOTO"; then
			copia_externa=ok
		else
			copia_externa=error
			log "ERROR: falló la copia fuera del local"
		fi
	fi
fi

segundos=$(($(date +%s) - inicio))
resultado=ok
for parte in "$base" "$disco_local" "$copia_externa"; do
	if [ "$parte" = error ]; then resultado=error; fi
done

cat >"$ESTADO/ultimo-respaldo.json.tmp" <<FIN
{"fecha": "$(date -Iseconds)", "motivo": "$MOTIVO", "resultado": "$resultado", "base": "$base", "disco_local": "$disco_local", "copia_externa": "$copia_externa", "segundos": $segundos}
FIN
mv "$ESTADO/ultimo-respaldo.json.tmp" "$ESTADO/ultimo-respaldo.json"

if [ -n "${MONITOR_URL:-}" ]; then
	destino="$MONITOR_URL"
	if [ "$resultado" != ok ]; then destino="$MONITOR_URL/fail"; fi
	curl -fsS -m 15 --retry 3 -o /dev/null "$destino" || log "Aviso: no se pudo avisar al monitor"
fi

log "Fin: $resultado (base: $base, disco local: $disco_local, copia externa: $copia_externa, $segundos s)"
[ "$resultado" = ok ]
