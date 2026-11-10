"""Casos de uso de la aplicación. Los usan tanto la web como la línea de comandos."""

from __future__ import annotations

import csv
import io
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from .almacenamiento import AlmacenLocal
from .conciliacion.motor import conciliar, fecha_referencia
from .conciliacion.reglas import Reglas
from .conectores.archivo import MapeoArchivo, leer_archivo
from .extraccion import ArchivoNoSoportado, ExtraccionReceta, Extractor, ResultadoExtraccion, tipo_de_archivo
from .modelos import (
    ArchivoReceta,
    Conciliacion,
    Discrepancia,
    EstadoReceta,
    Importacion,
    ItemReceta,
    Receta,
    RegistroSistema,
)
from .normalizacion import formatear_fecha, parsear_entero, parsear_fecha, parsear_importe

log = logging.getLogger(__name__)

MAX_BYTES_ARCHIVO = 25 * 1024 * 1024

CAMPOS_TEXTO_RECETA = (
    "obra_social",
    "plan",
    "nro_afiliado",
    "afiliado_nombre",
    "afiliado_dni",
    "medico_nombre",
    "medico_matricula",
    "nro_receta",
    "nro_autorizacion",
    "diagnostico",
    "tipo_receta",
)
CAMPOS_FECHA_RECETA = ("fecha_prescripcion", "fecha_dispensa")
CAMPOS_SI_NO_RECETA = ("firma_medico", "sello_medico", "firma_afiliado")
CAMPOS_IMPORTE_RECETA = ("importe_total", "importe_obra_social")


@dataclass
class ArchivoSubido:
    nombre: str
    contenido: bytes


# --- Recetas -----------------------------------------------------------------------------------


def crear_receta(
    sesion: Session, archivos: list[ArchivoSubido], almacen: AlmacenLocal, se_lee_con_ia: bool = False
) -> Receta:
    """Guarda las fotos/PDF de UNA receta (frente, dorso...). Queda "procesando" si la va a leer la IA
    o "pendiente" para cargar los datos a mano."""
    archivos = [a for a in archivos if a.contenido]
    if not archivos:
        raise ValueError("No se recibió ningún archivo.")
    tipos = []  # se validan todos antes de guardar nada en disco
    for archivo in archivos:
        if len(archivo.contenido) > MAX_BYTES_ARCHIVO:
            raise ValueError(f"{archivo.nombre}: supera los 25 MB.")
        try:
            tipos.append(tipo_de_archivo(archivo.contenido))
        except ArchivoNoSoportado as exc:
            raise ValueError(f"{archivo.nombre}: {exc}") from exc
    receta = Receta(estado=EstadoReceta.PROCESANDO if se_lee_con_ia else EstadoReceta.PENDIENTE)
    for archivo, tipo in zip(archivos, tipos):
        ruta = almacen.guardar(archivo.contenido, archivo.nombre)
        receta.archivos.append(ArchivoReceta(nombre_original=archivo.nombre[:255], ruta=ruta, tipo_mime=tipo))
    sesion.add(receta)
    sesion.commit()
    return receta


def leer_receta(receta_id: int, sesiones: sessionmaker[Session], extractor: Extractor, almacen: AlmacenLocal) -> None:
    """Lee la receta con la IA y guarda los datos. Pensado para correr en segundo plano."""
    with sesiones() as sesion:
        receta = sesion.get(Receta, receta_id)
        if receta is None:
            return
        receta.estado = EstadoReceta.PROCESANDO
        receta.error = None
        sesion.commit()
        try:
            archivos = [(almacen.leer(a.ruta), a.nombre_original) for a in receta.archivos]
            resultado = extractor.extraer(archivos)
        except Exception as exc:  # red, API, archivo dañado: se registra y se puede reintentar
            log.exception("No se pudo leer la receta %s", receta_id)
            receta.estado = EstadoReceta.ERROR
            receta.error = f"No se pudo leer la receta: {exc}"
            sesion.commit()
            return
        aplicar_extraccion(receta, resultado)
        sesion.commit()


def aplicar_extraccion(receta: Receta, resultado: ResultadoExtraccion) -> None:
    datos = resultado.datos
    if not datos.es_receta:
        receta.estado = EstadoReceta.ERROR
        receta.error = "La imagen no parece una receta. Revisar el archivo."
        receta.extraccion = resultado.como_json()
        return
    _volcar_datos(receta, datos)
    receta.extraccion = resultado.como_json()
    receta.estado = EstadoReceta.PARA_REVISAR
    receta.error = None


