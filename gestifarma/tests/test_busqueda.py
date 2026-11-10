from datetime import date

from gestifarma.busqueda import (
    Estado,
    buscar_fecha,
    buscar_nombre,
    buscar_numero,
    buscar_producto,
    cantidad_en,
    contiene_frase,
    corregir_numeros,
    fechas,
    numeros,
)

# Así suele devolver el OCR una receta: números cortados, letras por dígitos, renglones mezclados.
TEXTO = """RECETA - OBRA SOCIAL: PAMI
Nro de receta: 0001-000981 23
Afiliado: GOMEZ, MARIA E.
Nro de afiliado: 12345678901 2/00
Fecha: O2/11/2O26
Rp/ Enalapril 1O mg x 30 comp.
Cantidad: 1 (un) envase
Dr. JUAN PEREZ - MP 12345"""


def test_corrige_confusiones_solo_en_numeros():
    assert corregir_numeros("Fecha: O2/11/2O26 SOLO") == "FECHA: 02/11/2026 SOLO"


def test_numeros_une_lo_que_el_ocr_corto():
    candidatos = numeros(TEXTO)
    assert "12345678901200" in candidatos  # "12345678901 2/00"
    assert "98123" in candidatos  # "0001-000981 23"
    assert "12345" in candidatos


def test_buscar_numero():
    assert buscar_numero("123456789012/00", TEXTO).estado == Estado.CONFIRMADO
    assert buscar_numero("0098123", TEXTO).estado == Estado.CONFIRMADO
    parecido = buscar_numero("123456789013/00", TEXTO)
    assert parecido.estado == Estado.PARECIDO and parecido.leido == "12345678901200"
    assert buscar_numero("555444333", TEXTO).estado == Estado.NO_ENCONTRADO
    assert buscar_numero("12", TEXTO).estado == Estado.NO_ENCONTRADO  # demasiado corto para afirmar algo


def test_fechas():
    assert fechas(TEXTO) == [date(2026, 11, 2)]
    assert fechas("vence 5-3-27") == [date(2027, 3, 5)]
    assert buscar_fecha(date(2026, 11, 2), TEXTO).estado == Estado.CONFIRMADO
    otra = buscar_fecha(date(2026, 11, 3), TEXTO)
    assert otra.estado == Estado.PARECIDO and otra.leido == "02/11/2026"
    # Con varias fechas no se sabe cuál es la de la receta: no se afirma una diferencia.
    assert buscar_fecha(date(2026, 11, 3), "Fecha 02/11/2026 Nac 05/06/1950").estado == Estado.NO_ENCONTRADO


def test_buscar_nombre():
    assert buscar_nombre("GOMEZ MARIA ELENA", TEXTO).estado == Estado.CONFIRMADO  # inicial "E."
    assert buscar_nombre("Gomez Maria", "Paciente: MARIA GOMEZ").estado == Estado.CONFIRMADO
    assert buscar_nombre("GOMEZ MARTA", TEXTO).estado == Estado.PARECIDO
    assert buscar_nombre("RODRIGUEZ CARLOS", TEXTO).estado == Estado.NO_ENCONTRADO


def test_buscar_producto_y_cantidad():
    producto = buscar_producto("LOTRIAL 10 MG", "ENALAPRIL", TEXTO)
    assert producto.estado == Estado.CONFIRMADO and producto.linea == 5
    assert buscar_producto("IBUPROFENO 600 MG", None, TEXTO).estado == Estado.NO_ENCONTRADO
    combinada = buscar_producto("AMOX + CLAV", "ENALAPRIL HIDROCLOROTIAZIDA", TEXTO)
    assert combinada.estado == Estado.PARECIDO
    assert cantidad_en("Cantidad: 1 (un) envase") == 1
    assert cantidad_en("Amoxicilina 500 x 16 - 2 envases") == 2
    assert cantidad_en("Losartan 50 mg (dos)") == 2
    assert cantidad_en("Enalapril 10 mg x 30 comp") is None  # "x 30" es la presentación, no la cantidad


def test_contiene_frase():
    assert contiene_frase("PAMI", TEXTO)
    assert not contiene_frase("PAM", TEXTO)
    assert contiene_frase("obra social", TEXTO)
