"""Robot (RPA) que entra al portal web de la gerenciadora / colegio y descarga el reporte de lo cargado.

Usar solo si el portal no ofrece API y no hay forma de que alguien baje el reporte a mano. Criterios:
- El robot hace lo mismo que una persona para DESCARGAR el reporte (Excel/CSV) y después se reutiliza
  el importador de archivos con el mismo mapeo de columnas. No "lee la pantalla": si el portal cambia
  de diseño, solo se ajustan los selectores.
- Solo lectura: nunca modifica datos del portal.
- Las credenciales vienen de variables de entorno o de un gestor de secretos, nunca del código.
- Antes de usarlo, revisar los términos de uso del portal y pedir autorización (ver docs/propuesta.md).

La configuración va en la sección [portal] del archivo de la fuente (config/fuentes/<nombre>.toml).
Requiere las dependencias opcionales:  pip install "gestifarma[rpa]"  y  playwright install chromium
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path


class ErrorPortal(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigPortal:
    url_login: str
    selector_usuario: str
    selector_clave: str
    selector_ingresar: str
    url_reporte: str
    selector_desde: str
    selector_hasta: str
    selector_exportar: str
    selector_login_ok: str | None = None  # algo que solo aparece si el login funcionó
    formato_fecha: str = "%d/%m/%Y"
    headless: bool = True
    timeout_ms: int = 60_000

    @classmethod
    def desde_dict(cls, datos: dict) -> ConfigPortal:
        validos = {f.name for f in fields(cls)}
        desconocidos = set(datos) - validos
        if desconocidos:
            raise ErrorPortal(f"Claves desconocidas en [portal]: {sorted(desconocidos)}")
        try:
            return cls(**datos)
        except TypeError as exc:
            raise ErrorPortal(f"Configuración [portal] incompleta: {exc}") from exc


def descargar_reporte(config: ConfigPortal, usuario: str, clave: str, desde: date, hasta: date, destino: Path) -> Path:
    """Entra al portal, pide el reporte del período y devuelve la ruta del archivo descargado."""
    try:
        from playwright.sync_api import Error as ErrorPlaywright
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ErrorPortal('Falta Playwright: pip install "gestifarma[rpa]" && playwright install chromium') from exc

    destino.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=config.headless)
        try:
            contexto = navegador.new_context(accept_downloads=True)
            pagina = contexto.new_page()
            pagina.set_default_timeout(config.timeout_ms)

            pagina.goto(config.url_login)
            pagina.fill(config.selector_usuario, usuario)
            pagina.fill(config.selector_clave, clave)
            pagina.click(config.selector_ingresar)
            if config.selector_login_ok:
                pagina.wait_for_selector(config.selector_login_ok)

            pagina.goto(config.url_reporte)
            pagina.fill(config.selector_desde, desde.strftime(config.formato_fecha))
            pagina.fill(config.selector_hasta, hasta.strftime(config.formato_fecha))
            with pagina.expect_download() as espera:
                pagina.click(config.selector_exportar)
            descarga = espera.value
            ruta = destino / (Path(descarga.suggested_filename).name or "reporte.csv")
            descarga.save_as(ruta)
            return ruta
        except ErrorPlaywright as exc:
            raise ErrorPortal(
                f"El robot no pudo completar la descarga ({exc}). Revisar el usuario y la clave y, si el "
                "portal cambió, los selectores de config/fuentes."
            ) from exc
        finally:
            navegador.close()
