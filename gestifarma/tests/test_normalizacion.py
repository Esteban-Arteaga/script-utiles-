from datetime import date, datetime
from decimal import Decimal

import pytest

from gestifarma.normalizacion import (
    concentraciones,
    normalizar_id,
    normalizar_matricula,
    parsear_entero,
    parsear_fecha,
    parsear_importe,
    similitud_nombres,
    similitud_productos,
)


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("000123", "123"),
        ("12.345.678/00", "1234567800"),
        (" aut-0098123 ", "AUT0098123"),
        (15012345678900.0, "15012345678900"),  # número que Excel convirtió en float
        (None, ""),
        ("000", "0"),
    ],
)
def test_normalizar_id(valor, esperado):
    assert normalizar_id(valor) == esperado


def test_normalizar_matricula_ignora_prefijo():
    assert normalizar_matricula("M.P. 012345") == normalizar_matricula("MN 12345") == "12345"


@pytest.mark.parametrize(
    "valor", ["03/11/2026", "03/11/26", "2026-11-03", "03-11-2026", "03/11/2026 14:35", datetime(2026, 11, 3, 9, 0)]
)
def test_parsear_fecha_dia_primero(valor):
    assert parsear_fecha(valor) == date(2026, 11, 3)


def test_parsear_fecha_invalida():
    assert parsear_fecha("") is None
    with pytest.raises(ValueError):
        parsear_fecha("31/02/2026")


@pytest.mark.parametrize(
    ("valor", "separador", "esperado"),
    [
        ("$ 1.234,56", ",", Decimal("1234.56")),
        ("1234,5", ",", Decimal("1234.50")),
        (9850.0, ",", Decimal("9850.00")),
        ("1234.56", "auto", Decimal("1234.56")),
        ("1.234", "auto", Decimal("1234.00")),
        ("1.234,56", "auto", Decimal("1234.56")),
        ("", "auto", None),
    ],
)
def test_parsear_importe(valor, separador, esperado):
    assert parsear_importe(valor, separador) == esperado


def test_parsear_entero():
    assert parsear_entero("2") == parsear_entero("2,0") == parsear_entero(2.0) == 2
    assert parsear_entero("") is None
    with pytest.raises(ValueError):
        parsear_entero("dos")


def test_similitud_nombres_tolera_orden_iniciales_y_segundos_nombres():
    assert similitud_nombres("GOMEZ, María Elena", "MARIA ELENA GOMEZ") == 1.0
    assert similitud_nombres("Fernandez Ana", "FERNANDEZ ANA MARIA") == 1.0
    assert similitud_nombres("J. Perez", "PEREZ JUAN") == 1.0
    assert similitud_nombres("Fernandes Ana", "FERNANDEZ ANA") > 0.85
    assert similitud_nombres("Gomez Maria", "Rodriguez Carlos") < 0.6


def test_similitud_productos():
    assert similitud_productos("Amoxi 500", "AMOXICILINA 500 MG CAPS X 16") >= 0.85
    # Nombre comercial: se compara contra la monodroga si el reporte la trae.
    assert similitud_productos("Ibuprofeno 600", "MARCA X 600 COMP", "IBUPROFENO") == 1.0
    # Una combinación de drogas no es lo mismo que una sola droga: queda en la zona "a revisar".
    combinada = similitud_productos("Amoxicilina 875 mg", "AMOXICILINA + ACIDO CLAVULANICO 875 MG")
    assert 0.5 <= combinada < 0.85
    assert similitud_productos("Enalapril 10 mg", "IBUPROFENO 600 MG") < 0.5


def test_concentraciones():
    assert concentraciones("Levotiroxina 50 mcg") == {(Decimal("50"), "MCG")}
    assert concentraciones("Levotiroxina 50 µg") == {(Decimal("50"), "MCG")}
    assert concentraciones("Enalapril 10mg x 30") == {(Decimal("10"), "MG")}
    assert concentraciones("Amoxicilina 0,5 g") == {(Decimal("0.5"), "G")}
    assert concentraciones("Omeprazol") == set()
