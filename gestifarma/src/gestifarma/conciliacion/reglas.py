"""Reglas de conciliación configurables (config/reglas.toml).

Las reglas de negocio cambian por obra social (vigencia de la receta, cantidad máxima de
medicamentos, si exige diagnóstico, etc.). Se definen valores generales y excepciones por OS.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal
from pathlib import Path

from ..normalizacion import normalizar_texto, similitud


@dataclass(frozen=True)
class ReglasObraSocial:
    dias_validez_receta: int = 30
    max_items_por_receta: int = 3
    tolerancia_importe: Decimal = Decimal("1.00")
    exigir_firma_medico: bool = True
    exigir_sello_medico: bool = True
    exigir_firma_afiliado: bool = True
    exigir_diagnostico: bool = False


@dataclass(frozen=True)
class Similitud:
    umbral_nombre_ok: float = 0.85  # desde acá el nombre del afiliado se considera igual
    umbral_nombre_dudoso: float = 0.6  # entre este valor y el anterior: advertencia
    umbral_producto: float = 0.85  # desde acá el producto cargado es el recetado
    umbral_producto_minimo: float = 0.5  # debajo de esto no se considera el mismo producto
    umbral_obra_social: float = 0.8


@dataclass
class Reglas:
    general: ReglasObraSocial = field(default_factory=ReglasObraSocial)
    por_obra_social: dict[str, ReglasObraSocial] = field(default_factory=dict)
    alias: dict[str, str] = field(default_factory=dict)  # nombre normalizado -> nombre canónico
    similitud: Similitud = field(default_factory=Similitud)

    def canonica(self, obra_social: str | None) -> str:
        nombre = normalizar_texto(obra_social)
        return self.alias.get(nombre, nombre)

    def misma_obra_social(self, a: str | None, b: str | None) -> bool:
        ca, cb = self.canonica(a), self.canonica(b)
        if not ca or not cb:
            return False
        if ca == cb or similitud(ca, cb) >= self.similitud.umbral_obra_social:
            return True
        # "OSDE" / "OSDE 210": un nombre contiene al otro como palabra completa
        palabras_a, palabras_b = set(ca.split()), set(cb.split())
        return palabras_a <= palabras_b or palabras_b <= palabras_a

    def para(self, obra_social: str | None) -> ReglasObraSocial:
        return self.por_obra_social.get(self.canonica(obra_social), self.general)

    @classmethod
    def desde_toml(cls, ruta: Path) -> Reglas:
        with ruta.open("rb") as archivo:
            datos = tomllib.load(archivo)

        desconocidas = set(datos) - {"general", "obras_sociales", "alias_obras_sociales", "similitud"}
        if desconocidas:
            raise ValueError(f"{ruta}: secciones desconocidas {sorted(desconocidas)}")

        general = _armar(ReglasObraSocial(), datos.get("general", {}), f"{ruta} [general]")
        alias: dict[str, str] = {}
        for canonico, otros in datos.get("alias_obras_sociales", {}).items():
            for otro in otros:
                alias[normalizar_texto(otro)] = normalizar_texto(canonico)
        reglas = cls(
            general=general,
            alias=alias,
            similitud=_armar(Similitud(), datos.get("similitud", {}), f"{ruta} [similitud]"),
        )
        for nombre, valores in datos.get("obras_sociales", {}).items():
            reglas.por_obra_social[reglas.canonica(nombre)] = _armar(
                general, valores, f"{ruta} [obras_sociales.{nombre}]"
            )
        return reglas


def _armar(base, valores: dict, donde: str):
    """Pisa los valores de `base` con los del archivo, validando nombres y tipos."""
    permitidos = {f.name: f for f in fields(base)}
    cambios = {}
    for clave, valor in valores.items():
        if clave not in permitidos:
            raise ValueError(f"{donde}: clave desconocida {clave!r}. Válidas: {sorted(permitidos)}")
        actual = getattr(base, clave)
        if isinstance(actual, bool):
            if not isinstance(valor, bool):
                raise ValueError(f"{donde}: {clave} debe ser true o false")
        elif isinstance(actual, Decimal):
            valor = Decimal(str(valor))
        elif isinstance(actual, (int, float)) and (isinstance(valor, bool) or not isinstance(valor, (int, float))):
            raise ValueError(f"{donde}: {clave} debe ser un número")
        cambios[clave] = valor
    return replace(base, **cambios)
