"""Modelo de datos.

- Receta: lo que dice la receta (leído por la IA desde la foto y/o corregido por el backoffice).
- RegistroSistema: lo que la farmacia cargó en el sistema de la obra social / gerenciadora / colegio.
- Conciliacion + Discrepancia: el resultado de cruzar ambas cosas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def ahora() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class EstadoReceta:
    PENDIENTE = "pendiente"  # subida; falta leerla (o la lectura automática está apagada)
    PROCESANDO = "procesando"  # la IA la está leyendo
    PARA_REVISAR = "para_revisar"  # leída por la IA; se puede conciliar
    REVISADA = "revisada"  # datos confirmados o corregidos por el backoffice
    ERROR = "error"  # no se pudo leer: reintentar o cargar a mano

    CON_DATOS = (PARA_REVISAR, REVISADA)


class Receta(Base):
    __tablename__ = "recetas"

    id: Mapped[int] = mapped_column(primary_key=True)
    creada_en: Mapped[datetime] = mapped_column(default=ahora)
    actualizada_en: Mapped[datetime] = mapped_column(default=ahora, onupdate=ahora)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoReceta.PENDIENTE, index=True)

    tipo_receta: Mapped[str | None] = mapped_column(String(20))
    obra_social: Mapped[str | None] = mapped_column(String(120))
    plan: Mapped[str | None] = mapped_column(String(60))
    nro_afiliado: Mapped[str | None] = mapped_column(String(40), index=True)
    afiliado_nombre: Mapped[str | None] = mapped_column(String(160))
    afiliado_dni: Mapped[str | None] = mapped_column(String(20))
    medico_nombre: Mapped[str | None] = mapped_column(String(160))
    medico_matricula: Mapped[str | None] = mapped_column(String(40))
    fecha_prescripcion: Mapped[date | None]
    fecha_dispensa: Mapped[date | None]
    nro_receta: Mapped[str | None] = mapped_column(String(60), index=True)
    nro_autorizacion: Mapped[str | None] = mapped_column(String(60), index=True)
    diagnostico: Mapped[str | None] = mapped_column(String(255))
    firma_medico: Mapped[bool | None]
    sello_medico: Mapped[bool | None]
    firma_afiliado: Mapped[bool | None]
    importe_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importe_obra_social: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # Campos que la IA leyó con dudas: se marcan para que el backoffice los mire en la imagen.
    campos_dudosos: Mapped[list[str]] = mapped_column(JSON, default=list)
    observaciones: Mapped[str | None] = mapped_column(Text)
    # Respuesta completa de la IA (datos, modelo usado y consumo de tokens) para trazabilidad y costos.
    extraccion: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    archivos: Mapped[list[ArchivoReceta]] = relationship(
        back_populates="receta", cascade="all, delete-orphan", order_by="ArchivoReceta.id"
    )
    items: Mapped[list[ItemReceta]] = relationship(
        back_populates="receta", cascade="all, delete-orphan", order_by="ItemReceta.id"
    )
    conciliaciones: Mapped[list[Conciliacion]] = relationship(
        back_populates="receta", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def conciliacion(self) -> Conciliacion | None:
        return self.conciliaciones[-1] if self.conciliaciones else None


class ArchivoReceta(Base):
    __tablename__ = "archivos_receta"

    id: Mapped[int] = mapped_column(primary_key=True)
    receta_id: Mapped[int] = mapped_column(ForeignKey("recetas.id", ondelete="CASCADE"), index=True)
    nombre_original: Mapped[str] = mapped_column(String(255))
    ruta: Mapped[str] = mapped_column(String(255))
    tipo_mime: Mapped[str] = mapped_column(String(80))
    creado_en: Mapped[datetime] = mapped_column(default=ahora)

    receta: Mapped[Receta] = relationship(back_populates="archivos")


class ItemReceta(Base):
    __tablename__ = "items_receta"

    id: Mapped[int] = mapped_column(primary_key=True)
    receta_id: Mapped[int] = mapped_column(ForeignKey("recetas.id", ondelete="CASCADE"), index=True)
    descripcion: Mapped[str] = mapped_column(String(255))
    cantidad: Mapped[int | None]
    troquel: Mapped[str | None] = mapped_column(String(40))
    codigo_barras: Mapped[str | None] = mapped_column(String(40))

    receta: Mapped[Receta] = relationship(back_populates="items")


class Importacion(Base):
    """Un archivo exportado del sistema (o descargado por el robot) que se importó."""

    __tablename__ = "importaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    creada_en: Mapped[datetime] = mapped_column(default=ahora)
    fuente: Mapped[str] = mapped_column(String(80))
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    filas_leidas: Mapped[int] = mapped_column(default=0)
    errores: Mapped[list[str]] = mapped_column(JSON, default=list)

    registros: Mapped[list[RegistroSistema]] = relationship(
        back_populates="importacion", cascade="all, delete-orphan", passive_deletes=True
    )


class RegistroSistema(Base):
    """Una carga (dispensa validada) tal como figura en el sistema externo."""

    __tablename__ = "registros"

    id: Mapped[int] = mapped_column(primary_key=True)
    importacion_id: Mapped[int | None] = mapped_column(ForeignKey("importaciones.id", ondelete="CASCADE"), index=True)
    fuente: Mapped[str] = mapped_column(String(80), index=True)
    # Clave normalizada (autorización, nro de receta o, si no tiene ninguno, un hash de sus datos):
    # al reimportar, reemplaza la carga anterior.
    clave: Mapped[str | None] = mapped_column(String(80), index=True)

    nro_receta: Mapped[str | None] = mapped_column(String(60))
    nro_autorizacion: Mapped[str | None] = mapped_column(String(60))
    obra_social: Mapped[str | None] = mapped_column(String(120))
    plan: Mapped[str | None] = mapped_column(String(60))
    nro_afiliado: Mapped[str | None] = mapped_column(String(40))
    afiliado_nombre: Mapped[str | None] = mapped_column(String(160))
    medico_matricula: Mapped[str | None] = mapped_column(String(40))
    fecha_prescripcion: Mapped[date | None]
    fecha_dispensa: Mapped[date | None]
    importe_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importe_obra_social: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    datos_originales: Mapped[list[dict]] = mapped_column(JSON, default=list)

    importacion: Mapped[Importacion | None] = relationship(back_populates="registros")
    items: Mapped[list[ItemRegistro]] = relationship(
        back_populates="registro", cascade="all, delete-orphan", order_by="ItemRegistro.id"
    )
    conciliaciones: Mapped[list[Conciliacion]] = relationship(
        back_populates="registro", cascade="all, delete-orphan", passive_deletes=True
    )


class ItemRegistro(Base):
    __tablename__ = "items_registro"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), index=True)
    descripcion: Mapped[str] = mapped_column(String(255))
    monodroga: Mapped[str | None] = mapped_column(String(160))
    cantidad: Mapped[int | None]
    troquel: Mapped[str | None] = mapped_column(String(40))
    codigo_barras: Mapped[str | None] = mapped_column(String(40))
    importe: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cobertura_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    registro: Mapped[RegistroSistema] = relationship(back_populates="items")


class Conciliacion(Base):
    __tablename__ = "conciliaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    creada_en: Mapped[datetime] = mapped_column(default=ahora)
    receta_id: Mapped[int | None] = mapped_column(ForeignKey("recetas.id", ondelete="CASCADE"), index=True)
    registro_id: Mapped[int | None] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), index=True)
    resultado: Mapped[str] = mapped_column(String(30), index=True)
    criterio: Mapped[str | None] = mapped_column(String(30))  # cómo se encontró la carga
    # Lectura sin IA: qué datos de la carga se encontraron en la imagen.
    confirmados: Mapped[list[str]] = mapped_column(JSON, default=list)

    receta: Mapped[Receta | None] = relationship(back_populates="conciliaciones")
    registro: Mapped[RegistroSistema | None] = relationship(back_populates="conciliaciones")
    discrepancias: Mapped[list[Discrepancia]] = relationship(
        back_populates="conciliacion", cascade="all, delete-orphan", order_by="Discrepancia.id"
    )


class Discrepancia(Base):
    __tablename__ = "discrepancias"

    id: Mapped[int] = mapped_column(primary_key=True)
    conciliacion_id: Mapped[int] = mapped_column(ForeignKey("conciliaciones.id", ondelete="CASCADE"), index=True)
    campo: Mapped[str] = mapped_column(String(60))
    severidad: Mapped[str] = mapped_column(String(15))
    mensaje: Mapped[str] = mapped_column(Text)
    valor_receta: Mapped[str | None] = mapped_column(String(255))
    valor_sistema: Mapped[str | None] = mapped_column(String(255))

    conciliacion: Mapped[Conciliacion] = relationship(back_populates="discrepancias")
