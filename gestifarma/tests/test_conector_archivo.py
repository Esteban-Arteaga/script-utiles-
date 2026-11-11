import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

import pytest
from fabricas import RAIZ
from openpyxl import Workbook
from sqlalchemy import func, select, update

from gestifarma import servicios
from gestifarma.conciliacion.reglas import Reglas
from gestifarma.conectores import ErrorImportacion, MapeoArchivo, cargar_fuentes, leer_archivo
from gestifarma.db import crear_engine, crear_sesiones, inicializar
from gestifarma.extraccion import ExtraccionReceta
from gestifarma.modelos import Conciliacion, RegistroSistema

REPORTE = RAIZ / "ejemplos" / "reporte_colegio_ejemplo.csv"
ENCABEZADOS = REPORTE.read_text(encoding="utf-8").splitlines()[0]


@pytest.fixture
def mapeo() -> MapeoArchivo:
    return cargar_fuentes(RAIZ / "config" / "fuentes")["colegio-ejemplo"]


@pytest.fixture
def sesiones(tmp_path):
    engine = crear_engine(f"sqlite:///{tmp_path / 'prueba.db'}")
    inicializar(engine)
    yield crear_sesiones(engine)
    engine.dispose()


def cantidad_de_cargas(sesion) -> int:
    return sesion.scalar(select(func.count()).select_from(RegistroSistema))


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
    assert sin_numeros.clave.startswith("DAT:")  # sin autorización ni receta: se reconoce por sus datos
    assert sorted(r.clave for r in lectura.registros if r is not sin_numeros) == [
        "AUT:98123",
        "AUT:98140",
        "AUT:98155",
        "AUT:98170",
        "AUT:98200",
        "REC:45678",
    ]


def test_las_cargas_sin_numeros_se_reconocen_por_sus_datos(tmp_path, mapeo):
    def clave(afiliado="60-33445566-2", dispensa="07/11/2026", productos=(("OMEPRAZOL 20 MG", 1), ("IBUPROFENO", 2))):
        filas = [
            f";;OSPE;;{afiliado};FERNANDEZ ANA MARIA;67890;04/11/2026;{dispensa};{producto};;;;{cantidad};;"
            for producto, cantidad in productos
        ]
        archivo = tmp_path / "reporte.csv"
        archivo.write_text("\n".join([ENCABEZADOS, *filas]), encoding="utf-8")
        (registro,) = leer_archivo(archivo, mapeo).registros
        return registro.clave

    original = clave()
    assert original.startswith("DAT:")
    # Los mismos datos escritos de otra forma y en otro orden: es la misma carga.
    assert clave(afiliado="60 33445566 2", productos=[("Ibuprofeno", 2), ("omeprazol  20 mg", 1)]) == original
    # Otra cantidad, otro producto, otro afiliado u otra fecha: es otra carga.
    assert clave(productos=[("OMEPRAZOL 20 MG", 1), ("IBUPROFENO", 3)]) != original
    assert clave(productos=[("OMEPRAZOL 20 MG", 1), ("PARACETAMOL", 2)]) != original
    assert clave(afiliado="60-33445566-3") != original
    assert clave(dispensa="08/11/2026") != original


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


def test_reimportar_el_mismo_reporte_no_cambia_las_cargas_ni_la_conciliacion(sesiones, mapeo):
    reglas = Reglas.desde_toml(RAIZ / "config" / "reglas.toml")
    with sesiones() as sesion:
        for datos in json.loads((RAIZ / "ejemplos" / "recetas_ejemplo.json").read_text(encoding="utf-8")):
            sesion.add(servicios.receta_desde_extraccion(ExtraccionReceta.model_validate(datos)))
        sesion.commit()

    def importar_y_conciliar():  # cada paso en su propia sesión, como en la app
        with sesiones() as sesion:
            servicios.importar(sesion, REPORTE, REPORTE.name, mapeo)
        with sesiones() as sesion:
            resumen = servicios.conciliar_y_guardar(sesion, reglas)
        with sesiones() as sesion:
            # Lo que muestra la pantalla de conciliación: cada receta con su carga y sus diferencias.
            casos = Counter(
                (
                    c.resultado,
                    c.receta_id,
                    c.registro and c.registro.clave,
                    tuple(sorted(d.campo for d in c.discrepancias)),
                )
                for c in sesion.scalars(select(Conciliacion))
            )
            return cantidad_de_cargas(sesion), resumen.por_resultado, casos

    cargas, resumen, casos = importar_y_conciliar()
    assert cargas == 7
    # La carga sin números (FERNANDEZ ANA MARIA) se reemplaza: no aparece una «carga sin receta» de más.
    assert importar_y_conciliar() == (7, resumen, casos)


def test_reimportar_reemplaza_las_cargas_sin_clave_de_versiones_anteriores(sesiones, mapeo):
    with sesiones() as sesion:
        # Así quedaba la base al importar dos veces el reporte con la versión anterior: la carga sin
        # números, sin clave y duplicada.
        servicios.importar(sesion, REPORTE, REPORTE.name, mapeo)
        sesion.add_all([r for r in leer_archivo(REPORTE, mapeo).registros if r.clave.startswith("DAT:")])
        sesion.flush()
        sesion.execute(update(RegistroSistema).where(RegistroSistema.clave.startswith("DAT:")).values(clave=None))
        sesion.commit()
    with sesiones() as sesion:
        assert cantidad_de_cargas(sesion) == 8
        servicios.importar(sesion, REPORTE, REPORTE.name, mapeo)
        assert cantidad_de_cargas(sesion) == 7
