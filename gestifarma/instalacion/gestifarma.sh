#!/usr/bin/env bash
# Administra Gestifarma instalado en el servidor de la farmacia (o en su propia nube).
# Uso: ./gestifarma.sh <comando>   (./gestifarma.sh ayuda muestra los comandos)
set -Eeuo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
ENV_FILE="$DIR/.env"
ESPERA_SALUD="${ESPERA_SALUD:-240}" # segundos que se espera a que la app responda
PAUSA_SALUD="${PAUSA_SALUD:-3}"

info() { printf '\033[1m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33mAviso:\033[0m %s\n' "$*" >&2; }
error() {
	printf '\033[31mError:\033[0m %s\n' "$*" >&2
	exit 1
}

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

valor() { # valor VARIABLE: su valor en .env, sin comillas (vacío si no está)
	[ -f "$ENV_FILE" ] || return 0
	sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed 's/^"\(.*\)"$/\1/'
}

fijar() { # fijar VARIABLE VALOR: lo escribe en .env (valores sin espacios ni |)
	if grep -q "^$1=" "$ENV_FILE"; then
		sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
	else
		printf '%s=%s\n' "$1" "$2" >>"$ENV_FILE"
	fi
}

secreto() { head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

requisitos() {
	command -v docker >/dev/null || error "Falta Docker (ver README.md, «Preparar el servidor»)."
	docker compose version >/dev/null 2>&1 || error "Falta el complemento «docker compose»."
	docker info >/dev/null 2>&1 || error "Docker no responde: ¿está corriendo y el usuario está en el grupo docker?"
	[ -f "$ENV_FILE" ] || [ "${1:-}" = instalar ] || error "Falta .env: correr primero ./gestifarma.sh instalar."
}

validar_env() {
	[ -n "$(valor GESTIFARMA_DOMINIO)" ] || error "Falta GESTIFARMA_DOMINIO en .env (por ejemplo gestifarma.sufarmacia.com.ar)."
	case "$(valor GESTIFARMA_HTTPS)" in
	"" | red-local)
		[ -n "$(valor CLOUDFLARE_API_TOKEN)" ] || error "El modo red-local necesita CLOUDFLARE_API_TOKEN en .env (ver README.md)."
		;;
	publico | interno) ;;
	*) error "GESTIFARMA_HTTPS tiene que ser red-local, publico o interno." ;;
	esac
	local variable
	for variable in POSTGRES_PASSWORD GESTIFARMA_USUARIO GESTIFARMA_CLAVE RESTIC_PASSWORD; do
		[ -n "$(valor "$variable")" ] || error "Falta $variable en .env."
	done
}

