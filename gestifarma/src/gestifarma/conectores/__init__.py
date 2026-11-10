"""Conectores para traer lo cargado en los sistemas externos.

- archivo: importa un reporte exportado (CSV/Excel). Opción recomendada para arrancar.
- portal_web: robot (RPA) que descarga ese mismo reporte del portal con usuario y contraseña.
- API: cuando la gerenciadora/colegio ofrezca un webservice, se agrega un conector que devuelva
  RegistroSistema igual que los anteriores; el resto del sistema no cambia.
"""

from .archivo import ErrorImportacion, LecturaArchivo, MapeoArchivo, cargar_fuentes, leer_archivo

__all__ = ["ErrorImportacion", "LecturaArchivo", "MapeoArchivo", "cargar_fuentes", "leer_archivo"]