def receta_desde_extraccion(datos: ExtraccionReceta) -> Receta:
    """Crea una receta ya leída (se usa para la demo y para importar lecturas hechas en otro lado)."""
    receta = Receta(estado=EstadoReceta.PARA_REVISAR)
    _volcar_datos(receta, datos)
    return receta


def _volcar_datos(receta: Receta, datos: ExtraccionReceta) -> None:
    for campo in CAMPOS_TEXTO_RECETA + CAMPOS_FECHA_RECETA + CAMPOS_SI_NO_RECETA:
        setattr(receta, campo, getattr(datos, campo))
    for campo in CAMPOS_IMPORTE_RECETA:
        valor = getattr(datos, campo)
        setattr(receta, campo, None if valor is None else Decimal(str(valor)).quantize(Decimal("0.01")))
    receta.items = [
        ItemReceta(descripcion=i.descripcion, cantidad=i.cantidad, troquel=i.troquel, codigo_barras=i.codigo_barras)
        for i in datos.items
    ]
    receta.campos_dudosos = list(datos.campos_dudosos)
    receta.observaciones = datos.observaciones


def actualizar_receta(receta: Receta, campos: dict[str, str | None], items: list[dict[str, str | None]]) -> None:
    """Guarda la revisión del backoffice (formulario). Lanza ValueError si un dato no es válido."""
    errores = []
    for campo in CAMPOS_TEXTO_RECETA:
        if campo in campos:
            setattr(receta, campo, (campos[campo] or "").strip() or None)
    for campo in CAMPOS_FECHA_RECETA:
        if campo in campos:
            try:
                setattr(receta, campo, parsear_fecha(campos[campo]))
            except ValueError as exc:
                errores.append(f"{campo}: {exc}")
    for campo in CAMPOS_SI_NO_RECETA:
        if campo in campos:
            setattr(receta, campo, {"si": True, "no": False}.get((campos[campo] or "").strip().lower()))
    for campo in CAMPOS_IMPORTE_RECETA:
        if campo in campos:
            try:
                setattr(receta, campo, parsear_importe(campos[campo], separador_decimal="auto"))
            except ValueError as exc:
                errores.append(f"{campo}: {exc}")
    nuevos = []
    for numero, item in enumerate(items, start=1):
        descripcion = (item.get("descripcion") or "").strip()
        if not descripcion:
            continue
        try:
            cantidad = parsear_entero(item.get("cantidad"))
        except ValueError as exc:
            errores.append(f"medicamento {numero}: {exc}")
            continue
        nuevos.append(
            ItemReceta(
                descripcion=descripcion,
                cantidad=cantidad,
                troquel=(item.get("troquel") or "").strip() or None,
                codigo_barras=(item.get("codigo_barras") or "").strip() or None,
            )
        )
    if errores:
        raise ValueError("; ".join(errores))
    receta.items = nuevos
    receta.campos_dudosos = []  # una persona ya revisó los datos
    receta.estado = EstadoReceta.REVISADA
    receta.error = None


def eliminar_receta(sesion: Session, receta: Receta, almacen: AlmacenLocal) -> None:
    rutas = [a.ruta for a in receta.archivos]
    sesion.delete(receta)
    sesion.commit()
    for ruta in rutas:
        almacen.eliminar(ruta)


# --- Importación de lo cargado en el sistema ----------------------------------------------------


def importar(sesion: Session, ruta: Path, nombre_archivo: str, mapeo: MapeoArchivo) -> Importacion:
    """Importa un reporte exportado del sistema. Si una carga ya existía (misma fuente y número de
    autorización o de receta), la reemplaza: así se puede volver a importar después de corregir."""
    lectura = leer_archivo(ruta, mapeo)
    importacion = Importacion(
        fuente=mapeo.nombre, nombre_archivo=nombre_archivo[:255], filas_leidas=lectura.filas, errores=lectura.errores
    )
    claves = [r.clave for r in lectura.registros if r.clave]
    if claves:
        anteriores = sesion.scalars(
            select(RegistroSistema).where(RegistroSistema.fuente == mapeo.nombre, RegistroSistema.clave.in_(claves))
        )
        for anterior in anteriores:
            sesion.delete(anterior)
        sesion.flush()
    importacion.registros = lectura.registros
    sesion.add(importacion)
    sesion.commit()
    return importacion


# --- Conciliación -------------------------------------------------------------------------------


@dataclass
class ResumenConciliacion:
    por_resultado: Counter = field(default_factory=Counter)
    recetas_sin_leer: int = 0

    @property
    def total(self) -> int:
        return sum(self.por_resultado.values())


