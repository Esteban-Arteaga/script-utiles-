"""Aplicación web del backoffice. Pensada para usarse desde el celular (sacar fotos) y desde la PC."""

from __future__ import annotations

import logging
import secrets
import tempfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from .. import servicios, version_instalada
from ..almacenamiento import AlmacenLocal
from ..conciliacion.motor import Criterio, Resultado, Severidad
from ..conciliacion.reglas import Reglas
from ..conectores.archivo import cargar_fuentes
from ..config import Config
from ..db import crear_engine, crear_sesiones, inicializar
from ..extraccion import Extractor, ExtractorClaude
from ..extraccion.local import LectorLocal
from ..modelos import ArchivoReceta, Conciliacion, EstadoReceta, Importacion, Receta, RegistroSistema
from ..normalizacion import formatear_fecha, parsear_fecha

AQUI = Path(__file__).parent
log = logging.getLogger(__name__)

ETIQUETAS_RESULTADO = {  # en orden de urgencia
    Resultado.CON_DIFERENCIAS: "Con diferencias",
    Resultado.RECETA_SIN_REGISTRO: "Sin carga en el sistema",
    Resultado.REGISTRO_SIN_RECETA: "Carga sin receta",
    Resultado.OBSERVADA: "Revisar",
    Resultado.OK: "OK",
}
ETIQUETAS_SITUACION = {
    EstadoReceta.ERROR: "Error de lectura",
    EstadoReceta.PENDIENTE: "Cargar datos",
    EstadoReceta.PROCESANDO: "Leyendo…",
    "sin_conciliar": "Sin conciliar",
    **ETIQUETAS_RESULTADO,
}
ETIQUETAS_SEVERIDAD = {Severidad.ERROR: "Error", Severidad.ADVERTENCIA: "Revisar", Severidad.INFO: "Info"}
ETIQUETAS_CRITERIO = {
    Criterio.AUTORIZACION: "número de autorización",
    Criterio.NRO_RECETA: "número de receta",
    Criterio.AFILIADO_FECHA: "afiliado y fecha (la receta no tiene números para cruzar)",
    Criterio.EN_IMAGEN: "sus números en la imagen (lectura sin IA)",
}
CAMPOS_FORMULARIO = (
    servicios.CAMPOS_TEXTO_RECETA
    + servicios.CAMPOS_FECHA_RECETA
    + servicios.CAMPOS_SI_NO_RECETA
    + servicios.CAMPOS_IMPORTE_RECETA
)


ZONA_ARGENTINA = timezone(timedelta(hours=-3))  # Argentina no tiene horario de verano


def fecha_hora(valor: datetime | None) -> str:
    if valor is None:
        return ""
    if valor.tzinfo is None:  # la base guarda UTC
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(ZONA_ARGENTINA).strftime("%d/%m/%Y %H:%M")


def situacion(receta: Receta) -> str:
    """Estado a mostrar en la bandeja: primero la lectura, después el resultado de la conciliación."""
    if receta.estado not in EstadoReceta.CON_DATOS:
        return receta.estado
    return receta.conciliacion.resultado if receta.conciliacion else "sin_conciliar"


def redirigir(url: str, **parametros: str | None) -> RedirectResponse:
    consulta = urlencode({k: v for k, v in parametros.items() if v})
    return RedirectResponse(f"{url}?{consulta}" if consulta else url, status_code=303)


