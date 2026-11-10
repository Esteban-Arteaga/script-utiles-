"""Genera recetas de ejemplo (imágenes sintéticas, datos inventados) para probar el circuito completo.

Coinciden con ejemplos/reporte_colegio_ejemplo.csv: subirlas en "Varias recetas a la vez", importar el
reporte con el formato colegio-ejemplo y conciliar. Algunas simulan una foto de celular (inclinada,
con sombra y algo borrosa).

Uso: python scripts/generar_recetas_ejemplo.py [carpeta_destino]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RECETAS = [
    dict(
        archivo="01-gomez.jpg",
        obra_social="PAMI",
        plan="",
        nro_receta="0001-00098123",
        afiliado="GOMEZ, MARIA ELENA",
        nro_afiliado="123456789012/00",
        dni="12.345.678",
        fecha="02/11/2026",
        medicamento="Enalapril 10 mg x 30 comp.",
        cantidad="1 (un) envase",
        diagnostico="HTA",
        medico="Dr. JUAN PEREZ",
        matricula="MP 12345",
        foto=False,
    ),
    dict(
        archivo="02-rodriguez.jpg",
        obra_social="OSPE",
        plan="Plan 210",
        nro_receta="45678",
        afiliado="RODRIGUEZ, CARLOS ALBERTO",
        nro_afiliado="60-22334455-1",
        dni="20.111.222",
        fecha="30/10/2026",
        medicamento="Atorvastatina 20 mg x 30 comp.",
        cantidad="1 (un) envase",
        diagnostico="Dislipemia",
        medico="Dra. LAURA SILVA",
        matricula="MP 23456",
        foto=True,
    ),
    dict(
        archivo="03-lopez.jpg",
        obra_social="PAMI",
        plan="",
        nro_receta="",
        afiliado="LOPEZ, ROBERTO",
        nro_afiliado="234567890123/00",
        dni="8.765.432",
        fecha="20/09/2026",
        medicamento="Levotiroxina 50 mcg x 50 comp.",
        cantidad="1 (un) envase",
        diagnostico="Hipotiroidismo",
        medico="Dr. MARCOS DIAZ",
        matricula="MN 34567",
        foto=False,
    ),
    dict(
        archivo="04-martinez.jpg",
        obra_social="PAMI",
        plan="",
        nro_receta="",
        afiliado="MARTINEZ, SUSANA",
        nro_afiliado="345678901234/01",
        dni="10.203.040",
        fecha="01/11/2026",
        medicamento="Amoxicilina 500 mg x 16 comp.",
        cantidad="1 (un) envase",
        diagnostico="Faringitis",
        medico="Dra. PAULA ROSSI",
        matricula="MP 45678",
        foto=True,
    ),
    dict(
        archivo="05-sosa.jpg",
        obra_social="PAMI",
        plan="",
        nro_receta="",
        afiliado="SOSA, HECTOR",
        nro_afiliado="456789012345/00",
        dni="9.876.543",
        fecha="03/11/2026",
        medicamento="Losartan 50 mg x 30 comp.",
        cantidad="1 (un) envase",
        diagnostico="HTA",
        medico="Dr. JORGE MENDEZ",
        matricula="MP 56789",
        foto=False,
    ),
    dict(
        archivo="06-fernandez.jpg",
        obra_social="OSPE",
        plan="Plan 210",
        nro_receta="",
        afiliado="FERNANDEZ, ANA MARIA",
        nro_afiliado="60-33445566-2",
        dni="25.678.901",
        fecha="04/11/2026",
        medicamento="Omeprazol 20 mg x 28 caps.",
        cantidad="1 (un) envase",
        diagnostico="ERGE",
        medico="Dra. SOFIA CANO",
        matricula="MP 67890",
        foto=True,
    ),
    dict(
        archivo="07-diaz.jpg",
        obra_social="OSPE",
        plan="Plan 210",
        nro_receta="",
        afiliado="DIAZ, LAURA",
        nro_afiliado="60-44556677-3",
        dni="30.123.456",
        fecha="05/11/2026",
        medicamento="Metformina 850 mg x 60 comp.",
        cantidad="1 (un) envase",
        diagnostico="DBT 2",
        medico="Dr. PABLO RUIZ",
        matricula="MP 89012",
        foto=False,
    ),
]


def fuente(tamano: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=tamano)


def dibujar(datos: dict) -> Image.Image:
    ancho, alto = 1240, 1754
    imagen = Image.new("RGB", (ancho, alto), (252, 251, 247))
    d = ImageDraw.Draw(imagen)
    azul, negro, gris, sello = (20, 40, 90), (10, 10, 10), (90, 90, 90), (120, 40, 120)
    d.rectangle([40, 40, ancho - 40, alto - 40], outline=(60, 90, 140), width=4)
    encabezado = f"RECETA  -  OBRA SOCIAL: {datos['obra_social']}" + (f" - {datos['plan']}" if datos["plan"] else "")
    d.text((80, 80), encabezado, fill=azul, font=fuente(44))
    if datos["nro_receta"]:
        d.text((80, 150), f"Nro de receta: {datos['nro_receta']}", fill=negro, font=fuente(30))
    d.line([80, 210, ancho - 80, 210], fill=(60, 90, 140), width=2)
    y = 250
    for etiqueta, valor in [
        ("Afiliado:", datos["afiliado"]),
        ("Nro de afiliado:", datos["nro_afiliado"]),
        ("DNI:", datos["dni"]),
        ("Fecha:", datos["fecha"]),
    ]:
        d.text((80, y), etiqueta, fill=gris, font=fuente(32))
        d.text((420, y), valor, fill=negro, font=fuente(36))
        y += 70
    d.text((80, y + 40), "Rp/", fill=azul, font=fuente(56))
    d.text((160, y + 140), datos["medicamento"], fill=negro, font=fuente(44))
    d.text((160, y + 210), f"Cantidad: {datos['cantidad']}", fill=negro, font=fuente(36))
    d.text((80, y + 330), f"Diagnostico: {datos['diagnostico']}", fill=negro, font=fuente(34))
    d.line([700, 1450, 1120, 1380], fill=(30, 30, 120), width=5)  # firma
    d.arc([760, 1360, 980, 1480], 200, 340, fill=(30, 30, 120), width=5)
    d.rectangle([700, 1500, 1150, 1640], outline=sello, width=4)
    d.text((720, 1520), datos["medico"], fill=sello, font=fuente(36))
    d.text((720, 1575), f"Medico - {datos['matricula']}", fill=sello, font=fuente(30))
    return imagen


def como_foto(imagen: Image.Image) -> Image.Image:
    """Inclinada sobre una mesa, con luz despareja y algo borrosa."""
    fondo = (110, 95, 80)
    lienzo = Image.new("RGB", (int(imagen.width * 1.12), int(imagen.height * 1.08)), fondo)
    lienzo.paste(imagen, (int(imagen.width * 0.06), int(imagen.height * 0.04)))
    lienzo = lienzo.rotate(3.5, resample=Image.BICUBIC, fillcolor=fondo)
    sombra = Image.linear_gradient("L").rotate(90).resize(lienzo.size)  # más oscuro hacia un costado
    oscuro = Image.new("RGB", lienzo.size, (40, 35, 30))
    lienzo = Image.composite(lienzo, oscuro, sombra.point(lambda v: 150 + v * 105 // 255))
    lienzo = lienzo.filter(ImageFilter.GaussianBlur(1.1))
    return lienzo.resize((lienzo.width * 3 // 4, lienzo.height * 3 // 4))


def main() -> None:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "ejemplos" / "recetas"
    destino.mkdir(parents=True, exist_ok=True)
    for datos in RECETAS:
        imagen = dibujar(datos)
        if datos["foto"]:
            imagen = como_foto(imagen)
        imagen.save(destino / datos["archivo"], "JPEG", quality=85)
        print(destino / datos["archivo"])


if __name__ == "__main__":
    main()
