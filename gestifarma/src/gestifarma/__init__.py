"""Gestifarma: conciliación de recetas contra lo cargado en los sistemas de obras sociales."""

import os

__version__ = "0.1.0"


def version_instalada() -> str:
    """Versión del paquete y, si corre en la imagen de Docker, la versión con la que se construyó."""
    imagen = os.environ.get("GESTIFARMA_VERSION_IMAGEN", "").strip()
    return f"{__version__} ({imagen})" if imagen and imagen != __version__ else __version__
