import base64
import json
from io import BytesIO

import pytest
from fabricas import RAIZ
from fastapi.testclient import TestClient
from PIL import Image

from gestifarma.config import Config
from gestifarma.extraccion import ExtraccionReceta, ResultadoExtraccion
from gestifarma.web import crear_app

RECETA_GOMEZ = json.loads((RAIZ / "ejemplos" / "recetas_ejemplo.json").read_text(encoding="utf-8"))[0]
REPORTE = RAIZ / "ejemplos" / "reporte_colegio_ejemplo.csv"


CREDENCIALES = {"Authorization": "Basic " + base64.b64encode(b"ana:secreta").decode()}


class ExtractorFalso:
    def __init__(self):
        self.llamadas = 0

    def extraer(self, archivos):
        self.llamadas += 1
        return ResultadoExtraccion(ExtraccionReceta.model_validate(RECETA_GOMEZ), "falso", {"output_tokens": 1})


def configuracion(tmp_path, **cambios) -> Config:
    datos = dict(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        config_dir=RAIZ / "config",
        usuario="ana",
        clave="secreta",
    )
    datos.update(cambios)
    return Config(**datos)


@pytest.fixture
def extractor():
    return ExtractorFalso()


@pytest.fixture
def cliente(tmp_path, extractor):
    app = crear_app(configuracion(tmp_path), extractor=extractor)
    return TestClient(app, headers=CREDENCIALES)


def jpg() -> bytes:
    salida = BytesIO()
    Image.new("RGB", (800, 600), "white").save(salida, format="JPEG")
    return salida.getvalue()


def test_pide_usuario_y_clave(tmp_path):
    cliente = TestClient(crear_app(configuracion(tmp_path), extractor=ExtractorFalso()))
    assert cliente.get("/recetas").status_code == 401
    otra_clave = {"Authorization": "Basic " + base64.b64encode(b"ana:otra").decode()}
    assert cliente.get("/recetas", headers=otra_clave).status_code == 401
    assert cliente.get("/salud").json() == {"estado": "ok"}


def test_flujo_completo_foto_importacion_y_conciliacion(cliente, extractor):
    respuesta = cliente.post(
        "/recetas", files=[("archivos", ("frente.jpg", jpg(), "image/jpeg"))], data={"modo": "una"}
    )
    assert respuesta.status_code == 200 and respuesta.url.path == "/recetas/1"
    assert extractor.llamadas == 1
    pagina = cliente.get("/recetas/1").text
    assert "Enalapril 10 mg x 30 comp" in pagina and "Sin conciliar" in pagina
    assert cliente.get("/archivos/1").headers["content-type"] == "image/jpeg"

    with REPORTE.open("rb") as archivo:
        respuesta = cliente.post(
            "/importaciones",
            data={"fuente": "colegio-ejemplo"},
            files={"archivo": ("reporte.csv", archivo, "text/csv")},
        )
    assert "Se importaron 7 cargas" in respuesta.text

    respuesta = cliente.post("/conciliacion", data={"desde": "", "hasta": "", "obra_social": ""})
    assert "Conciliación lista: 7 casos" in respuesta.text
    assert "Carga sin receta" in respuesta.text
    assert 'badge badge-ok">OK' in cliente.get("/recetas/1").text

    csv = cliente.get("/conciliacion/diferencias.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.content.startswith("\ufeff".encode() + b"Resultado;")


def test_varias_recetas_a_la_vez(cliente, extractor):
    archivos = [("archivos", (f"r{i}.jpg", jpg(), "image/jpeg")) for i in range(3)]
    respuesta = cliente.post("/recetas", files=archivos, data={"modo": "varias"})
    assert "Se subieron 3 recetas" in respuesta.text
    assert extractor.llamadas == 3


def test_archivo_que_no_es_receta(cliente):
    respuesta = cliente.post(
        "/recetas", files=[("archivos", ("nota.txt", b"hola", "text/plain"))], data={"modo": "una"}
    )
    assert respuesta.url.path == "/recetas/nueva"
    assert "Formato no soportado" in respuesta.text


def test_revision_manual_actualiza_datos_y_conciliacion(cliente):
    cliente.post("/recetas", files=[("archivos", ("frente.jpg", jpg(), "image/jpeg"))], data={"modo": "una"})
    formulario = {
        "obra_social": "PAMI",
        "nro_afiliado": "123456789012/00",
        "afiliado_nombre": "Gomez Maria Elena",
        "medico_matricula": "MP 12345",
        "fecha_prescripcion": "2026-11-02",
        "nro_autorizacion": "98123",
        "firma_medico": "si",
        "sello_medico": "si",
        "firma_afiliado": "no",
        "importe_total": "1.234,50",
        "item_descripcion": ["Enalapril 10 mg", ""],
        "item_cantidad": ["2", ""],
        "item_troquel": ["", ""],
        "item_codigo_barras": ["", ""],
    }
    respuesta = cliente.post("/recetas/1", data=formulario)
    assert "Datos guardados" in respuesta.text
    assert "Falta la firma del afiliado en el dorso." in respuesta.text  # se volvió a conciliar
    assert 'value="1234.50"' in respuesta.text

    formulario["fecha_prescripcion"] = "30/02/2026"
    assert "No se guardó" in cliente.post("/recetas/1", data=formulario).text


def test_sin_ia_la_receta_queda_para_cargar_a_mano(tmp_path):
    cliente = TestClient(crear_app(configuracion(tmp_path)), headers=CREDENCIALES)
    respuesta = cliente.post(
        "/recetas", files=[("archivos", ("frente.jpg", jpg(), "image/jpeg"))], data={"modo": "una"}
    )
    assert "Completá los datos" in respuesta.text


def test_rechaza_formularios_enviados_desde_otro_sitio(cliente):
    respuesta = cliente.post("/conciliacion", data={}, headers={"Origin": "https://otro-sitio.example"})
    assert respuesta.status_code == 403


def test_eliminar_receta_borra_los_archivos(cliente, tmp_path):
    cliente.post("/recetas", files=[("archivos", ("frente.jpg", jpg(), "image/jpeg"))], data={"modo": "una"})
    assert list((tmp_path / "archivos").rglob("*.jpg"))
    cliente.post("/recetas/1/eliminar")
    assert cliente.get("/recetas/1").status_code == 404
    assert not list((tmp_path / "archivos").rglob("*.jpg"))
