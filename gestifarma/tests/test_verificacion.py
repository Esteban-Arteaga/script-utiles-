from datetime import date

import pytest
from fabricas import RAIZ, nuevo_registro

from gestifarma.conciliacion import Reglas, Resultado, Severidad, conciliar
from gestifarma.conciliacion.motor import Criterio
from gestifarma.conciliacion.verificacion import TextoReceta, verificar
from gestifarma.modelos import EstadoReceta, Receta

FRENTE = """RECETA - OBRA SOCIAL: PAMI
Nro de receta: 0001-00098123
Afiliado: GOMEZ, MARIA ELENA
Nro de afiliado: 12345678901 2/00
Fecha: 02/11/2026
Rp/ Enalapril 10 mg x 30 comp.
Cantidad: 1 (un) envase
Dr. JUAN PEREZ - MP 12345"""

TICKET = """TICKET DE VALIDACION
Autorizacion: 0098123
Afiliado: 123456789012/00"""


@pytest.fixture
def reglas() -> Reglas:
    return Reglas.desde_toml(RAIZ / "config" / "reglas.toml")


def verificar_texto(reglas, frente=FRENTE, dorso="", codigos=(), **cambios_registro):
    registro = nuevo_registro(obra_social="INSSJP", **cambios_registro)
    return verificar(TextoReceta(frente, dorso, list(codigos)), registro, reglas, {"INSSJP", "OSDE"})


def mensajes(verificacion, severidad):
    return [h.mensaje for h in verificacion.hallazgos if h.severidad == severidad]


def test_todo_confirmado(reglas):
    v = verificar_texto(reglas)
    assert v.hallazgos == []
    assert v.confirmados[:5] == [
        "obra social",
        "número de afiliado",
        "nombre del afiliado",
        "matrícula del médico",
        "fecha de prescripción",
    ]
    assert v.valores["nro_afiliado"] == "123456789012/00"


def test_un_digito_distinto_es_posible_diferencia(reglas):
    v = verificar_texto(reglas, nro_afiliado="123456789013/00")
    assert "Posible diferencia en el número de afiliado." in mensajes(v, Severidad.ERROR)[0]


def test_sufijo_de_parentesco(reglas):
    v = verificar_texto(reglas, nro_afiliado="123456789012/01")
    assert any("sufijo" in m for m in mensajes(v, Severidad.ADVERTENCIA))


def test_el_ticket_del_dorso_no_confirma_los_datos_de_la_receta(reglas):
    """El ticket lo imprime el sistema con lo cargado: no sirve para confirmar la receta."""
    frente_sin_afiliado = FRENTE.replace("Nro de afiliado: 12345678901 2/00", "")
    v = verificar_texto(reglas, frente=frente_sin_afiliado, dorso=TICKET)
    assert "No se pudo confirmar el número de afiliado en la imagen." in mensajes(v, Severidad.ADVERTENCIA)
    assert "número de autorización" in v.confirmados  # la autorización sí sale del ticket


def test_otra_obra_social_en_la_receta(reglas):
    v = verificar_texto(reglas, frente=FRENTE.replace("PAMI", "OSDE"))
    assert any("parece ser de OSDE" in m for m in mensajes(v, Severidad.ERROR))


def test_fecha_cantidad_y_concentracion(reglas):
    items = [{"descripcion": "ENALAPRIL 20 MG COMP X 30", "monodroga": "ENALAPRIL", "cantidad": 2}]
    v = verificar_texto(reglas, fecha_prescripcion=date(2026, 11, 3), items=items)
    errores = mensajes(v, Severidad.ERROR)
    assert any("fecha de la receta parece ser otra" in m for m in errores)
    assert any("concentración recetada" in m for m in errores)
    assert any("Se cargaron 2" in m and "se lee 1" in m for m in errores)


def test_producto_que_no_aparece_queda_para_revisar(reglas):
    items = [{"descripcion": "IBUPROFENO 600 MG", "monodroga": "IBUPROFENO", "cantidad": 1}]
    v = verificar_texto(reglas, items=items)
    assert mensajes(v, Severidad.ERROR) == []
    assert any("IBUPROFENO" in m for m in mensajes(v, Severidad.ADVERTENCIA))


