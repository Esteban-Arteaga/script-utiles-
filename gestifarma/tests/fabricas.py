"""Atajos para armar recetas y cargas en los tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gestifarma.modelos import ItemReceta, ItemRegistro, Receta, RegistroSistema

RAIZ = Path(__file__).resolve().parents[1]


def nueva_receta(items: list[dict] | None = None, **campos) -> Receta:
    datos = dict(
        obra_social="PAMI",
        nro_afiliado="123456789012/00",
        afiliado_nombre="Gomez, María Elena",
        medico_matricula="MP 12345",
        fecha_prescripcion=date(2026, 11, 2),
        nro_autorizacion="98123",
        firma_medico=True,
        sello_medico=True,
        firma_afiliado=True,
        campos_dudosos=[],
    )
    datos.update(campos)
    receta = Receta(**datos)
    if items is None:
        items = [{"descripcion": "Enalapril 10 mg x 30 comp", "cantidad": 1}]
    receta.items = [ItemReceta(**item) for item in items]
    return receta


def nuevo_registro(items: list[dict] | None = None, **campos) -> RegistroSistema:
    datos = dict(
        fuente="prueba",
        obra_social="PAMI",
        nro_afiliado="123456789012/00",
        afiliado_nombre="GOMEZ MARIA ELENA",
        medico_matricula="12345",
        fecha_prescripcion=date(2026, 11, 2),
        fecha_dispensa=date(2026, 11, 4),
        nro_autorizacion="98123",
    )
    datos.update(campos)
    registro = RegistroSistema(**datos)
    if items is None:
        items = [{"descripcion": "ENALAPRIL 10 MG COMP X 30", "monodroga": "ENALAPRIL", "cantidad": 1}]
    registro.items = [ItemRegistro(**item) for item in items]
    return registro