def conciliar_y_guardar(
    sesion: Session,
    reglas: Reglas,
    desde: date | None = None,
    hasta: date | None = None,
    obra_social: str | None = None,
) -> ResumenConciliacion:
    """Cruza las recetas leídas con las cargas importadas (opcionalmente de un período / una obra
    social) y reemplaza los resultados anteriores de esas recetas y cargas."""

    def entra(objeto) -> bool:
        fecha = fecha_referencia(objeto)
        if desde and (fecha is None or fecha < desde):
            return False
        if hasta and (fecha is None or fecha > hasta):
            return False
        return not obra_social or reglas.misma_obra_social(objeto.obra_social, obra_social)

    todas = sesion.scalars(select(Receta).options(selectinload(Receta.items))).all()
    recetas = [r for r in todas if r.estado in EstadoReceta.CON_DATOS and entra(r)]
    sin_leer = sum(1 for r in todas if r.estado not in EstadoReceta.CON_DATOS and entra(r))
    registros = [
        r
        for r in sesion.scalars(select(RegistroSistema).options(selectinload(RegistroSistema.items))).all()
        if entra(r)
    ]

    ids_recetas = [r.id for r in recetas]
    ids_registros = [r.id for r in registros]
    anteriores = sesion.scalars(
        select(Conciliacion).where(
            or_(Conciliacion.receta_id.in_(ids_recetas), Conciliacion.registro_id.in_(ids_registros))
        )
    )
    for anterior in anteriores:
        sesion.delete(anterior)
    sesion.flush()

    resumen = ResumenConciliacion(recetas_sin_leer=sin_leer)
    for cruce in conciliar(recetas, registros, reglas):
        sesion.add(
            Conciliacion(
                receta=cruce.receta,
                registro=cruce.registro,
                resultado=cruce.resultado,
                criterio=cruce.criterio,
                confirmados=cruce.confirmados,
                discrepancias=[
                    Discrepancia(
                        campo=h.campo,
                        severidad=h.severidad,
                        mensaje=h.mensaje,
                        valor_receta=_recortar(h.valor_receta),
                        valor_sistema=_recortar(h.valor_sistema),
                    )
                    for h in cruce.hallazgos
                ],
            )
        )
        if cruce.receta is not None and cruce.valores:
            # Lectura sin IA: se muestran en la receta los datos que se encontraron en la imagen.
            for campo, valor in cruce.valores.items():
                setattr(cruce.receta, campo, valor)
            cruce.receta.campos_dudosos = [c for c in cruce.receta.campos_dudosos or [] if c not in cruce.valores]
        resumen.por_resultado[cruce.resultado] += 1
    sesion.commit()
    return resumen


def _recortar(valor: str | None) -> str | None:
    return valor[:255] if valor else valor


def exportar_csv(sesion: Session) -> str:
    """Planilla con todas las diferencias, para corregir en el sistema antes de presentar."""
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(
        [
            "Resultado",
            "Receta Gestifarma",
            "Obra social",
            "Nro afiliado",
            "Afiliado",
            "Nro autorización",
            "Nro receta",
            "Fecha dispensa",
            "Severidad",
            "Campo",
            "Detalle",
            "Valor en receta",
            "Valor en sistema",
        ]
    )
    conciliaciones = sesion.scalars(
        select(Conciliacion)
        .options(
            selectinload(Conciliacion.receta),
            selectinload(Conciliacion.registro),
            selectinload(Conciliacion.discrepancias),
        )
        .order_by(Conciliacion.id)
    ).all()
    for c in conciliaciones:
        cabecera = [
            c.resultado,
            c.receta.id if c.receta else "",
            _dato(c, "obra_social") or "",
            _dato(c, "nro_afiliado") or "",
            _dato(c, "afiliado_nombre") or "",
            _dato(c, "nro_autorizacion") or "",
            _dato(c, "nro_receta") or "",
            formatear_fecha(_dato(c, "fecha_dispensa")) or "",
        ]
        if not c.discrepancias:
            escritor.writerow(cabecera + ["", "", "Sin diferencias", "", ""])
        for d in c.discrepancias:
            escritor.writerow(cabecera + [d.severidad, d.campo, d.mensaje, d.valor_receta or "", d.valor_sistema or ""])
    return "\ufeff" + salida.getvalue()  # BOM: Excel en castellano abre bien los acentos


def _dato(conciliacion: Conciliacion, campo: str):
    """El dato de la carga del sistema o, si no hay carga, el de la receta."""
    return getattr(conciliacion.registro, campo, None) or getattr(conciliacion.receta, campo, None)