usa_registro() { [[ "$(valor GESTIFARMA_IMAGEN)" == */* ]]; }

version_del_codigo() { # versión de la imagen cuando se construye desde este repositorio
	local version
	version="$(git -C "$DIR/.." describe --tags --always --dirty 2>/dev/null || true)"
	echo "${version:-local}"
}

preparar_app() { # baja (si hay registro) o construye la imagen de la versión que figura en .env
	if usa_registro; then
		compose pull app
	else
		compose build app
	fi
}

esperar_salud() { # hasta ESPERA_SALUD segundos a que Docker marque la app como saludable
	local limite=$((SECONDS + ESPERA_SALUD)) id estado
	while ((SECONDS < limite)); do
		id="$(compose ps -q app 2>/dev/null || true)"
		if [ -n "$id" ]; then
			estado="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id" 2>/dev/null || true)"
			[ "$estado" = healthy ] && return 0
		fi
		sleep "$PAUSA_SALUD"
	done
	return 1
}

registrar_version() { # deja asentado cada cambio de versión
	mkdir -p "$DIR/estado"
	printf '%s\t%s\t%s\n' "$(date -Iseconds)" "$1" "$2" >>"$DIR/estado/versiones.log"
}

preparar_disco() {
	local disco
	disco="$(valor RESPALDO_DISCO)"
	if [ -z "$disco" ]; then
		disco="$DIR/respaldo-local"
		aviso "RESPALDO_DISCO está vacío: el respaldo local queda en el disco interno ($disco). Configurar el disco externo antes de entregar."
	elif ! mountpoint -q "$disco"; then
		error "$disco no es un disco montado: conectar y montar el disco de respaldo (README.md) o corregir RESPALDO_DISCO."
	fi
	mkdir -p "$disco"
	[ -f "$disco/.gestifarma-respaldo" ] || date -Iseconds >"$disco/.gestifarma-respaldo"
}

cmd_instalar() {
	requisitos instalar
	if [ ! -f "$ENV_FILE" ]; then
		cp "$DIR/.env.ejemplo" "$ENV_FILE"
		chmod 600 "$ENV_FILE"
		fijar POSTGRES_PASSWORD "$(secreto)"
		fijar GESTIFARMA_CLAVE "$(secreto 8)"
		fijar RESTIC_PASSWORD "$(secreto)"
		info "Se creó .env con claves nuevas."
		echo "Completar GESTIFARMA_DOMINIO, el modo del certificado y RESPALDO_DISCO, y volver a correr ./gestifarma.sh instalar"
		return 0
	fi
	validar_env
	if [ ! -d "$DIR/config" ]; then
		cp -r "$DIR/../config" "$DIR/config"
		info "Se copiaron las reglas y los formatos de ejemplo a instalacion/config: ajustarlos a la farmacia."
	fi
	preparar_disco
	mkdir -p "$DIR/estado"
	if ! usa_registro; then
		fijar GESTIFARMA_VERSION "$(version_del_codigo)"
	fi
	[ -n "$(valor GESTIFARMA_VERSION)" ] || error "Falta GESTIFARMA_VERSION en .env (la versión publicada a instalar)."

	info "Preparando Gestifarma $(valor GESTIFARMA_VERSION) (la primera vez tarda unos minutos)…"
	preparar_app
	compose build proxy respaldo
	compose up -d
	esperar_salud || error "Gestifarma no respondió. Revisar: ./gestifarma.sh registros app"
	registrar_version "$(valor GESTIFARMA_VERSION)" instalacion

	info "Primer respaldo…"
	compose exec -T respaldo respaldar.sh instalacion || aviso "El primer respaldo falló: revisar ./gestifarma.sh estado"

	info "Gestifarma quedó instalado."
	cat <<FIN

  Dirección:  https://$(valor GESTIFARMA_DOMINIO)
  Usuario:    $(valor GESTIFARMA_USUARIO)
  Clave:      $(valor GESTIFARMA_CLAVE)

  Clave de recuperación de los respaldos (RESTIC_PASSWORD):
      $(valor RESTIC_PASSWORD)
  Imprimirla y entregarla a la farmacia en un sobre cerrado: sin ella no se puede restaurar un respaldo.

  Falta revisar: el DNS del dominio, la entrada en el DNS del router, la VPN y una restauración de prueba
  (lista de control en README.md).
FIN
}

cmd_actualizar() {
	requisitos
	validar_env
	local anterior nueva
	anterior="$(valor GESTIFARMA_VERSION)"
	if usa_registro; then
		nueva="${1:-}"
		[ -n "$nueva" ] || error "Indicar la versión: ./gestifarma.sh actualizar 1.2.0"
	else
		nueva="$(version_del_codigo)"
	fi
	if [ "$nueva" = "$anterior" ] && [ "${FORZAR:-no}" != si ]; then
		info "Ya está instalada la versión $nueva."
		return 0
	fi

	info "Actualizando de $anterior a $nueva"
	info "1/4 Respaldo previo"
	compose exec -T respaldo respaldar.sh actualizacion ||
		error "Falló el respaldo previo, así que no se actualiza. Sigue andando la versión $anterior."
	info "2/4 Preparando la versión $nueva"
	fijar GESTIFARMA_VERSION "$nueva"
	if ! preparar_app; then
		fijar GESTIFARMA_VERSION "$anterior"
		error "No se pudo preparar la versión $nueva. Sigue andando la versión $anterior."
	fi
	info "3/4 Instalando"
	compose up -d app
	info "4/4 Verificando"
	if esperar_salud; then
		registrar_version "$nueva" actualizacion
		info "Listo: Gestifarma quedó en la versión $nueva."
		return 0
	fi

	aviso "La versión $nueva no respondió: vuelvo a la $anterior con la base como estaba antes de actualizar."
	compose stop app
	compose exec -T respaldo restaurar.sh --base-previa
	fijar GESTIFARMA_VERSION "$anterior"
	compose up -d app
	if esperar_salud; then
		registrar_version "$anterior" "vuelta atrás desde $nueva"
		error "La actualización a $nueva falló y se volvió a la $anterior. Revisar: ./gestifarma.sh registros app"
	fi
	error "ATENCIÓN: tampoco responde la versión $anterior. Revisar: ./gestifarma.sh registros app"
}

cmd_respaldar() {
	requisitos
	compose exec -T respaldo respaldar.sh manual
}

cmd_respaldos() {
	requisitos
	if [ "${1:-local}" = remoto ]; then
		# La variable se expande adentro del contenedor, donde está configurada.
		# shellcheck disable=SC2016
		compose exec -T respaldo sh -c 'restic -r "$RESPALDO_REMOTO" snapshots --host gestifarma'
	else
		compose exec -T respaldo restic -r /respaldo/gestifarma snapshots --host gestifarma
	fi
}

cmd_restaurar() {
	requisitos
	local id="${1:-latest}" origen="${2:-local}" respuesta
	if [ "${CONFIRMAR:-no}" != si ]; then
		echo "Esto reemplaza la base y las fotos actuales por las del respaldo $id ($origen)."
		read -r -p "Escribir RESTAURAR para seguir: " respuesta
		[ "$respuesta" = RESTAURAR ] || error "Cancelado: no se cambió nada."
	fi
	compose stop app
	if ! compose exec -T respaldo restaurar.sh "$id" "$origen"; then
		compose start app
		error "Falló la restauración. Revisar los mensajes de arriba antes de volver a intentar."
	fi
	compose start app
	esperar_salud || error "La app no respondió después de restaurar. Revisar: ./gestifarma.sh registros app"
	info "Restauración terminada: la app ya está usando los datos del respaldo $id."
}

cmd_estado() {
	requisitos
	info "Servicios"
	compose ps --format 'table {{.Service}}\t{{.Status}}'
	info "Gestifarma"
	echo "Versión configurada: $(valor GESTIFARMA_VERSION)"
	compose exec -T app python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=5)))" ||
		aviso "La app no responde."
	info "Espacio en disco"
	local disco
	disco="$(valor RESPALDO_DISCO)"
	df -h / ${disco:+"$disco"}
	info "Último respaldo"
	local archivo="$DIR/estado/ultimo-respaldo.json"
	if [ ! -f "$archivo" ]; then
		aviso "Todavía no hay respaldos."
		return 0
	fi
	cat "$archivo"
	grep -q '"resultado": "ok"' "$archivo" || aviso "El último respaldo terminó con errores."
	[ -z "$(find "$archivo" -mmin +1560)" ] || aviso "El último respaldo tiene más de 26 horas."
}

cmd_registros() {
	requisitos
	compose logs --tail "${LINEAS:-200}" "$@"
}

cmd_reiniciar() { # por ejemplo después de cambiar las reglas o los formatos en config/
	requisitos
	compose restart "${@:-app}"
}

cmd_ayuda() {
	cat <<'FIN'
Uso: ./gestifarma.sh <comando>

  instalar                  Primera instalación: claves, arranque y primer respaldo.
  actualizar [versión]      Respaldo previo, nueva versión y verificación; si falla, vuelve sola a la anterior.
  respaldar                 Respaldo inmediato (además del de todas las noches).
  respaldos [remoto]        Lista los respaldos del disco local o de la copia fuera del local.
  restaurar [id] [remoto]   Restaura la base y las fotos de un respaldo (por defecto, el último del disco).
  estado                    Servicios, versión, espacio en disco y último respaldo.
  registros [servicio]      Últimas líneas de los registros (app, proxy, db, respaldo).
  reiniciar [servicio]      Reinicia la app (o el servicio indicado), por ejemplo después de cambiar config/.
FIN
}

case "${1:-ayuda}" in
instalar) cmd_instalar ;;
actualizar) cmd_actualizar "${@:2}" ;;
respaldar) cmd_respaldar ;;
respaldos) cmd_respaldos "${@:2}" ;;
restaurar) cmd_restaurar "${@:2}" ;;
estado) cmd_estado ;;
registros) cmd_registros "${@:2}" ;;
reiniciar) cmd_reiniciar "${@:2}" ;;
ayuda | -h | --help) cmd_ayuda ;;
*)
	cmd_ayuda
	exit 2
	;;
esac
