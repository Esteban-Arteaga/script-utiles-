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


def pdf_con_texto(lineas: list[str]) -> bytes:
    """PDF mínimo de una página con texto (como una receta electrónica), sin librerías extra."""

    def escapar(texto: str) -> str:
        return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    contenido = "BT /F1 14 Tf 50 800 Td " + " ".join(f"({escapar(linea)}) Tj 0 -22 Td" for linea in lineas) + " ET"
    objetos = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida, posiciones = "%PDF-1.4\n", []
    for numero, objeto in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{numero} 0 obj\n{objeto}\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n"
    salida += "".join(f"{posicion:010d} 00000 n \n" for posicion in posiciones)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n"
    return salida.encode("latin-1")