def test_troquel_por_codigo_de_barras(reglas):
    items = [{"descripcion": "ENALAPRIL 10 MG", "monodroga": "ENALAPRIL", "cantidad": 1, "troquel": "4123456"}]
    assert "troquel 4123456" in verificar_texto(reglas, dorso=TICKET, codigos=["4123456"], items=items).confirmados
    otro = verificar_texto(reglas, dorso=TICKET, codigos=["4999999"], items=items)
    assert any("troquel 4123456" in m for m in mensajes(otro, Severidad.ADVERTENCIA))


def test_receta_vencida(reglas):
    v = verificar_texto(reglas, frente=FRENTE.replace("02/11/2026", "20/09/2026"), fecha_prescripcion=date(2026, 9, 20))
    assert any("vencida" in m for m in mensajes(v, Severidad.ERROR))


def receta_leida(frente, dorso="", codigos=()):
    paginas = [
        {"lado": "frente", "texto": frente, "codigos": []},
        {"lado": "dorso", "texto": dorso, "codigos": list(codigos)},
    ]
    return Receta(estado=EstadoReceta.PARA_REVISAR, extraccion={"lector": "local", "paginas": paginas}, items=[])


def test_motor_empareja_por_los_numeros_de_la_imagen(reglas):
    receta = receta_leida(FRENTE)
    otra_carga = nuevo_registro(nro_autorizacion="555", nro_afiliado="999888777666/00", afiliado_nombre="BENITEZ")
    la_suya = nuevo_registro(obra_social="INSSJP")
    resultados = conciliar([receta], [otra_carga, la_suya], reglas)
    emparejado = next(r for r in resultados if r.receta is receta)
    assert emparejado.registro is la_suya and emparejado.criterio == Criterio.EN_IMAGEN
    assert emparejado.resultado == Resultado.OK


def test_dos_recetas_del_mismo_afiliado_desempata_la_fecha(reglas):
    octubre = receta_leida(FRENTE.replace("02/11/2026", "01/10/2026").replace("0001-00098123", ""))
    noviembre = receta_leida(FRENTE.replace("0001-00098123", ""))
    carga_oct = nuevo_registro(
        nro_autorizacion="111", fecha_prescripcion=date(2026, 10, 1), fecha_dispensa=date(2026, 10, 2)
    )
    carga_nov = nuevo_registro(nro_autorizacion="222")
    pares = {id(r.receta): r.registro for r in conciliar([octubre, noviembre], [carga_nov, carga_oct], reglas)}
    assert pares[id(octubre)] is carga_oct and pares[id(noviembre)] is carga_nov


def test_receta_revisada_por_una_persona_se_compara_campo_por_campo(reglas):
    receta = receta_leida(FRENTE)
    receta.estado = EstadoReceta.REVISADA
    assert TextoReceta.de(receta) is None


def test_receta_sin_numeros_conocidos(reglas):
    (resultado, sobrante) = conciliar([receta_leida("texto ilegible")], [nuevo_registro()], reglas)
    assert resultado.resultado == Resultado.RECETA_SIN_REGISTRO
    assert "no aparece el número" in resultado.hallazgos[0].mensaje
    assert sobrante.resultado == Resultado.REGISTRO_SIN_RECETA


def test_plan(reglas):
    con_plan = FRENTE.replace("OBRA SOCIAL: PAMI", "OBRA SOCIAL: PAMI - Plan 210")
    assert "plan" in verificar_texto(reglas, frente=con_plan, plan="PLAN 210").confirmados
    distinto = verificar_texto(reglas, frente=con_plan, plan="PLAN 310")
    assert any("plan de la receta parece ser PLAN 210" in m for m in mensajes(distinto, Severidad.ADVERTENCIA))
    assert not any(
        "plan" in m.lower() for m in mensajes(verificar_texto(reglas, plan="PLAN 310"), Severidad.ADVERTENCIA)
    )
