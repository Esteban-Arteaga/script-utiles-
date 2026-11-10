from datetime import date, datetime
from decimal import Decimal

import pytest
from fabricas import RAIZ
from openpyxl import Workbook
from sqlalchemy import func, select

from gestifarma import servicios
from gestifarma.conectores import ErrorImportacion, MapeoArchivo, cargar_fuentes, leer_archivo
from gestifarma.db import crear_engine, crear_sesiones, inicializar
from gestifarma.modelos import RegistroSistema

REPORTE = RAIZ / "ejemplos" / "reporte_colegio_ejemplo.csv"
ENCABEZADOS = REPORTE.read_text(encoding="utf-8").splitlines()[0]


@pytest.fixture
def mapeo() -> MapeoArchivo:
    return cargar_fuentes(RAIZ / "config" / "fuentes")["colegio-ejemplo"]


def test_lee_el_reporte_de_ejemplo_y_agrupa_por_autorizacion(mapeo):
    lectura = leer_archivo(REPORTE, mapeo)
    assert lectura.errores == []
    assert lectura.filas == 8
    assert len(lectura.registros) == 7  # dos filas son productos de la misma carga
    martinez = next(r for r in lectura.registros if r.afiliado_nombre == "MARTINEZ SUSANA")
    assert martinez.clave == "AUT:98155"
    assert [i.cantidad for i in martinez.items] == [2, 1]
    assert martinez.items[0].importe == Decimal("12300.00")
    assert martinez.fecha_prescripcion == date(2026, 11, 1)
    sin_numeros = next(r for r in lectura.registros if r.afiliado_nombre == "FERNANDEZ ANA MARIA")
    assert sin_numeros.clave is None


def test_columnas_faltantes_da_un_error_claro(tmp_path, mapeo):
    archivo = tmp_path / "otro.csv"
    archivo.write_text("Fecha;Producto\n01/11/2026;ALGO\n", encoding="utf-8")
    with pytest.raises(ErrorImportacion, match="Nro Autorizacion"):
        leer_archivo(archivo, mapeo)


def test_una_fila_con_error_se_informa_y_no_frena_el_resto(tmp_path, mapeo):
    filas = REPORTE.read_text(encoding="utf-8").splitlines()
    filas[1] = filas[1].replace("02/11/2026", "31/02/2026")
    archivo = tmp_path / "con_error.csv"
    archivo.write_text("\n".join(filas), encoding="utf-8")
    lectura = leer_archivo(archivo, mapeo)
    assert len(lectura.registros) == 6
    assert lectura.errores and lectura.errores[0].startswith("Fila 2: fecha_prescripcion")


def test_reporte_en_latin1(tmp_path, mapeo):
    archivo = tmp_path / "latin1.csv"
    fila = ";;OSPE;;60-1;FERNÁNDEZ ÑANDÚ;1;04/11/2026;07/11/2026;OMEPRAZOL 20 MG;;;;1;;"
    archivo.write_bytes(f"{ENCABEZADOS}\n{fila}\n".encode("latin-1"))
    (registro,) = leer_archivo(archivo, mapeo).registros
    assert registro.afiliado_nombre == "FERNÁNDEZ ÑANDÚ"


def test_reporte_en_excel(tmp_path, mapeo):
    libro = Workbook()
    hoja = libro.active
    hoja.append(ENCABEZADOS.split(";"))
    # En Excel los números y fechas vienen tipados (y los números largos como float).
    hoja.append(
        [
            98123,
            None,
            "PAMI",
            None,
            123456789012.0,
            "GOMEZ MARIA",
            12345,
            datetime(2026, 11, 2),
            datetime(2026, 11, 4),
            "ENALAPRIL 10 MG",
            "ENALAPRIL",
            4123456,
            None,
            1,
            9850.5,
            100,
        ]
    )
    archivo = tmp_path / "reporte.xlsx"
    libro.save(archivo)
    (registro,) = leer_archivo(archivo, mapeo).registros
    assert registro.nro_afiliado == "123456789012"
    assert registro.nro_autorizacion == "98123"
    assert registro.fecha_dispensa == date(2026, 11, 4)
    assert registro.items[0].troquel == "4123456"
    assert registro.items[0].importe == Decimal("9850.50")


def test_reimportar_reemplaza_las_cargas_existentes(tmp_path, mapeo):
    engine = crear_engine(f"sqlite:///{tmp_path / 'prueba.db'}")
    inicializar(engine)
    sesiones = crear_sesiones(engine)
    with sesiones() as sesion:
        servicios.importar(sesion, REPORTE, REPORTE.name, mapeo)
        servicios.importar(sesion, REPORTE, REPORTE.name, mapeo)
        total = sesion.scalar(select(func.count()).select_from(RegistroSistema))
    # 6 cargas con número se reemplazan; la que no tiene número no se puede identificar y se duplica.
    assert total == 8
