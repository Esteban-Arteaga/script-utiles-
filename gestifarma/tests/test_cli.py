from fabricas import RAIZ

from gestifarma.cli import main


def test_demo(monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    monkeypatch.delenv("GESTIFARMA_CONFIG_DIR", raising=False)
    assert main(["demo"]) == 0
    salida = capsys.readouterr().out
    assert "Resumen: DIFERENCIAS 4, SIN CARGA 1, SIN RECETA 1, REVISAR 1, OK 1" in salida
    assert "El número de afiliado no coincide." in salida


def test_importar_y_conciliar(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(RAIZ)
    monkeypatch.setenv("GESTIFARMA_DATA_DIR", str(tmp_path))
    assert main(["importar", "ejemplos/reporte_colegio_ejemplo.csv", "--fuente", "colegio-ejemplo"]) == 0
    assert main(["conciliar"]) == 0
    salida = capsys.readouterr().out
    assert "7 cargas importadas" in salida
    assert salida.count("SIN RECETA") == 7  # no hay recetas cargadas en esta base
    assert main(["importar", "x.csv", "--fuente", "no-existe"]) == 2
