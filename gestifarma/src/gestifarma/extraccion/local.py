"""Lectura de recetas SIN IA y sin costo por receta: todo corre en el propio servidor.

En cascada, de lo más exacto a lo menos:
1. Texto de los PDF (recetas electrónicas): se lee tal cual, sin errores.
2. Códigos de barras y QR (troqueles, recetas electrónicas): decodificación exacta.
3. OCR (Tesseract o RapidOCR) para fotos y escaneos: muy bueno con texto impreso; con letra
   manuscrita lee poco y esos datos quedan para revisar.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError

from .campos import extraer_campos
from .claude import ErrorExtraccion, ResultadoExtraccion

MAX_PAGINAS_PDF = 6
MIN_TEXTO_PDF = 40  # menos que esto: PDF escaneado (imagen), hay que pasarle OCR


RUTAS_TESSERACT_WINDOWS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def ruta_tesseract() -> str | None:
    """Tesseract: la ruta de GESTIFARMA_TESSERACT, el que esté en el PATH o el instalador de Windows."""
    configurada = os.environ.get("GESTIFARMA_TESSERACT")
    if configurada:
        return configurada if Path(configurada).exists() else None
    return shutil.which("tesseract") or next((r for r in RUTAS_TESSERACT_WINDOWS if Path(r).exists()), None)


class LectorLocal:
    def __init__(self, motor_ocr: str = "tesseract", idioma: str = "spa"):
        if motor_ocr not in ("tesseract", "rapidocr"):
            raise ValueError(f"Motor de OCR desconocido: {motor_ocr} (usar tesseract o rapidocr)")
        self.motor_ocr = motor_ocr
        self.idioma = idioma
        self._rapidocr = None

    def extraer(self, archivos: list[tuple[bytes, str]]) -> ResultadoExtraccion:
        """`archivos`: (contenido, nombre) de UNA receta. La primera página del primer archivo es el
        frente (la receta del médico); el resto, dorso (ticket de validación, troqueles, firma)."""
        if not archivos:
            raise ErrorExtraccion("La receta no tiene archivos.")
        inicio = time.monotonic()
        paginas = []
        for n_archivo, (contenido, nombre) in enumerate(archivos):
            for n_pagina, (imagen, texto_pdf) in enumerate(_paginas(contenido, nombre)):
                if texto_pdf and len(texto_pdf.strip()) >= MIN_TEXTO_PDF:
                    texto, fuente = texto_pdf, "pdf"
                else:
                    texto, fuente = self._ocr(imagen), "ocr"
                paginas.append(
                    {
                        "archivo": nombre,
                        "pagina": n_pagina + 1,
                        "lado": "frente" if n_archivo == 0 and n_pagina == 0 else "dorso",
                        "fuente": fuente,
                        "texto": texto.strip(),
                        "codigos": _codigos(imagen),
                    }
                )
        frente = "\n".join(p["texto"] for p in paginas if p["lado"] == "frente")
        dorso = "\n".join(p["texto"] for p in paginas if p["lado"] == "dorso")
        datos = extraer_campos(frente, dorso)
        if any(p["fuente"] == "pdf" for p in paginas):
            datos.tipo_receta = "electronica"
        if len(frente) < 40:
            datos.observaciones = (
                "Se leyó muy poco texto en el frente (¿letra manuscrita o foto borrosa?). Revisar a mano o leer con IA."
            )
        return ResultadoExtraccion(
            datos=datos,
            modelo=f"local:{self.motor_ocr}",
            uso={"segundos": round(time.monotonic() - inicio, 2)},
            lector="local",
            extra={"paginas": paginas},
        )

    def _ocr(self, imagen: Image.Image) -> str:
        imagen = _preparar_para_ocr(imagen)
        if self.motor_ocr == "rapidocr":
            return self._ocr_rapidocr(imagen)
        return self._ocr_tesseract(imagen)

    def _ocr_tesseract(self, imagen: Image.Image) -> str:
        ejecutable = ruta_tesseract()
        if ejecutable is None:
            raise ErrorExtraccion(
                "No se encontró Tesseract (OCR). Windows: winget install UB-Mannheim.TesseractOCR (o definir "
                "GESTIFARMA_TESSERACT con la ruta a tesseract.exe). Debian/Ubuntu: apt-get install tesseract-ocr "
                "tesseract-ocr-spa. macOS: brew install tesseract tesseract-lang."
            )
        # Se pasa por un archivo temporal (y no por la entrada estándar) para que ande igual en Windows.
        with tempfile.TemporaryDirectory() as carpeta:
            entrada = Path(carpeta) / "pagina.png"
            imagen.save(entrada, format="PNG")
            proceso = subprocess.run(
                [ejecutable, str(entrada), "stdout", "-l", self.idioma, "--psm", "3"],
                capture_output=True,
                timeout=120,
                check=False,
            )
        if proceso.returncode != 0:
            error = proceso.stderr.decode(errors="replace")
            if "Failed loading language" in error or "Error opening data file" in error:
                raise ErrorExtraccion(
                    f"A Tesseract le falta el idioma «{self.idioma}» ({self.idioma}.traineddata). "
                    "Copiarlo a la carpeta tessdata de Tesseract (ver README, sección Windows)."
                )
            raise ErrorExtraccion(f"Tesseract falló: {error[:300]}")
        return proceso.stdout.decode("utf-8", errors="replace")

    def _ocr_rapidocr(self, imagen: Image.Image) -> str:
        if self._rapidocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise ErrorExtraccion('Falta RapidOCR: pip install "gestifarma[rapidocr]"') from exc
            self._rapidocr = RapidOCR()
        import numpy as np

        cajas, _ = self._rapidocr(np.asarray(imagen.convert("RGB")))
        return _unir_en_renglones(cajas or [])


def _paginas(contenido: bytes, nombre: str) -> Iterator[tuple[Image.Image, str | None]]:
    """(imagen, texto del PDF si tiene) de cada página."""
    if contenido.startswith(b"%PDF"):
        import pypdfium2 as pdfium

        documento = pdfium.PdfDocument(contenido)
        try:
            for indice in range(min(len(documento), MAX_PAGINAS_PDF)):
                pagina = documento[indice]
                texto = pagina.get_textpage().get_text_range()
                yield pagina.render(scale=200 / 72).to_pil(), texto
        finally:
            documento.close()
        return
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ErrorExtraccion(f"{nombre}: formato no soportado (usar JPG, PNG, WEBP o PDF).") from exc
    yield ImageOps.exif_transpose(imagen), None


def _codigos(imagen: Image.Image) -> list[str]:
    """Contenido de los códigos de barras y QR de la imagen, sin repetir."""
    vistos: list[str] = []
    for codigo in zxingcpp.read_barcodes(imagen):
        if codigo.text and codigo.text not in vistos:
            vistos.append(codigo.text)
    return vistos


def _preparar_para_ocr(imagen: Image.Image) -> Image.Image:
    """Solo se ajusta el tamaño si es extremo: en las pruebas, pasar a grises o reescalar fotos de
    tamaño normal empeoró la lectura (Tesseract binariza por su cuenta)."""
    imagen = imagen.convert("RGB")
    lado = max(imagen.size)
    if 1000 <= lado <= 4000:
        return imagen
    factor = (1600 if lado < 1000 else 3000) / lado
    return imagen.resize((round(imagen.width * factor), round(imagen.height * factor)), Image.LANCZOS)


def _unir_en_renglones(cajas: list) -> str:
    """RapidOCR devuelve un texto por recuadro: se juntan los que están a la misma altura."""
    elementos = []
    for caja, texto, _confianza in cajas:
        ys = [p[1] for p in caja]
        xs = [p[0] for p in caja]
        elementos.append((sum(ys) / len(ys), max(ys) - min(ys), min(xs), texto))
    elementos.sort()
    renglones: list[list[tuple]] = []
    for elemento in elementos:
        if renglones and abs(elemento[0] - renglones[-1][0][0]) < max(elemento[1], renglones[-1][0][1]) / 2:
            renglones[-1].append(elemento)
        else:
            renglones.append([elemento])
    return "\n".join(" ".join(e[3] for e in sorted(renglon, key=lambda e: e[2])) for renglon in renglones)
