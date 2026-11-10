from datetime import date

import pytest
from fabricas import RAIZ, nueva_receta, nuevo_registro

from gestifarma.conciliacion import Reglas, Resultado, Severidad, conciliar
from gestifarma.conciliacion.motor import Criterio


@pytest.fixture
def reglas() -> Reglas:
    return Reglas.desde_toml(RAIZ / "config" / "reglas.toml")


def cruzar(receta, registro, reglas):
    (resultado,) = conciliar([receta], [registro], reglas)
    return resultado


def mensajes(resultado, severidad=None):
    return [h.mensaje for h in resultado.hallazgos if severidad is None or h.severidad == severidad]


def test_receta_igual_a_la_carga_da_ok(reglas):
    resultado = cruzar(nueva_receta(), nuevo_registro(), reglas)
    assert resultado.resultado == Resultado.OK, mensajes(resultado)
    assert resultado.criterio == Criterio.AUTORIZACION


def test_autorizacion_con_ceros_adelante_y_alias_de_obra_social(reglas):
    resultado = cruzar(nueva_receta(nro_autorizacion="0098123"), nuevo_registro(obra_social="INSSJP"), reglas)
    assert resultado.resultado == Resultado.OK, mensajes(resultado)


def test_obra_social_distinta_es_error(reglas):
    resultado = cruzar(nueva_receta(), nuevo_registro(obra_social="OSDE"), reglas)
    assert resultado.resultado == Resultado.CON_DIFERENCIAS
    assert any("obra social" in m for m in mensajes(resultado, Severidad.ERROR))


def test_afiliado_distinto_es_error(reglas):
    resultado = cruzar(nueva_receta(nro_afiliado="123456789013/00"), nuevo_registro(), reglas)
    assert resultado.resultado == Resultado.CON_DIFERENCIAS
    assert "El número de afiliado no coincide." in mensajes(resultado, Severidad.ERROR)


def test_solo_cambia_el_sufijo_de_parentesco_es_advertencia(reglas):
    resultado = cruzar(nueva_receta(nro_afiliado="123456789012/01"), nuevo_registro(), reglas)
    assert resultado.resultado == Resultado.OBSERVADA
    assert any("sufijo" in m for m in mensajes(resultado, Severidad.ADVERTENCIA))


def test_nombre_del_afiliado(reglas):
    parecido = cruzar(nueva_receta(afiliado_nombre="Gimenez Maria"), nuevo_registro(), reglas)
    assert parecido.resultado == Resultado.OBSERVADA
    distinto = cruzar(nueva_receta(afiliado_nombre="Rodriguez Carlos"), nuevo_registro(), reglas)
    assert distinto.resultado == Resultado.CON_DIFERENCIAS


def test_matricula_distinta_es_error(reglas):
    resultado = cruzar(nueva_receta(medico_matricula="MP 99999"), nuevo_registro(), reglas)
    assert "La matrícula del médico no coincide." in mensajes(resultado, Severidad.ERROR)


def test_receta_vencida_al_dispensar(reglas):
    resultado = cruzar(
        nueva_receta(fecha_prescripcion=date(2026, 9, 20)),
        nuevo_registro(fecha_prescripcion=date(2026, 9, 20), fecha_dispensa=date(2026, 11, 3)),
        reglas,
    )
    assert any("vencida" in m and "44 días" in m for m in mensajes(resultado, Severidad.ERROR))


def test_vigencia_configurable_por_obra_social(reglas):
    receta = nueva_receta(obra_social="Obra Social Ejemplo", fecha_prescripcion=date(2026, 9, 20), diagnostico="HTA")
    registro = nuevo_registro(
        obra_social="OBRA SOCIAL EJEMPLO", fecha_prescripcion=date(2026, 9, 20), fecha_dispensa=date(2026, 11, 3)
    )
    assert cruzar(receta, registro, reglas).resultado == Resultado.OK  # esa OS acepta 60 días


def test_dispensa_anterior_a_la_prescripcion(reglas):
    resultado = cruzar(nueva_receta(), nuevo_registro(fecha_dispensa=date(2026, 11, 1)), reglas)
    assert any("anterior" in m for m in mensajes(resultado, Severidad.ERROR))


def test_fecha_de_prescripcion_cargada_distinta(reglas):
    resultado = cruzar(nueva_receta(), nuevo_registro(fecha_prescripcion=date(2026, 11, 3)), reglas)
    assert any("fecha de prescripción cargada" in m for m in mensajes(resultado, Severidad.ERROR))


def test_cantidad_mayor_a_la_recetada_y_producto_que_no_figura(reglas):
    registro = nuevo_registro(
        items=[
            {"descripcion": "ENALAPRIL 10 MG COMP X 30", "cantidad": 2},
            {"descripcion": "IBUPROFENO 600 MG COMP X 10", "cantidad": 1},
        ]
    )
    resultado = cruzar(nueva_receta(), registro, reglas)
    errores = mensajes(resultado, Severidad.ERROR)
    assert any("Se cargaron 2" in m for m in errores)
    assert any("IBUPROFENO" in m and "no figura" in m for m in errores)


