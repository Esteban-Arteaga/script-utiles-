"""Importación de lo cargado en el sistema a partir de un archivo exportado (CSV o Excel).

Es la forma más simple de arrancar: funciona con cualquier sistema que permita bajar un reporte,
sin credenciales guardadas ni integraciones. Cada formato de reporte se describe con un archivo
config/fuentes/<nombre>.toml que dice qué columna tiene cada dato.

Se espera una fila por producto dispensado. Las filas con el mismo número de autorización (o de
receta) se agrupan en una sola carga; los datos de cabecera se toman de la primera fila del grupo.
Las filas sin ninguno de los dos números se agrupan por afiliado y fecha de dispensa, y la carga se
reconoce por sus datos (ver clave_por_datos).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..modelos import ItemRegistro, RegistroSistema
from ..normalizacion import (
    normalizar_id,
    normalizar_texto,
    parsear_entero,
    parsear_fecha,
    parsear_importe,
    texto_o_none,
)

CAMPOS_TEXTO = (
    "nro_autorizacion",
    "nro_receta",
    "obra_social",
    "plan",
    "nro_afiliado",
    "afiliado_nombre",
    "medico_matricula",
)
CAMPOS_FECHA = ("fecha_prescripcion", "fecha_dispensa")
CAMPOS_IMPORTE = ("importe_total", "importe_obra_social")
CAMPOS_ITEM_TEXTO = ("item_descripcion", "item_monodroga", "item_troquel", "item_codigo_barras")
CAMPOS_ITEM_IMPORTE = ("item_importe", "item_cobertura_pct")
CAMPOS_VALIDOS = set(
    CAMPOS_TEXTO + CAMPOS_FECHA + CAMPOS_IMPORTE + CAMPOS_ITEM_TEXTO + CAMPOS_ITEM_IMPORTE + ("item_cantidad",)
)


class ErrorImportacion(ValueError):
    pass


@dataclass(frozen=True)
class MapeoArchivo:
    nombre: str
    columnas: dict[str, str]  # campo de Gestifarma -> encabezado de la columna en el archivo
    descripcion: str = ""
    delimitador: str = ";"
    encoding: str = "utf-8-sig"
    formato_fecha: str | None = None
    separador_decimal: str = ","
    hoja: str | None = None
    portal: dict = field(default_factory=dict)  # configuración opcional del robot (ver portal_web.py)

    @classmethod
    def desde_toml(cls, ruta: Path) -> MapeoArchivo:
        with ruta.open("rb") as f:
            datos = tomllib.load(f)
        columnas = datos.get("columnas", {})
        desconocidos = set(columnas) - CAMPOS_VALIDOS
        if desconocidos:
            raise ErrorImportacion(f"{ruta}: campos desconocidos en [columnas]: {sorted(desconocidos)}")
        if "item_descripcion" not in columnas:
            raise ErrorImportacion(f"{ruta}: falta la columna obligatoria item_descripcion en [columnas]")
        archivo = datos.get("archivo", {})
        return cls(
            nombre=datos.get("nombre", ruta.stem),
            descripcion=datos.get("descripcion", ""),
            columnas=columnas,
            delimitador=archivo.get("delimitador", ";"),
            encoding=archivo.get("encoding", "utf-8-sig"),
            formato_fecha=archivo.get("formato_fecha") or None,
            separador_decimal=archivo.get("separador_decimal", ","),
            hoja=archivo.get("hoja") or None,
            portal=datos.get("portal", {}),
        )


def cargar_fuentes(directorio: Path) -> dict[str, MapeoArchivo]:
    """Todas las fuentes configuradas en config/fuentes/*.toml, por nombre."""
    fuentes = {}
    for ruta in sorted(directorio.glob("*.toml")) if directorio.exists() else []:
        mapeo = MapeoArchivo.desde_toml(ruta)
        fuentes[mapeo.nombre] = mapeo
    return fuentes


@dataclass
class LecturaArchivo:
    registros: list[RegistroSistema]
    filas: int
    errores: list[str]


def leer_archivo(ruta: Path, mapeo: MapeoArchivo) -> LecturaArchivo:
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        encabezados, filas = _leer_excel(ruta, mapeo)
    else:
        encabezados, filas = _leer_csv(ruta, mapeo)

    # Los encabezados se buscan sin importar mayúsculas, acentos ni espacios.
    por_normalizado = {normalizar_texto(e): e for e in encabezados if e}
    columnas: dict[str, str] = {}
    faltantes = []
    for campo, encabezado in mapeo.columnas.items():
        real = por_normalizado.get(normalizar_texto(encabezado))
        if real is None:
            faltantes.append(encabezado)
        else:
            columnas[campo] = real
    if faltantes:
        raise ErrorImportacion(
            f"Al archivo le faltan columnas del formato «{mapeo.nombre}»: {', '.join(faltantes)}. "
            f"Columnas encontradas: {', '.join(e for e in encabezados if e)}."
        )

    grupos: dict[str, RegistroSistema] = {}
    errores: list[str] = []
    leidas = 0
    for numero, fila in enumerate(filas, start=2):  # la fila 1 son los encabezados
        if all(texto_o_none(v) is None for v in fila.values()):
            continue
        leidas += 1
        valores = {campo: fila.get(columna) for campo, columna in columnas.items()}
        try:
            cabecera, item = _interpretar(valores, mapeo)
        except ValueError as exc:
            errores.append(f"Fila {numero}: {exc}")
            continue
        clave = _clave(cabecera)
        clave_grupo = clave or "|".join(
            ["SIN-CLAVE", normalizar_id(cabecera.get("nro_afiliado")), str(cabecera.get("fecha_dispensa"))]
        )
        registro = grupos.get(clave_grupo)
        if registro is None:
            registro = RegistroSistema(fuente=mapeo.nombre, clave=clave, datos_originales=[], items=[], **cabecera)
            grupos[clave_grupo] = registro
        if item is not None:
            registro.items.append(item)
        registro.datos_originales.append({k: texto_o_none(v) for k, v in fila.items() if k})
    for registro in grupos.values():
        if registro.clave is None:  # recién ahora la carga tiene todos sus productos
            registro.clave = clave_por_datos(registro)
    return LecturaArchivo(registros=list(grupos.values()), filas=leidas, errores=errores)


def _clave(cabecera: dict) -> str | None:
    if normalizar_id(cabecera.get("nro_autorizacion")):
        return "AUT:" + normalizar_id(cabecera["nro_autorizacion"])
    if normalizar_id(cabecera.get("nro_receta")):
        return "REC:" + normalizar_id(cabecera["nro_receta"])
    return None


def clave_por_datos(registro: RegistroSistema) -> str:
    """Clave de respaldo de una carga sin número de autorización ni de receta: un hash de la fuente, el
    afiliado, las fechas y los productos con sus cantidades, normalizados (no cambia con mayúsculas, acentos,
    signos ni con el orden de los productos). Al volver a importar el mismo reporte, la carga se reemplaza en vez
    de duplicarse. Si en el sistema se corrige uno de esos datos, es otra clave y la carga anterior queda.

    Las claves quedan guardadas: si se cambia qué datos entran acá, las cargas ya importadas dejan de
    reconocerse y la próxima importación las duplica."""
    productos = sorted((normalizar_texto(item.descripcion), str(item.cantidad)) for item in registro.items)
    datos = [
        registro.fuente,
        normalizar_id(registro.nro_afiliado),
        registro.fecha_prescripcion,
        registro.fecha_dispensa,
        productos,
    ]
    return "DAT:" + hashlib.sha256(json.dumps(datos, default=str).encode()).hexdigest()


def _interpretar(valores: dict, mapeo: MapeoArchivo) -> tuple[dict, ItemRegistro | None]:
    cabecera: dict = {}
    for campo in CAMPOS_TEXTO:
        if campo in valores:
            cabecera[campo] = texto_o_none(valores[campo])
    for campo in CAMPOS_FECHA:
        if campo in valores:
            cabecera[campo] = _con_campo(campo, parsear_fecha, valores[campo], mapeo.formato_fecha)
    for campo in CAMPOS_IMPORTE:
        if campo in valores:
            cabecera[campo] = _con_campo(campo, parsear_importe, valores[campo], mapeo.separador_decimal)

    descripcion = texto_o_none(valores.get("item_descripcion"))
    if descripcion is None:
        return cabecera, None
    item = ItemRegistro(
        descripcion=descripcion,
        monodroga=texto_o_none(valores.get("item_monodroga")),
        troquel=texto_o_none(valores.get("item_troquel")),
        codigo_barras=texto_o_none(valores.get("item_codigo_barras")),
        cantidad=_con_campo("item_cantidad", parsear_entero, valores.get("item_cantidad")),
        importe=_con_campo("item_importe", parsear_importe, valores.get("item_importe"), mapeo.separador_decimal),
        cobertura_pct=_con_campo(
            "item_cobertura_pct", parsear_importe, valores.get("item_cobertura_pct"), mapeo.separador_decimal
        ),
    )
    return cabecera, item


def _con_campo(campo: str, funcion, *argumentos):
    try:
        return funcion(*argumentos)
    except ValueError as exc:
        raise ValueError(f"{campo}: {exc}") from exc


def _leer_csv(ruta: Path, mapeo: MapeoArchivo) -> tuple[list[str], list[dict]]:
    crudo = ruta.read_bytes()
    try:
        texto = crudo.decode(mapeo.encoding)
    except UnicodeDecodeError:
        texto = crudo.decode("latin-1")  # muchos sistemas viejos exportan en Latin-1 / Windows-1252
    lector = csv.DictReader(io.StringIO(texto), delimiter=mapeo.delimitador)
    encabezados = [(e or "").strip() for e in (lector.fieldnames or [])]
    lector.fieldnames = encabezados
    return encabezados, list(lector)


def _leer_excel(ruta: Path, mapeo: MapeoArchivo) -> tuple[list[str], list[dict]]:
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        if mapeo.hoja:
            if mapeo.hoja not in libro.sheetnames:
                raise ErrorImportacion(
                    f"El Excel no tiene la hoja «{mapeo.hoja}». Hojas: {', '.join(libro.sheetnames)}"
                )
            hoja = libro[mapeo.hoja]
        else:
            hoja = libro.worksheets[0]
        filas = hoja.iter_rows(values_only=True)
        encabezados = [str(c).strip() if c is not None else "" for c in next(filas, ())]
        return encabezados, [dict(zip(encabezados, fila)) for fila in filas]
    finally:
        libro.close()
