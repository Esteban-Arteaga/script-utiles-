"""Conexión a la base de datos (SQLite para el piloto, PostgreSQL en producción)."""

from __future__ import annotations

import warnings

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session, sessionmaker

from .modelos import Base

# SQLite guarda los importes como punto flotante; para el piloto alcanza (en PostgreSQL son exactos).
warnings.filterwarnings("ignore", message=r"Dialect sqlite\+pysqlite does \*not\* support Decimal", category=SAWarning)


def crear_engine(database_url: str) -> Engine:
    if not database_url.startswith("sqlite"):
        return create_engine(database_url, pool_pre_ping=True)

    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _configurar_sqlite(conexion, _registro):
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def crear_sesiones(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


# Columnas agregadas después de la primera versión: (tabla, columna, tipo SQL).
_COLUMNAS_NUEVAS = [("conciliaciones", "confirmados", "JSON")]


def inicializar(engine: Engine) -> None:
    """Crea las tablas y columnas que falten. Cuando el esquema se estabilice, pasar a migraciones (Alembic)."""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conexion:
        for tabla, columna, tipo in _COLUMNAS_NUEVAS:
            if columna not in {c["name"] for c in inspector.get_columns(tabla)}:
                conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}"))
