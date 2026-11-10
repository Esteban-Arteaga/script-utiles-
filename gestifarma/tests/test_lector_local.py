import shutil
from datetime import date
from io import BytesIO

import pytest
import zxingcpp
from fabricas import RAIZ, pdf_con_texto
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from gestifarma.extraccion.local import LectorLocal

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="falta Tesseract (OCR)")

FRENTE = (RAIZ / "ejemplos" / "receta_sintetica.jpg").read_bytes()


def jpg(imagen: Image.Image) -> bytes:
    salida = BytesIO()
    imagen.save(salida, format="JPEG", quality=85)
    return salida.getvalue()


def como_foto(contenido: bytes) -> bytes:
    """Inclinada, más chica y algo borrosa, como una foto de celular."""
    imagen = Image.open(BytesIO(contenido)).convert("RGB")
    imagen = imagen.rotate(3, expand=True, fillcolor=(110, 95, 80)).filter(ImageFilter.GaussianBlur(1))
    return jpg(imagen.resize((imagen.width * 3 // 4, imagen.height * 3 // 4)))


def dorso_con_troquel() -> bytes:
    dorso = Image.new("RGB", (1240, 1754), "white")
    dibujo = ImageDraw.Draw(dorso)
    codigo = zxingcpp.create_barcode("4123456", zxingcpp.BarcodeFormat.Code128).to_image(scale=4)
    alto, ancho = codigo.shape
    dorso.paste(Image.frombytes("L", (ancho, alto), bytes(memoryview(codigo))), (100, 120))
    fuente = ImageFont.load_default(size=28)
    for i, linea in enumerate(
        ["TICKET DE VALIDACION", "Fecha: 04/11/2026", "Autorizacion: 0098123", "Total: $ 9.850,00"]
    ):
        dibujo.text((650, 500 + 50 * i), linea, fill="black", font=fuente)
    return jpg(dorso)


@pytest.mark.parametrize("frente", [FRENTE, como_foto(FRENTE)], ids=["escaneada", "foto"])
def test_lee_la_receta_impresa_sin_ia(frente):
    resultado = LectorLocal().extraer([(frente, "frente.jpg")])
    datos = resultado.datos
    assert resultado.lector == "local" and resultado.modelo == "local:tesseract"
    assert datos.obra_social == "PAMI"
    assert datos.nro_afiliado == "123456789012/00"
    assert datos.afiliado_nombre == "GOMEZ, MARIA ELENA"
    assert datos.medico_matricula == "MP 12345"
    assert datos.fecha_prescripcion == date(2026, 11, 2)
    assert [(i.descripcion.lower()[:12], i.cantidad) for i in datos.items] == [("enalapril 10", 1)]
    assert resultado.extra["paginas"][0]["lado"] == "frente"


def test_dorso_ticket_y_codigo_de_barras():
    resultado = LectorLocal().extraer([(FRENTE, "frente.jpg"), (dorso_con_troquel(), "dorso.jpg")])
    frente, dorso = resultado.extra["paginas"]
    assert dorso["lado"] == "dorso" and dorso["codigos"] == ["4123456"]
    assert resultado.datos.nro_autorizacion == "0098123"
    assert resultado.datos.fecha_dispensa == date(2026, 11, 4)
    assert resultado.datos.importe_total == 9850.0


def test_receta_electronica_en_pdf_se_lee_sin_ocr():
    pdf = pdf_con_texto(
        [
            "RECETA ELECTRONICA - OBRA SOCIAL: OSPE",
            "Afiliado: DIAZ LAURA",
            "Nro de afiliado: 60-44556677-3",
            "Fecha: 05/11/2026",
            "Metformina 850 mg x 60 comp",
            "Cantidad: 1",
            "Dra. Ana Ruiz - M.N. 89012",
        ]
    )
    resultado = LectorLocal().extraer([(pdf, "receta.pdf")])
    assert resultado.extra["paginas"][0]["fuente"] == "pdf"
    assert resultado.datos.tipo_receta == "electronica"
    assert resultado.datos.nro_afiliado == "60-44556677-3"
    assert resultado.datos.medico_matricula == "MN 89012"
    assert resultado.datos.items[0].descripcion.startswith("Metformina 850")


def test_imagen_sin_texto_avisa():
    resultado = LectorLocal().extraer([(jpg(Image.new("RGB", (800, 600), "white")), "vacia.jpg")])
    assert "muy poco texto" in resultado.datos.observaciones
