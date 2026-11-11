"""El kit de instalación en el cliente (instalacion/gestifarma.sh), con un docker simulado.

Prueba la parte que más importa del comando: que una actualización que no responde vuelva sola a la
versión anterior, y que no se toque nada si falla el respaldo previo o no se puede bajar la versión.
"""

import os
import shutil
import subprocess
import sys

import pytest
from fabricas import RAIZ

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="el kit corre en el servidor Linux"
)

# Registra cada llamada y responde como Docker. La app «no responde» cuando la versión configurada en .env
# es FALSO_VERSION_ROTA.
DOCKER_FALSO = r"""#!/usr/bin/env bash
echo "$*" >>"$FALSO_REGISTRO"
if [ "$1" = info ]; then exit 0; fi
if [ "$1" = inspect ]; then
	version="$(sed -n 's/^GESTIFARMA_VERSION=//p' "$FALSO_ENV" | tail -n 1)"
	if [ "$version" = "${FALSO_VERSION_ROTA:-}" ]; then echo unhealthy; else echo healthy; fi
	exit 0
fi
if [ "$1" = compose ] && [ "$2" = version ]; then exit 0; fi
llamada="$*"
case "$llamada" in
*" ps -q app"*) echo id-de-la-app ;;
*"respaldar.sh"*) [ "${FALSO_RESPALDO_FALLA:-no}" = si ] && exit 1 ;;
*" pull app"*) [ "${FALSO_PULL_FALLA:-no}" = si ] && exit 1 ;;
esac
exit 0
"""

CONFIGURACION = {
    "GESTIFARMA_DOMINIO": "gestifarma.ejemplo.com.ar",
    "GESTIFARMA_HTTPS": "interno",
    "GESTIFARMA_CLAVE": "clave",
    "POSTGRES_PASSWORD": "base",
    "RESTIC_PASSWORD": "respaldos",
    "GESTIFARMA_IMAGEN": "registro.ejemplo/gestifarma",
    "GESTIFARMA_VERSION": "1.0.0",
}


@pytest.fixture
def kit(tmp_path):
    destino = tmp_path / "instalacion"
    shutil.copytree(
        RAIZ / "instalacion", destino, ignore=shutil.ignore_patterns(".env", "estado", "config", "respaldo-local")
    )
    lineas = []
    for linea in (destino / ".env.ejemplo").read_text(encoding="utf-8").splitlines():
        clave = linea.split("=", 1)[0]
        lineas.append(f"{clave}={CONFIGURACION[clave]}" if clave in CONFIGURACION else linea)
    (destino / ".env").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    binarios = tmp_path / "bin"
    binarios.mkdir()
    (binarios / "docker").write_text(DOCKER_FALSO, encoding="utf-8")
    (binarios / "docker").chmod(0o755)
    return destino


def correr(kit, *argumentos, **entorno):
    variables = {
        **os.environ,
        "PATH": f"{kit.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FALSO_REGISTRO": str(kit.parent / "llamadas.log"),
        "FALSO_ENV": str(kit / ".env"),
        "ESPERA_SALUD": "1",
        "PAUSA_SALUD": "0.1",
        **entorno,
    }
    return subprocess.run(
        ["bash", str(kit / "gestifarma.sh"), *argumentos], capture_output=True, text=True, env=variables, check=False
    )


def version(kit) -> str:
    lineas = (kit / ".env").read_text(encoding="utf-8").splitlines()
    return [linea.split("=", 1)[1] for linea in lineas if linea.startswith("GESTIFARMA_VERSION=")][-1]


def llamadas(kit) -> str:
    registro = kit.parent / "llamadas.log"
    return registro.read_text(encoding="utf-8") if registro.exists() else ""


def test_actualiza_con_respaldo_previo(kit):
    resultado = correr(kit, "actualizar", "1.1.0")
    assert resultado.returncode == 0, resultado.stderr
    assert version(kit) == "1.1.0"
    registro = llamadas(kit)
    assert registro.index("respaldar.sh actualizacion") < registro.index("pull app") < registro.index("up -d app")
    assert "restaurar.sh" not in registro
    assert "1.1.0\tactualizacion" in (kit / "estado" / "versiones.log").read_text(encoding="utf-8")


def test_vuelve_sola_a_la_version_anterior_si_la_nueva_no_responde(kit):
    resultado = correr(kit, "actualizar", "1.1.0", FALSO_VERSION_ROTA="1.1.0")
    assert resultado.returncode == 1
    assert "se volvió a la 1.0.0" in resultado.stderr
    assert version(kit) == "1.0.0"
    registro = llamadas(kit)
    assert registro.index("stop app") < registro.index("restaurar.sh --base-previa") < registro.rindex("up -d app")
    assert "vuelta atrás desde 1.1.0" in (kit / "estado" / "versiones.log").read_text(encoding="utf-8")


def test_no_actualiza_si_falla_el_respaldo_previo(kit):
    resultado = correr(kit, "actualizar", "1.1.0", FALSO_RESPALDO_FALLA="si")
    assert resultado.returncode == 1
    assert "Falló el respaldo previo" in resultado.stderr
    assert version(kit) == "1.0.0"
    assert "pull app" not in llamadas(kit)


def test_no_cambia_nada_si_no_se_puede_bajar_la_version(kit):
    resultado = correr(kit, "actualizar", "1.1.0", FALSO_PULL_FALLA="si")
    assert resultado.returncode == 1
    assert version(kit) == "1.0.0"
    assert "up -d app" not in llamadas(kit)


def test_primera_instalacion_genera_las_claves(kit):
    (kit / ".env").unlink()
    resultado = correr(kit, "instalar")
    assert resultado.returncode == 0, resultado.stderr
    assert "Completar GESTIFARMA_DOMINIO" in resultado.stdout
    claves = dict(
        linea.split("=", 1) for linea in (kit / ".env").read_text(encoding="utf-8").splitlines() if "=" in linea
    )
    assert len(claves["RESTIC_PASSWORD"]) == 48 and len(claves["POSTGRES_PASSWORD"]) == 48
    assert claves["GESTIFARMA_CLAVE"] and claves["GESTIFARMA_CLAVE"] != claves["RESTIC_PASSWORD"]
    assert oct((kit / ".env").stat().st_mode)[-3:] == "600"


def test_pide_el_token_de_cloudflare_en_modo_red_local(kit):
    contenido = (
        (kit / ".env").read_text(encoding="utf-8").replace("GESTIFARMA_HTTPS=interno", "GESTIFARMA_HTTPS=red-local")
    )
    (kit / ".env").write_text(contenido, encoding="utf-8")
    resultado = correr(kit, "actualizar", "1.1.0")
    assert resultado.returncode == 1
    assert "CLOUDFLARE_API_TOKEN" in resultado.stderr
    assert llamadas(kit).count("respaldar.sh") == 0
