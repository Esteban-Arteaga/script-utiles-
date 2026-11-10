"""Tipos comunes de la conciliación (resultados, hallazgos) y reglas compartidas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..modelos import Receta, RegistroSistema
from ..normalizacion import formatear_fecha
from .reglas import ReglasObraSocial


class Severidad:
    ERROR = "error"
    ADVERTENCIA = "advertencia"
    INFO = "info"


class Resultado:
    OK = "ok"
    OBSERVADA = "observada"
    CON_DIFERENCIAS = "con_diferencias"
    RECETA_SIN_REGISTRO = "receta_sin_registro"
    REGISTRO_SIN_RECETA = "registro_sin_receta"


class Criterio:
    AUTORIZACION = "nro_autorizacion"
    NRO_RECETA = "nro_receta"
    AFILIADO_FECHA = "afiliado_y_fecha"
    EN_IMAGEN = "numeros_en_imagen"  # lectura sin IA: números de la carga encontrados en la imagen


@dataclass
class Hallazgo:
    campo: str
    severidad: str
    mensaje: str
    valor_receta: str | None = None
    valor_sistema: str | None = None


@dataclass
class ResultadoCruce:
    receta: Receta | None
    registro: RegistroSistema | None
    criterio: str | None = None
    hallazgos: list[Hallazgo] = field(default_factory=list)
    confirmados: list[str] = field(default_factory=list)  # lectura sin IA: datos encontrados en la imagen
    valores: dict = field(default_factory=dict)  # lectura sin IA: valores confirmados, para mostrar

    @property
    def resultado(self) -> str:
        if self.registro is None:
            return Resultado.RECETA_SIN_REGISTRO
        if self.receta is None:
            return Resultado.REGISTRO_SIN_RECETA
        severidades = {h.severidad for h in self.hallazgos}
        if Severidad.ERROR in severidades:
            return Resultado.CON_DIFERENCIAS
        if Severidad.ADVERTENCIA in severidades:
            return Resultado.OBSERVADA
        return Resultado.OK


def hallazgos_vigencia(prescripcion: date | None, dispensa: date | None, reglas_os: ReglasObraSocial) -> list[Hallazgo]:
    if not prescripcion or not dispensa:
        return []
    dias = (dispensa - prescripcion).days
    if dias < 0:
        return [
            Hallazgo(
                "fecha_dispensa",
                Severidad.ERROR,
                "La fecha de dispensa es anterior a la de prescripción.",
                formatear_fecha(prescripcion),
                formatear_fecha(dispensa),
            )
        ]
    if dias > reglas_os.dias_validez_receta:
        return [
            Hallazgo(
                "fecha_prescripcion",
                Severidad.ERROR,
                f"Receta vencida al dispensar: pasaron {dias} días desde la prescripción "
                f"(máximo {reglas_os.dias_validez_receta}).",
                formatear_fecha(prescripcion),
                formatear_fecha(dispensa),
            )
        ]
    return []
