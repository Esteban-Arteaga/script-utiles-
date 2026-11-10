"""Preparación de fotos y PDF antes de mandarlos a la IA."""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

# Lado máximo que aprovechan los modelos actuales: más grande solo hace más pesado el envío.
LADO_MAXIMO = 2576
MAX_PDF_BYTES = 30 * 1024 * 1024


class ArchivoNoSoportado(ValueError):
    pass


def tipo_de_archivo(contenido: bytes) -> str:
    """Tipo MIME real según el contenido (no se confía en la extensión ni en lo que manda el navegador)."""
    if contenido.startswith(b"%PDF"):
        return "application/pdf"
    try:
        with Image.open(BytesIO(contenido)) as imagen:
            formato = (imagen.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise ArchivoNoSoportado("Formato no soportado: subir una foto (JPG, PNG, WEBP) o un PDF.") from exc
    return f"image/{'jpeg' if formato == 'jpeg' else formato}"


def bloque_para_claude(contenido: bytes, nombre: str) -> dict:
    """Arma el bloque de contenido (imagen o documento) para la API de Claude."""
    if contenido.startswith(b"%PDF"):
        if len(contenido) > MAX_PDF_BYTES:
            raise ArchivoNoSoportado(f"{nombre}: el PDF supera los 30 MB.")
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(contenido)},
        }
    try:
        imagen = Image.open(BytesIO(contenido))
        imagen = ImageOps.exif_transpose(imagen)  # las fotos del celular vienen rotadas por EXIF
    except (UnidentifiedImageError, OSError) as exc:
        raise ArchivoNoSoportado(f"{nombre}: formato no soportado (usar JPG, PNG, WEBP o PDF).") from exc
    if imagen.mode != "RGB":
        imagen = imagen.convert("RGB")
    imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO))  # solo achica; mantiene la proporción
    salida = BytesIO()
    imagen.save(salida, format="JPEG", quality=90)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(salida.getvalue())},
    }


def _b64(datos: bytes) -> str:
    return base64.standard_b64encode(datos).decode("ascii")
