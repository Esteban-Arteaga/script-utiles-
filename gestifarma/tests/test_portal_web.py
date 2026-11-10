"""Prueba del robot (RPA) contra un portal falso que corre en la misma máquina.

Se saltea si Playwright no está instalado (pip install -e ".[rpa]" && playwright install chromium).
"""

import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fabricas import RAIZ

pytest.importorskip("playwright.sync_api")

from gestifarma.conectores import cargar_fuentes, leer_archivo  # noqa: E402
from gestifarma.conectores.portal_web import ConfigPortal, ErrorPortal, descargar_reporte  # noqa: E402

REPORTE = (RAIZ / "ejemplos" / "reporte_colegio_ejemplo.csv").read_bytes()

LOGIN = b"""<form method="post" action="/login">
<input id="usuario" name="usuario"><input id="clave" name="clave" type="password">
<button type="submit">Ingresar</button></form>"""
INICIO = "<p>Hola {usuario}</p><a href='/salir'>Cerrar sesión</a>"
REPORTES = b"""<form method="get" action="/exportar">
<input id="fecha-desde" name="desde"><input id="fecha-hasta" name="hasta">
<button type="submit">Exportar a Excel</button></form>"""


class PortalFalso(BaseHTTPRequestHandler):
    pedidos: list = []

    def log_message(self, *args):
        pass

    def _responder(self, cuerpo: bytes, tipo="text/html; charset=utf-8", extra=None, codigo=200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        for clave, valor in (extra or {}).items():
            self.send_header(clave, valor)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _logueado(self) -> bool:
        return "sesion=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/login":
            self._responder(LOGIN)
        elif url.path == "/inicio" and self._logueado():
            self._responder(INICIO.format(usuario="robot").encode())
        elif url.path == "/reportes" and self._logueado():
            self._responder(REPORTES)
        elif url.path == "/exportar" and self._logueado():
            PortalFalso.pedidos.append(parse_qs(url.query))
            self._responder(REPORTE, "text/csv", {"Content-Disposition": 'attachment; filename="dispensas.csv"'})
        else:
            self._responder(b"no autorizado", codigo=403)

    def do_POST(self):
        datos = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if datos.get("usuario") == ["robot"] and datos.get("clave") == ["secreta"]:
            self._responder(b"", extra={"Set-Cookie": "sesion=ok; Path=/", "Location": "/inicio"}, codigo=303)
        else:
            self._responder(LOGIN, codigo=401)


@pytest.fixture
def portal():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), PortalFalso)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{servidor.server_port}"
    yield ConfigPortal(
        url_login=f"{url}/login",
        selector_usuario="#usuario",
        selector_clave="#clave",
        selector_ingresar="button[type=submit]",
        selector_login_ok="text=Cerrar sesión",
        url_reporte=f"{url}/reportes",
        selector_desde="#fecha-desde",
        selector_hasta="#fecha-hasta",
        selector_exportar="text=Exportar a Excel",
        timeout_ms=10_000,
    )
    servidor.shutdown()


def test_el_robot_descarga_el_reporte_y_se_importa(portal, tmp_path):
    try:
        ruta = descargar_reporte(portal, "robot", "secreta", date(2026, 11, 1), date(2026, 11, 15), tmp_path)
    except ErrorPortal as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            pytest.skip("Falta el navegador de Playwright")
        raise
    assert ruta.name == "dispensas.csv"
    assert PortalFalso.pedidos[-1] == {"desde": ["01/11/2026"], "hasta": ["15/11/2026"]}
    mapeo = cargar_fuentes(RAIZ / "config" / "fuentes")["colegio-ejemplo"]
    assert len(leer_archivo(ruta, mapeo).registros) == 7


def test_login_fallido_da_un_error_claro(portal, tmp_path):
    with pytest.raises(ErrorPortal, match="selectores"):
        descargar_reporte(
            ConfigPortal(**{**portal.__dict__, "timeout_ms": 2_000}),
            "robot",
            "mal",
            date(2026, 11, 1),
            date(2026, 11, 15),
            tmp_path,
        )
