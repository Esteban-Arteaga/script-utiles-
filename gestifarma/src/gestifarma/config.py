"""Configuración leída de variables de entorno (ver .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MODELO_POR_DEFECTO = "claude-opus-5-5"


def _si_no(valor: str | None) -> bool | None:
    if valor is None or not valor.strip():
        return None
    return valor.strip().lower() in ("1", "si", "sí", "true", "yes")


@dataclass(frozen=True)
class Config:
    data_dir: Path
    database_url: str
    config_dir: Path
    usuario: str | None = None
    clave: str | None = None
    lectura_ia: bool = False
    modelo: str = MODELO_POR_DEFECTO
    esfuerzo: str = "medium"

    @property
    def archivos_dir(self) -> Path:
        return self.data_dir / "archivos"

    @property
    def reglas_path(self) -> Path:
        return self.config_dir / "reglas.toml"

    @property
    def fuentes_dir(self) -> Path:
        return self.config_dir / "fuentes"

    @property
    def auth_activa(self) -> bool:
        return bool(self.usuario and self.clave)

    @classmethod
    def desde_entorno(cls) -> Config:
        data_dir = Path(os.environ.get("GESTIFARMA_DATA_DIR", "datos")).resolve()
        hay_credenciales_ia = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        lectura_ia = _si_no(os.environ.get("GESTIFARMA_LECTURA_IA"))
        return cls(
            data_dir=data_dir,
            database_url=os.environ.get("GESTIFARMA_DATABASE_URL", f"sqlite:///{data_dir / 'gestifarma.db'}"),
            config_dir=Path(os.environ.get("GESTIFARMA_CONFIG_DIR", "config")).resolve(),
            usuario=os.environ.get("GESTIFARMA_USUARIO") or None,
            clave=os.environ.get("GESTIFARMA_CLAVE") or None,
            lectura_ia=hay_credenciales_ia if lectura_ia is None else lectura_ia,
            modelo=os.environ.get("GESTIFARMA_MODELO", MODELO_POR_DEFECTO),
            esfuerzo=os.environ.get("GESTIFARMA_ESFUERZO", "medium"),
        )
