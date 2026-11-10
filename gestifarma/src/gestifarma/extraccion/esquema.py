"""Qué datos se le piden a la IA de cada receta (esquema JSON) y cómo se validan.

El esquema se manda a la API como "structured output": la respuesta siempre respeta este formato.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

CampoDudoso = Literal[
    "obra_social",
    "plan",
    "nro_afiliado",
    "afiliado_nombre",
    "afiliado_dni",
    "medico_nombre",
    "medico_matricula",
    "fecha_prescripcion",
    "fecha_dispensa",
    "nro_receta",
    "nro_autorizacion",
    "diagnostico",
    "firma_medico",
    "sello_medico",
    "firma_afiliado",
    "importe_total",
    "importe_obra_social",
    "items",
]
TipoReceta = Literal["manuscrita", "impresa", "electronica", "otro"]


class ItemExtraido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    descripcion: str
    cantidad: int | None = None
    troquel: str | None = None
    codigo_barras: str | None = None


class ExtraccionReceta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    es_receta: bool = True
    tipo_receta: TipoReceta = "otro"
    obra_social: str | None = None
    plan: str | None = None
    nro_afiliado: str | None = None
    afiliado_nombre: str | None = None
    afiliado_dni: str | None = None
    medico_nombre: str | None = None
    medico_matricula: str | None = None
    fecha_prescripcion: date | None = None
    fecha_dispensa: date | None = None
    nro_receta: str | None = None
    nro_autorizacion: str | None = None
    diagnostico: str | None = None
    firma_medico: bool | None = None
    sello_medico: bool | None = None
    firma_afiliado: bool | None = None
    importe_total: float | None = None
    importe_obra_social: float | None = None
    items: list[ItemExtraido] = []
    campos_dudosos: list[CampoDudoso] = []
    observaciones: str | None = None


def _o_null(tipo: dict) -> dict:
    return {"anyOf": [tipo, {"type": "null"}]}


_TEXTO = {"type": "string"}
_FECHA = {"type": "string", "format": "date"}

_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["descripcion", "cantidad", "troquel", "codigo_barras"],
    "properties": {
        "descripcion": _TEXTO,
        "cantidad": _o_null({"type": "integer"}),
        "troquel": _o_null(_TEXTO),
        "codigo_barras": _o_null(_TEXTO),
    },
}

_PROPIEDADES = {
    "es_receta": {"type": "boolean"},
    "tipo_receta": {"type": "string", "enum": list(get_args(TipoReceta))},
    "obra_social": _o_null(_TEXTO),
    "plan": _o_null(_TEXTO),
    "nro_afiliado": _o_null(_TEXTO),
    "afiliado_nombre": _o_null(_TEXTO),
    "afiliado_dni": _o_null(_TEXTO),
    "medico_nombre": _o_null(_TEXTO),
    "medico_matricula": _o_null(_TEXTO),
    "fecha_prescripcion": _o_null(_FECHA),
    "fecha_dispensa": _o_null(_FECHA),
    "nro_receta": _o_null(_TEXTO),
    "nro_autorizacion": _o_null(_TEXTO),
    "diagnostico": _o_null(_TEXTO),
    "firma_medico": _o_null({"type": "boolean"}),
    "sello_medico": _o_null({"type": "boolean"}),
    "firma_afiliado": _o_null({"type": "boolean"}),
    "importe_total": _o_null({"type": "number"}),
    "importe_obra_social": _o_null({"type": "number"}),
    "items": {"type": "array", "items": _ITEM},
    "campos_dudosos": {"type": "array", "items": {"type": "string", "enum": list(get_args(CampoDudoso))}},
    "observaciones": _o_null(_TEXTO),
}

ESQUEMA_EXTRACCION = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_PROPIEDADES),
    "properties": _PROPIEDADES,
}
