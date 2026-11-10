"""Línea de comandos: `gestifarma --help`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import servicios
from .conciliacion.motor import Resultado
from .conciliacion.reglas import Reglas
from .conectores.archivo import ErrorImportacion, cargar_fuentes
from .config import Config
from .db import crear_engine, crear_sesiones, inicializar
from .extraccion import ExtraccionReceta, ExtractorClaude
from .extraccion.local import LectorLocal
from .modelos import Conciliacion

ICONOS = {  # en orden de urgencia
    Resultado.CON_DIFERENCIAS: "DIFERENCIAS ",
    Resultado.RECETA_SIN_REGISTRO: "SIN CARGA   ",
    Resultado.REGISTRO_SIN_RECETA: "SIN RECETA  ",
    Resultado.OBSERVADA: "REVISAR     ",
    Resultado.OK: "OK          ",
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="gestifarma", description="Conciliación de recetas vs. lo cargado en las obras sociales."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("servidor", help="levanta la aplicación web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)

    p = sub.add_parser("importar", help="importa un reporte exportado del sistema (CSV/Excel)")
    p.add_argument("archivo", type=Path)
    p.add_argument("--fuente", required=True, help="formato del reporte (nombre en config/fuentes)")

    p = sub.add_parser("traer", help="descarga el reporte del portal con el robot (RPA) y lo importa")
    p.add_argument("--fuente", required=True)
    p.add_argument("--desde", type=date.fromisoformat, required=True, help="AAAA-MM-DD")
    p.add_argument("--hasta", type=date.fromisoformat, required=True, help="AAAA-MM-DD")

    p = sub.add_parser("conciliar", help="cruza recetas y cargas e imprime el resultado")
    p.add_argument("--desde", type=date.fromisoformat, help="AAAA-MM-DD")
    p.add_argument("--hasta", type=date.fromisoformat, help="AAAA-MM-DD")
    p.add_argument("--obra-social")

    p = sub.add_parser("leer", help="lee una receta (fotos o PDF) y muestra los datos en JSON")
    p.add_argument("archivos", type=Path, nargs="+", help="frente, dorso... de UNA receta")
    p.add_argument("--ia", action="store_true", help="leer con IA (Claude, con costo) en vez de sin IA")

    p = sub.add_parser("demo", help="concilia los datos de ejemplo (no necesita IA ni configuración)")
    p.add_argument("--ejemplos", type=Path, default=Path("ejemplos"))

    args = parser.parse_args(argv)
    config = Config.desde_entorno()

    if args.comando == "servidor":
        import uvicorn

        from .web.app import crear_app

        uvicorn.run(crear_app(config), host=args.host, port=args.port)
        return 0
    if args.comando == "leer":
        return _leer(config, args.archivos, args.ia)
    if args.comando == "demo":
        return _demo(config, args.ejemplos)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    engine = crear_engine(config.database_url)
    inicializar(engine)
    sesiones = crear_sesiones(engine)
    fuentes = cargar_fuentes(config.fuentes_dir)

    if args.comando == "importar":
        return _importar(sesiones, fuentes, args.fuente, args.archivo)
    if args.comando == "traer":
        return _traer(sesiones, fuentes, args.fuente, args.desde, args.hasta)
    if args.comando == "conciliar":
        reglas = _reglas(config)
        with sesiones() as sesion:
            resumen = servicios.conciliar_y_guardar(sesion, reglas, args.desde, args.hasta, args.obra_social)
            _imprimir_resultados(sesion)
        print(f"\n{resumen.total} casos. Recetas sin datos (no incluidas): {resumen.recetas_sin_leer}")
        return 0
    return 1


def _reglas(config: Config) -> Reglas:
    return Reglas.desde_toml(config.reglas_path) if config.reglas_path.exists() else Reglas()


def _importar(sesiones, fuentes, fuente: str, archivo: Path) -> int:
    if fuente not in fuentes:
        print(f"Formato desconocido: {fuente}. Disponibles: {', '.join(fuentes) or '(ninguno)'}", file=sys.stderr)
        return 2
    with sesiones() as sesion:
        try:
            importacion = servicios.importar(sesion, archivo, archivo.name, fuentes[fuente])
        except ErrorImportacion as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"{len(importacion.registros)} cargas importadas de {importacion.filas_leidas} filas.")
        for error in importacion.errores:
            print(f"  ! {error}")
    return 0


def _traer(sesiones, fuentes, fuente: str, desde: date, hasta: date) -> int:
    from .conectores.portal_web import ConfigPortal, ErrorPortal, descargar_reporte

    mapeo = fuentes.get(fuente)
    if mapeo is None or not mapeo.portal:
        print(f"La fuente {fuente!r} no existe o no tiene sección [portal].", file=sys.stderr)
        return 2
    usuario, clave = os.environ.get("GESTIFARMA_PORTAL_USUARIO"), os.environ.get("GESTIFARMA_PORTAL_CLAVE")
    if not usuario or not clave:
        print("Definir GESTIFARMA_PORTAL_USUARIO y GESTIFARMA_PORTAL_CLAVE.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as directorio:
        try:
            ruta = descargar_reporte(
                ConfigPortal.desde_dict(mapeo.portal), usuario, clave, desde, hasta, Path(directorio)
            )
        except ErrorPortal as exc:
            print(exc, file=sys.stderr)
            return 2
        return _importar(sesiones, fuentes, fuente, ruta)


def _leer(config: Config, archivos: list[Path], con_ia: bool) -> int:
    if con_ia or config.lector == "claude":
        if not config.lectura_ia:
            print("Falta ANTHROPIC_API_KEY para leer recetas con IA (ver .env.example).", file=sys.stderr)
            return 2
        lector = ExtractorClaude(config.modelo, config.esfuerzo)
    else:
        lector = LectorLocal(config.ocr)
    resultado = lector.extraer([(a.read_bytes(), a.name) for a in archivos])
    print(json.dumps(resultado.como_json(), ensure_ascii=False, indent=2))
    return 0


def _demo(config: Config, ejemplos: Path) -> int:
    """Carga recetas ya leídas + un reporte de ejemplo en una base temporal y concilia."""
    recetas_json = ejemplos / "recetas_ejemplo.json"
    reporte = ejemplos / "reporte_colegio_ejemplo.csv"
    if not recetas_json.exists() or not reporte.exists():
        print(
            f"No encuentro los ejemplos en {ejemplos.resolve()} (correr desde la carpeta del proyecto).",
            file=sys.stderr,
        )
        return 2
    with tempfile.TemporaryDirectory() as directorio:
        config_demo = replace(config, data_dir=Path(directorio), database_url=f"sqlite:///{directorio}/demo.db")
        engine = crear_engine(config_demo.database_url)
        inicializar(engine)
        sesiones = crear_sesiones(engine)
        fuentes = cargar_fuentes(config.fuentes_dir)
        with sesiones() as sesion:
            for datos in json.loads(recetas_json.read_text(encoding="utf-8")):
                sesion.add(servicios.receta_desde_extraccion(ExtraccionReceta.model_validate(datos)))
            sesion.commit()
            importacion = servicios.importar(sesion, reporte, reporte.name, fuentes["colegio-ejemplo"])
            print(
                f"Recetas de ejemplo: {len(json.loads(recetas_json.read_text(encoding='utf-8')))} · "
                f"cargas importadas: {len(importacion.registros)}\n"
            )
            resumen = servicios.conciliar_y_guardar(sesion, _reglas(config))
            _imprimir_resultados(sesion)
        print(
            "\nResumen: "
            + ", ".join(f"{ICONOS[k].strip()} {resumen.por_resultado[k]}" for k in ICONOS if resumen.por_resultado[k])
        )
        engine.dispose()
    return 0


def _imprimir_resultados(sesion) -> None:
    from sqlalchemy import select

    orden = list(ICONOS)
    casos = sorted(sesion.scalars(select(Conciliacion)).all(), key=lambda c: (orden.index(c.resultado), c.id))
    for caso in casos:
        datos = caso.registro or caso.receta
        quien = f"{datos.afiliado_nombre or '¿afiliado?'} ({datos.obra_social or '¿OS?'})"
        origen = f"receta #{caso.receta.id}" if caso.receta else "carga sin receta"
        print(f"{ICONOS[caso.resultado]} {origen:<16} {quien}")
        for d in caso.discrepancias:
            valores = (
                f" (receta: {d.valor_receta or '-'} / sistema: {d.valor_sistema or '-'})"
                if d.valor_receta or d.valor_sistema
                else ""
            )
            print(f"    - [{d.severidad}] {d.mensaje}{valores}")


if __name__ == "__main__":
    sys.exit(main())
