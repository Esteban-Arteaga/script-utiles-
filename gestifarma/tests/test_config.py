import os

import pytest

from gestifarma.config import Config, cargar_env
from gestifarma.extraccion.local import ruta_tesseract


def test_cargar_env(tmp_path, monkeypatch):
    for clave in ("GF_PRUEBA_A", "GF_PRUEBA_B", "GF_PRUEBA_C", "GF_PRUEBA_VACIA"):
        monkeypatch.delenv(clave, raising=False)
    monkeypatch.setenv("GF_PRUEBA_C", "ya-estaba")
    archivo = tmp_path / ".env"
    archivo.write_text(
        '# comentario\nGF_PRUEBA_A=uno\nexport GF_PRUEBA_B="dos con espacios"\nGF_PRUEBA_C=pisada\nGF_PRUEBA_VACIA=\n',
        encoding="utf-8",
    )
    cargar_env(archivo)
    assert os.environ["GF_PRUEBA_A"] == "uno"
    assert os.environ["GF_PRUEBA_B"] == "dos con espacios"
    assert os.environ["GF_PRUEBA_C"] == "ya-estaba"  # lo definido afuera manda
    assert "GF_PRUEBA_VACIA" not in os.environ
    cargar_env(tmp_path / "no-existe.env")  # sin archivo no hace nada


def test_url_de_sqlite_portable(monkeypatch, tmp_path):
    monkeypatch.setenv("GESTIFARMA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GESTIFARMA_DATABASE_URL", raising=False)
    assert Config.desde_entorno().database_url == f"sqlite:///{(tmp_path / 'gestifarma.db').as_posix()}"


def test_ruta_de_tesseract_configurada(monkeypatch, tmp_path):
    ejecutable = tmp_path / "tesseract.exe"
    ejecutable.write_bytes(b"")
    monkeypatch.setenv("GESTIFARMA_TESSERACT", str(ejecutable))
    assert ruta_tesseract() == str(ejecutable)
    monkeypatch.setenv("GESTIFARMA_TESSERACT", str(tmp_path / "no-existe.exe"))
    assert ruta_tesseract() is None


@pytest.mark.skipif(ruta_tesseract() is None, reason="falta Tesseract")
def test_idioma_faltante_da_un_error_claro():
    from io import BytesIO

    from PIL import Image

    from gestifarma.extraccion import ErrorExtraccion
    from gestifarma.extraccion.local import LectorLocal

    imagen = BytesIO()
    Image.new("RGB", (1200, 800), "white").save(imagen, format="PNG")
    with pytest.raises(ErrorExtraccion, match="le falta el idioma"):
        LectorLocal(idioma="xyz").extraer([(imagen.getvalue(), "hoja.png")])
