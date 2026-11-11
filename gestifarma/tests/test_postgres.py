"""El circuito completo sobre PostgreSQL, la base de las instalaciones en el cliente.

Se corre solo si GESTIFARMA_TEST_DATABASE_URL apunta a una base de prueba (se borra su contenido):

    GESTIFARMA_TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost:5432/gestifarma_test pytest
"""

import json
import os

import pytest
from fabricas import RAIZ
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from gestifarma import servicios
from gestifarma.cli import main
from gestifarma.conciliacion.motor import Resultado
from gestifarma.conciliacion.reglas import Reglas
from gestifarma.conectores.archivo import cargar_fuentes
from gestifarma.config import Config
from gestifarma.db import crear_engine, crear_sesiones, inicializar
from gestifarma.extraccion import ExtraccionReceta
from gestifarma.modelos import Base
from gestifarma.web import crear_app

URL = os.environ.get("GESTIFARMA_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not URL.startswith("postgresql"), reason="definir GESTIFARMA_TEST_DATABASE_URL para probar con PostgreSQL"
)

REPORTE = RAIZ / "ejemplos" / "reporte_colegio_ejemplo.csv"


@pytest.fixture
def engine():
    engine = crear_engine(URL)
    Base.metadata.drop_all(engine)
    inicializar(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_conciliacion_de_ejemplo_en_postgres(engine):
    sesiones = crear_sesiones(engine)
    fuente = cargar_fuentes(RAIZ / "config" / "fuentes")["colegio-ejemplo"]
    with sesiones() as sesion:
        for datos in json.loads((RAIZ / "ejemplos" / "recetas_ejemplo.json").read_text(encoding="utf-8")):
            sesion.add(servicios.receta_desde_extraccion(ExtraccionReceta.model_validate(datos)))
        sesion.commit()
        assert len(servicios.importar(sesion, REPORTE, REPORTE.name, fuente).registros) == 7
        resumen = servicios.conciliar_y_guardar(sesion, Reglas.desde_toml(RAIZ / "config" / "reglas.toml"))
    assert {resultado: n for resultado, n in resumen.por_resultado.items() if n} == {
        Resultado.CON_DIFERENCIAS: 4,
        Resultado.RECETA_SIN_REGISTRO: 1,
        Resultado.REGISTRO_SIN_RECETA: 1,
        Resultado.OBSERVADA: 1,
        Resultado.OK: 1,
    }


def test_agrega_las_columnas_nuevas_al_actualizar(engine):
    with engine.begin() as conexion:
        conexion.execute(text("ALTER TABLE conciliaciones DROP COLUMN confirmados"))
    inicializar(engine)
    assert "confirmados" in {columna["name"] for columna in inspect(engine).get_columns("conciliaciones")}


def test_app_y_linea_de_comandos_en_postgres(engine, tmp_path, monkeypatch, capsys):
    config = Config(data_dir=tmp_path, database_url=URL, config_dir=RAIZ / "config")
    cliente = TestClient(crear_app(config))
    assert cliente.get("/salud").json()["base"] == "ok"
    with REPORTE.open("rb") as archivo:
        respuesta = cliente.post(
            "/importaciones",
            data={"fuente": "colegio-ejemplo"},
            files={"archivo": ("reporte.csv", archivo, "text/csv")},
        )
    assert "Se importaron 7 cargas" in respuesta.text
    assert "Conciliación lista: 7 casos" in cliente.post("/conciliacion", data={}).text

    monkeypatch.chdir(RAIZ)
    monkeypatch.setenv("GESTIFARMA_DATABASE_URL", URL)
    monkeypatch.setenv("GESTIFARMA_DATA_DIR", str(tmp_path))
    assert main(["conciliar"]) == 0
    assert capsys.readouterr().out.count("SIN RECETA") == 7