def crear_app(
    config: Config | None = None, extractor: Extractor | None = None, extractor_ia: Extractor | None = None
) -> FastAPI:
    """`extractor`: lectura automática al subir cada receta (por defecto, sin IA).
    `extractor_ia`: lectura con IA a pedido, receta por receta (si hay clave de la API)."""
    config = config or Config.desde_entorno()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    engine = crear_engine(config.database_url)
    inicializar(engine)
    sesiones = crear_sesiones(engine)
    almacen = AlmacenLocal(config.archivos_dir)
    reglas = Reglas.desde_toml(config.reglas_path) if config.reglas_path.exists() else Reglas()
    fuentes = cargar_fuentes(config.fuentes_dir)
    if extractor_ia is None and config.lectura_ia:
        extractor_ia = ExtractorClaude(config.modelo, config.esfuerzo)
    if extractor is None:
        if config.lector == "local":
            extractor = LectorLocal(config.ocr)
        elif config.lector == "claude":
            extractor = extractor_ia
    if not config.auth_activa:
        log.warning("GESTIFARMA_USUARIO / GESTIFARMA_CLAVE sin definir: la app queda abierta (solo para pruebas).")

    plantillas = Jinja2Templates(directory=AQUI / "templates")
    plantillas.env.filters["fecha"] = lambda valor: formatear_fecha(valor) or ""
    plantillas.env.filters["fecha_hora"] = fecha_hora
    plantillas.env.globals.update(
        etiquetas_situacion=ETIQUETAS_SITUACION,
        etiquetas_resultado=ETIQUETAS_RESULTADO,
        etiquetas_severidad=ETIQUETAS_SEVERIDAD,
        etiquetas_criterio=ETIQUETAS_CRITERIO,
        situacion=situacion,
        lectura_automatica=extractor is not None,
        lectura_sin_ia=isinstance(extractor, LectorLocal),
        ia_a_pedido=extractor_ia is not None,
    )

    def render(request: Request, plantilla: str, **contexto) -> HTMLResponse:
        contexto.setdefault("msg", request.query_params.get("msg"))
        contexto.setdefault("error", request.query_params.get("error"))
        return plantillas.TemplateResponse(request, plantilla, contexto)

    seguridad = HTTPBasic(auto_error=False)

    def verificar_acceso(credenciales: HTTPBasicCredentials | None = Depends(seguridad)) -> None:
        if not config.auth_activa:
            return
        if credenciales is not None:
            usuario_ok = secrets.compare_digest(credenciales.username.encode(), config.usuario.encode())
            clave_ok = secrets.compare_digest(credenciales.password.encode(), config.clave.encode())
            if usuario_ok and clave_ok:
                return
        raise HTTPException(
            401, "Usuario o clave incorrectos", headers={"WWW-Authenticate": 'Basic realm="Gestifarma"'}
        )

    app = FastAPI(title="Gestifarma", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")

    @app.middleware("http")
    async def mismo_origen(request: Request, call_next):
        # Evita que otra página envíe formularios con las credenciales guardadas del navegador.
        origen = request.headers.get("origin")
        if request.method == "POST" and origen and urlparse(origen).netloc != request.url.netloc:
            return Response("Origen no permitido", status_code=403)
        return await call_next(request)

    @app.get("/salud", include_in_schema=False)
    def salud() -> Response:
        # Lo usan Docker, el script de actualización y el monitoreo: sin datos de recetas ni de pacientes.
        datos = {"estado": "ok", "version": version_instalada(), "base": "ok"}
        try:
            with sesiones() as sesion:
                sesion.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - cualquier falla de la base deja la app como no saludable
            log.exception("La base de datos no responde")
            datos.update(estado="error", base="error")
        return JSONResponse(datos, status_code=200 if datos["estado"] == "ok" else 503)

    rutas = APIRouter(dependencies=[Depends(verificar_acceso)])

    # --- Recetas ---------------------------------------------------------------------------------

    @rutas.get("/")
    def inicio():
        return RedirectResponse("/recetas", status_code=303)

    @rutas.get("/recetas", response_class=HTMLResponse)
    def bandeja(request: Request, filtro: str | None = None):
        with sesiones() as sesion:
            recetas = sesion.scalars(
                select(Receta)
                .options(selectinload(Receta.conciliaciones), selectinload(Receta.items))
                .order_by(Receta.id.desc())
                .limit(500)
            ).all()
            conteo = Counter(situacion(r) for r in recetas)
            if filtro:
                recetas = [r for r in recetas if situacion(r) == filtro]
            return render(request, "recetas.html", seccion="recetas", recetas=recetas, conteo=conteo, filtro=filtro)

    @rutas.get("/recetas/nueva", response_class=HTMLResponse)
    def nueva(request: Request):
        return render(request, "nueva.html", seccion="recetas")

    @rutas.post("/recetas")
    def subir(background: BackgroundTasks, archivos: list[UploadFile] = File(...), modo: str = Form("una")):
        subidos = [servicios.ArchivoSubido(a.filename or "archivo", a.file.read()) for a in archivos]
        subidos = [s for s in subidos if s.contenido]
        if not subidos:
            return redirigir("/recetas/nueva", error="No se recibió ningún archivo.")
        grupos = [subidos] if modo == "una" else [[s] for s in subidos]
        creadas, errores = [], []
        with sesiones() as sesion:
            for grupo in grupos:
                try:
                    creadas.append(
                        servicios.crear_receta(sesion, grupo, almacen, se_lee_con_ia=extractor is not None).id
                    )
                except ValueError as exc:
                    sesion.rollback()
                    errores.append(str(exc))
        if extractor is not None:
            for receta_id in creadas:
                background.add_task(servicios.leer_receta, receta_id, sesiones, extractor, almacen)
        if not creadas:
            return redirigir("/recetas/nueva", error=" ".join(errores))
        if len(creadas) == 1 and not errores:
            return redirigir(f"/recetas/{creadas[0]}")
        mensaje = f"Se subieron {len(creadas)} recetas." + (
            f" No se pudieron subir: {' '.join(errores)}" if errores else ""
        )
        return redirigir("/recetas", msg=mensaje)

    @rutas.get("/recetas/{receta_id}", response_class=HTMLResponse)
    def ver(request: Request, receta_id: int):
        with sesiones() as sesion:
            receta = sesion.get(Receta, receta_id)
            if receta is None:
                raise HTTPException(404, "La receta no existe")
            return render(request, "receta.html", seccion="recetas", receta=receta)

    @rutas.post("/recetas/{receta_id}")
    async def guardar(request: Request, receta_id: int):
        formulario = await request.form()
        campos = {campo: formulario.get(campo) for campo in CAMPOS_FORMULARIO}
        items = [
            {"descripcion": d, "cantidad": c, "troquel": t, "codigo_barras": b}
            for d, c, t, b in zip(
                formulario.getlist("item_descripcion"),
                formulario.getlist("item_cantidad"),
                formulario.getlist("item_troquel"),
                formulario.getlist("item_codigo_barras"),
            )
        ]

        def _guardar() -> None:
            with sesiones() as sesion:
                receta = sesion.get(Receta, receta_id)
                if receta is None:
                    raise HTTPException(404, "La receta no existe")
                servicios.actualizar_receta(receta, campos, items)
                sesion.commit()
                servicios.conciliar_y_guardar(sesion, reglas)

        try:
            await run_in_threadpool(_guardar)
        except ValueError as exc:
            return redirigir(f"/recetas/{receta_id}", error=f"No se guardó: {exc}")
        return redirigir(f"/recetas/{receta_id}", msg="Datos guardados y conciliación actualizada.")

    @rutas.post("/recetas/{receta_id}/leer")
    def releer(background: BackgroundTasks, receta_id: int, con: str = Form("auto")):
        lector = extractor_ia if con == "ia" else extractor
        if lector is None:
            return redirigir(
                f"/recetas/{receta_id}", error="Esa lectura no está configurada (para la IA falta ANTHROPIC_API_KEY)."
            )
        with sesiones() as sesion:
            receta = sesion.get(Receta, receta_id)
            if receta is None:
                raise HTTPException(404, "La receta no existe")
            receta.estado = EstadoReceta.PROCESANDO
            sesion.commit()
        background.add_task(servicios.leer_receta, receta_id, sesiones, lector, almacen)
        return redirigir(f"/recetas/{receta_id}")

    @rutas.post("/recetas/{receta_id}/eliminar")
    def eliminar(receta_id: int):
        with sesiones() as sesion:
            receta = sesion.get(Receta, receta_id)
            if receta is not None:
                servicios.eliminar_receta(sesion, receta, almacen)
        return redirigir("/recetas", msg=f"Se eliminó la receta #{receta_id}.")

    @rutas.get("/archivos/{archivo_id}")
    def archivo(archivo_id: int):
        with sesiones() as sesion:
            registro = sesion.get(ArchivoReceta, archivo_id)
            if registro is None:
                raise HTTPException(404, "El archivo no existe")
            return FileResponse(
                almacen.ruta(registro.ruta),
                media_type=registro.tipo_mime,
                headers={"Cache-Control": "private, max-age=3600"},
            )

    # --- Cargas del sistema (importación) ---------------------------------------------------------

    @rutas.get("/importaciones", response_class=HTMLResponse)
    def importaciones(request: Request):
        with sesiones() as sesion:
            lista = sesion.scalars(select(Importacion).order_by(Importacion.id.desc()).limit(50)).all()
            cargas = dict(
                sesion.execute(
                    select(RegistroSistema.importacion_id, func.count()).group_by(RegistroSistema.importacion_id)
                ).all()
            )
            return render(
                request,
                "importaciones.html",
                seccion="importaciones",
                importaciones=lista,
                cargas=cargas,
                fuentes=fuentes,
            )

    @rutas.post("/importaciones")
    def importar(fuente: str = Form(...), archivo: UploadFile = File(...)):
        mapeo = fuentes.get(fuente)
        if mapeo is None:
            return redirigir("/importaciones", error=f"Formato de reporte desconocido: {fuente}")
        nombre = Path(archivo.filename or "reporte.csv").name
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / f"reporte{Path(nombre).suffix.lower() or '.csv'}"
            ruta.write_bytes(archivo.file.read())
            with sesiones() as sesion:
                try:
                    resultado = servicios.importar(sesion, ruta, nombre, mapeo)
                except Exception as exc:  # archivo de otro formato, dañado, columnas faltantes...
                    log.warning("No se pudo importar %s: %s", nombre, exc)
                    return redirigir("/importaciones", error=f"No se pudo importar «{nombre}»: {exc}")
                mensaje = f"Se importaron {len(resultado.registros)} cargas ({resultado.filas_leidas} filas)."
                if resultado.errores:
                    mensaje += f" {len(resultado.errores)} filas con errores: ver el detalle abajo."
        return redirigir("/importaciones", msg=mensaje)

    # --- Conciliación ----------------------------------------------------------------------------

    @rutas.get("/conciliacion", response_class=HTMLResponse)
    def conciliacion(request: Request, filtro: str | None = None):
        with sesiones() as sesion:
            casos = sesion.scalars(
                select(Conciliacion).options(
                    selectinload(Conciliacion.receta).selectinload(Receta.items),
                    selectinload(Conciliacion.registro).selectinload(RegistroSistema.items),
                    selectinload(Conciliacion.discrepancias),
                )
            ).all()
            conteo = Counter(c.resultado for c in casos)
            orden = list(ETIQUETAS_RESULTADO)
            casos = sorted(casos, key=lambda c: (orden.index(c.resultado), c.id))
            if filtro:
                casos = [c for c in casos if c.resultado == filtro]
            sin_leer = sesion.scalar(
                select(func.count()).select_from(Receta).where(Receta.estado.not_in(EstadoReceta.CON_DATOS))
            )
            return render(
                request,
                "conciliacion.html",
                seccion="conciliacion",
                casos=casos,
                conteo=conteo,
                filtro=filtro,
                sin_leer=sin_leer,
            )

    @rutas.post("/conciliacion")
    def conciliar(desde: str = Form(""), hasta: str = Form(""), obra_social: str = Form("")):
        try:
            fecha_desde, fecha_hasta = parsear_fecha(desde), parsear_fecha(hasta)
        except ValueError as exc:
            return redirigir("/conciliacion", error=str(exc))
        with sesiones() as sesion:
            resumen = servicios.conciliar_y_guardar(
                sesion, reglas, fecha_desde, fecha_hasta, obra_social.strip() or None
            )
        mensaje = f"Conciliación lista: {resumen.total} casos revisados."
        if resumen.recetas_sin_leer:
            mensaje += f" Quedaron afuera {resumen.recetas_sin_leer} recetas que todavía no tienen datos."
        return redirigir("/conciliacion", msg=mensaje)

    @rutas.get("/conciliacion/diferencias.csv")
    def exportar():
        with sesiones() as sesion:
            contenido = servicios.exportar_csv(sesion)
        nombre = f"gestifarma-diferencias-{date.today():%Y%m%d}.csv"
        return Response(
            contenido.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    app.include_router(rutas)
    return app
