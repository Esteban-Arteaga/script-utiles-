"""Guardado de las fotos/PDF de las recetas.

Para el piloto alcanza con un disco (local o un volumen persistente en la nube). Para varias
farmacias conviene un almacenamiento de objetos (S3, Cloud Storage o similar) con la misma interfaz.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from uuid import uuid4


class AlmacenLocal:
    def __init__(self, base: Path):
        self.base = base.resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def guardar(self, contenido: bytes, nombre_original: str) -> str:
        """Guarda el archivo y devuelve su ruta relativa (lo que se registra en la base)."""
        extension = re.sub(r"[^a-z0-9.]", "", Path(nombre_original).suffix.lower())[:10] or ".bin"
        hoy = date.today()
        relativa = f"{hoy:%Y}/{hoy:%m}/{uuid4().hex}{extension}"
        destino = self.base / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        return relativa

    def ruta(self, relativa: str) -> Path:
        ruta = (self.base / relativa).resolve()
        if not ruta.is_relative_to(self.base):
            raise ValueError(f"Ruta fuera del almacenamiento: {relativa}")
        return ruta

    def leer(self, relativa: str) -> bytes:
        return self.ruta(relativa).read_bytes()

    def eliminar(self, relativa: str) -> None:
        self.ruta(relativa).unlink(missing_ok=True)
