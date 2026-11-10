"""Configuración leída de variables de entorno (ver .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MODELO_POR_DEFECTO = "claude-opus-5-5"


def cargar_env(ruta: Path = Path(".env")) -> None:
    """Carga un archivo .env (CLAVE=valor). No pisa variables ya definidas ni carga valores vacíos.
    Así anda igual en PowerShell, cmd o bash, sin tener que exportar las variables a mano."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip().removeprefix("export ").strip()
        valor = valor.strip().strip('"').strip("'")
        if clave and valor and clave not in os.environ:
            os.environ[clave] = valor


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
    lector: str = "local"  # local (sin IA, sin costo por receta) | claude | manual
    ocr: str = "tesseract"  # tesseract | rapidocr

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
            database_url=os.environ.get(
                "GESTIFARMA_DATABASE_URL", f"sqlite:///{(data_dir / 'gestifarma.db').as_posix()}"
            ),
            config_dir=Path(os.environ.get("GESTIFARMA_CONFIG_DIR", "config")).resolve(),
            usuario=os.environ.get("GESTIFARMA_USUARIO") or None,
            clave=os.environ.get("GESTIFARMA_CLAVE") or None,
            lectura_ia=hay_credenciales_ia if lectura_ia is None else lectura_ia,
            modelo=os.environ.get("GESTIFARMA_MODELO", MODELO_POR_DEFECTO),
            esfuerzo=os.environ.get("GESTIFARMA_ESFUERZO", "medium"),
            lector=os.environ.get("GESTIFARMA_LECTOR", "local"),
            ocr=os.environ.get("GESTIFARMA_OCR", "tesseract"),
        )
