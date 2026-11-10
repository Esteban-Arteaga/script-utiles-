"""Datos de la receta a partir del texto leído sin IA, buscando etiquetas ("Afiliado:", "M.P.", "Fecha:").

Es una lectura aproximada para mostrar algo en la bandeja y precargar el formulario. La conciliación de
las recetas leídas sin IA no depende de esto: busca en el texto los datos cargados en el sistema
(ver conciliacion/verificacion.py).
"""

from __future__ import annotations

import re

from ..busqueda import cantidad_en, corregir_numeros, fechas
from ..normalizacion import concentraciones, parsear_importe, sin_acentos
from .esquema import ExtraccionReceta, ItemExtraido

_NUMERO = r"([0-9][0-9 ./\-]{2,}[0-9])"
_ETIQUETA_NRO = r"(?:N(?:RO|ro|°|º|UM|um)?\.?\s*(?:DE\s+|de\s+)?)?"
_PALABRAS_DE_ETIQUETA = re.compile(
    r"FECHA|AFILIADO|BENEFICIARIO|DNI|OBRA SOCIAL|MATRICULA|DIAGNOSTICO|RECETA|AUTORIZ|TOTAL|DR\.?\s", re.I
)


def _lineas(texto: str) -> list[str]:
    return [sin_acentos(linea).strip() for linea in texto.splitlines() if linea.strip()]


def _tras_etiqueta(etiqueta: str, valor: str, lineas: list[str]) -> str | None:
    patron = re.compile(rf"(?:^|\b){etiqueta}\s*[:.\-]?\s*{valor}", re.I)
    for linea in lineas:
        coincidencia = patron.search(linea)
        if coincidencia:
            return coincidencia.group(1).strip(" :.-,")
    return None


def _sin_espacios_en_numero(valor: str | None) -> str | None:
    """ "12345678901 2/00" -> "123456789012/00" (el OCR a veces corta los números)."""
    if valor is None:
        return None
    return re.sub(r"(?<=[\d/.\-])\s+(?=[\d/.\-])", "", corregir_numeros(valor))


def _fecha_con_etiqueta(lineas: list[str]):
    for linea in lineas:
        if re.search(r"FECHA", linea, re.I):
            encontradas = fechas(linea)
            if encontradas:
                return encontradas[0]
    return None


def _importe(etiqueta: str, lineas: list[str]):
    valor = _tras_etiqueta(etiqueta, r"\$?\s*([\d.]+,\d{2})", lineas)
    try:
        return float(parsear_importe(valor)) if valor else None
    except ValueError:
        return None


def _items(lineas: list[str]) -> list[ItemExtraido]:
    """Renglones con una concentración ("Enalapril 10 mg x 30 comp") que no son etiquetas."""
    items = []
    for i, linea in enumerate(lineas):
        if not concentraciones(corregir_numeros(linea)) or _PALABRAS_DE_ETIQUETA.search(linea):
            continue
        if not re.search(r"[A-Za-z]{4,}", linea):
            continue
        descripcion = re.sub(r"^(?:RP\s*/?|\d+[.)-])\s*", "", linea, flags=re.I).strip()
        items.append(ItemExtraido(descripcion=descripcion, cantidad=cantidad_en("\n".join(lineas[i : i + 2]))))
    return items[:5]


def extraer_campos(frente: str, dorso: str) -> ExtraccionReceta:
    """Datos de la receta (frente) y del ticket o troqueles (dorso) a partir del texto leído."""
    lineas, lineas_dorso = _lineas(frente), _lineas(dorso)
    obra_social = _tras_etiqueta(r"(?:OBRA\s+SOCIAL|PREPAGA|COBERTURA)", r"([A-Za-z][A-Za-z0-9 .]{1,40})", lineas)
    obra_social = obra_social.upper() if obra_social else None
    matricula = None
    coincidencia = re.search(r"\bM\.?\s*([PN])\.?\s*:?\s*(\d{3,7})\b", "\n".join(lineas), re.I)
    if coincidencia:
        matricula = f"M{coincidencia.group(1).upper()} {coincidencia.group(2)}"
    else:
        numero = _tras_etiqueta(r"MAT(?:RICULA)?\.?\s*(?:N[°º]?)?", r"(\d{3,7})", lineas)
        matricula = numero
    medico = _tras_etiqueta(r"DRA?\.", r"([A-Za-z][A-Za-z .,']{3,60}?)(?:\s*-|$)", lineas)
    fechas_frente = fechas(frente)

    datos = ExtraccionReceta(
        es_receta=True,
        tipo_receta="otro",
        obra_social=obra_social,
        nro_afiliado=_sin_espacios_en_numero(
            _tras_etiqueta(rf"{_ETIQUETA_NRO}(?:AFILIADO|BENEFICIARIO|CREDENCIAL)", _NUMERO, lineas)
        ),
        afiliado_nombre=_tras_etiqueta(
            r"(?:AFILIADO|PACIENTE|BENEFICIARIO|NOMBRE)", r"([A-Za-z][A-Za-z ,.']{2,60})$", lineas
        ),
        afiliado_dni=_sin_espacios_en_numero(_tras_etiqueta(r"D\.?N\.?I\.?", r"([0-9][0-9 .]{5,}[0-9])", lineas)),
        medico_nombre=medico,
        medico_matricula=matricula,
        fecha_prescripcion=_fecha_con_etiqueta(lineas) or (fechas_frente[0] if fechas_frente else None),
        fecha_dispensa=_fecha_con_etiqueta(lineas_dorso),
        nro_receta=_sin_espacios_en_numero(_tras_etiqueta(rf"{_ETIQUETA_NRO}RECETA", _NUMERO, lineas)),
        nro_autorizacion=_sin_espacios_en_numero(
            _tras_etiqueta(
                r"(?:AUTORIZACION|VALIDACION|COD(?:IGO)?\.?\s+AUT\.?)", r"([0-9][0-9 ]{2,}[0-9])", lineas + lineas_dorso
            )
        ),
        diagnostico=_tras_etiqueta(r"(?:DIAGNOSTICO|DX)", r"([A-Za-z0-9][^\n]{1,80})", lineas),
        importe_total=_importe(r"TOTAL", lineas_dorso),
        importe_obra_social=_importe(r"A\s+CARGO\s+(?:DE\s+LA\s+)?(?:OS|O\.S\.|OBRA\s+SOCIAL)", lineas_dorso),
        items=_items(lineas),
    )
    faltantes = [
        campo
        for campo in ("obra_social", "nro_afiliado", "afiliado_nombre", "medico_matricula", "fecha_prescripcion")
        if getattr(datos, campo) is None
    ]
    datos.campos_dudosos = faltantes + ["firma_medico", "sello_medico"] + (["items"] if not datos.items else [])
    return datos