def test_medicamento_recetado_no_cargado_es_informativo(reglas):
    receta = nueva_receta(
        items=[{"descripcion": "Enalapril 10 mg", "cantidad": 1}, {"descripcion": "Omeprazol 20 mg", "cantidad": 1}]
    )
    resultado = cruzar(receta, nuevo_registro(), reglas)
    assert resultado.resultado == Resultado.OK
    assert any("Omeprazol" in m for m in mensajes(resultado, Severidad.INFO))


def test_concentracion_distinta_es_error(reglas):
    registro = nuevo_registro(items=[{"descripcion": "ENALAPRIL 20 MG COMP X 30", "cantidad": 1}])
    resultado = cruzar(nueva_receta(), registro, reglas)
    assert any("concentración" in m for m in mensajes(resultado, Severidad.ERROR))


def test_troquel_distinto_es_error_y_troquel_igual_empareja(reglas):
    receta = nueva_receta(items=[{"descripcion": "Enalapril 10 mg", "cantidad": 1, "troquel": "4123456"}])
    distinto = nuevo_registro(items=[{"descripcion": "ENALAPRIL 10 MG", "cantidad": 1, "troquel": "4123457"}])
    assert any("troquel" in m for m in mensajes(cruzar(receta, distinto, reglas), Severidad.ERROR))
    # Con el mismo troquel se empareja aunque el nombre comercial no se parezca a la droga.
    igual = nuevo_registro(items=[{"descripcion": "MARCA X 10 MG", "cantidad": 1, "troquel": "4123456"}])
    assert cruzar(receta, igual, reglas).resultado == Resultado.OK


def test_combinacion_de_drogas_queda_para_revisar(reglas):
    receta = nueva_receta(items=[{"descripcion": "Amoxicilina 875 mg", "cantidad": 1}])
    registro = nuevo_registro(items=[{"descripcion": "AMOXICILINA + ACIDO CLAVULANICO 875 MG", "cantidad": 1}])
    resultado = cruzar(receta, registro, reglas)
    assert resultado.resultado == Resultado.OBSERVADA
    assert any("Verificar" in m for m in mensajes(resultado, Severidad.ADVERTENCIA))


def test_firmas(reglas):
    sin_firma = cruzar(nueva_receta(firma_medico=False), nuevo_registro(), reglas)
    assert "Falta la firma del médico." in mensajes(sin_firma, Severidad.ERROR)
    sin_dorso = cruzar(nueva_receta(firma_afiliado=None), nuevo_registro(), reglas)
    assert sin_dorso.resultado == Resultado.OBSERVADA


def test_demasiados_medicamentos(reglas):
    items = [
        {"descripcion": d, "cantidad": 1} for d in ("Enalapril 10 mg", "Omeprazol 20 mg", "Losartan 50", "Aspirina 100")
    ]
    resultado = cruzar(nueva_receta(items=items), nuevo_registro(), reglas)
    assert any("máximo" in m for m in mensajes(resultado, Severidad.ERROR))


def test_lectura_dudosa_se_aclara_en_el_mensaje(reglas):
    receta = nueva_receta(nro_afiliado="123456789013/00", campos_dudosos=["nro_afiliado"])
    resultado = cruzar(receta, nuevo_registro(), reglas)
    assert any("dudosa" in m for m in mensajes(resultado, Severidad.ERROR))


def test_emparejamiento_por_afiliado_y_fecha_sin_numeros(reglas):
    receta = nueva_receta(nro_autorizacion=None)
    otra_del_mismo_afiliado = nuevo_registro(
        nro_autorizacion=None,
        fecha_prescripcion=date(2026, 10, 1),
        fecha_dispensa=date(2026, 10, 2),
        items=[{"descripcion": "LOSARTAN 50 MG", "cantidad": 1}],
    )
    la_correcta = nuevo_registro(nro_autorizacion=None)
    resultados = conciliar([receta], [otra_del_mismo_afiliado, la_correcta], reglas)
    emparejado = next(r for r in resultados if r.receta is not None)
    assert emparejado.registro is la_correcta
    assert emparejado.criterio == Criterio.AFILIADO_FECHA
    sobrante = next(r for r in resultados if r.receta is None)
    assert sobrante.resultado == Resultado.REGISTRO_SIN_RECETA


def test_receta_sin_carga_y_carga_sin_receta(reglas):
    receta = nueva_receta(nro_autorizacion="1", nro_afiliado="999")
    registro = nuevo_registro(nro_autorizacion="2")
    resultados = {r.resultado for r in conciliar([receta], [registro], reglas)}
    assert resultados == {Resultado.RECETA_SIN_REGISTRO, Resultado.REGISTRO_SIN_RECETA}


def test_reglas_rechazan_claves_desconocidas(tmp_path):
    archivo = tmp_path / "reglas.toml"
    archivo.write_text("[general]\nexigir_firma_medicoo = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exigir_firma_medicoo"):
        Reglas.desde_toml(archivo)
