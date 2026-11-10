"""Motor de conciliación: cruza recetas con cargas del sistema y lista las diferencias.

1. Empareja cada receta con su carga: por número de autorización, por número de receta o,
   si la receta no los tiene, por afiliado + fecha + medicamentos.
2. Compara campo por campo y genera hallazgos con severidad:
   - error: diferencia que provoca un débito o un cobro mal hecho (corregir antes de presentar).
   - advertencia: hay que mirarlo (lectura dudosa, nombre parecido pero no igual, dato faltante).
   - info: para saber (un medicamento recetado que no se dispensó).
3. Las recetas sin carga y las cargas sin receta también se informan.

Es lógica pura (no toca la base de datos): recibe objetos y devuelve resultados.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..modelos import ItemReceta, ItemRegistro, Receta, RegistroSistema
from ..normalizacion import (
    concentraciones,
    formatear_fecha,
    normalizar_id,
    normalizar_matricula,
    normalizar_texto,
    similitud_nombres,
    similitud_productos,
)
from .reglas import Reglas, ReglasObraSocial


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


def conciliar(recetas: Iterable[Receta], registros: Iterable[RegistroSistema], reglas: Reglas) -> list[ResultadoCruce]:
    pares, recetas_libres, registros_libres = emparejar(list(recetas), list(registros), reglas)
    resultados = [
        ResultadoCruce(receta, registro, criterio, comparar(receta, registro, reglas))
        for receta, registro, criterio in pares
    ]
    for receta in recetas_libres:
        mensaje = (
            "No se encontró la carga de esta receta en el sistema. Si se dispensó, "
            "falta cargarla (si no se carga, no se cobra)."
        )
        claves_dudosas = {"nro_afiliado", "nro_autorizacion", "nro_receta"} & set(receta.campos_dudosos or [])
        if claves_dudosas or not receta.nro_afiliado:
            mensaje += (
                " Puede que la carga exista y no se haya encontrado porque el número de afiliado o de "
                "autorización no se leyó bien: revisarlo en la imagen y volver a conciliar."
            )
        hallazgos = [Hallazgo("carga", Severidad.ERROR, mensaje)]
        hallazgos += controles_receta(receta, reglas.para(receta.obra_social))
        resultados.append(ResultadoCruce(receta, None, None, _marcar_dudosos(receta, hallazgos)))
    for registro in registros_libres:
        resultados.append(
            ResultadoCruce(
                None,
                registro,
                None,
                [
                    Hallazgo(
                        "receta",
                        Severidad.ERROR,
                        "Hay una carga en el sistema sin receta escaneada. Si la receta física "
                        "no está, la obra social la va a debitar.",
                    )
                ],
            )
        )
    return resultados


# --- Emparejamiento receta <-> carga -----------------------------------------------------------


def emparejar(
    recetas: list[Receta], registros: list[RegistroSistema], reglas: Reglas
) -> tuple[list[tuple[Receta, RegistroSistema, str]], list[Receta], list[RegistroSistema]]:
    pares: list[tuple[Receta, RegistroSistema, str]] = []
    recetas_libres = list(recetas)
    registros_libres = list(registros)

    for criterio in (Criterio.AUTORIZACION, Criterio.NRO_RECETA):
        indice: dict[str, list[RegistroSistema]] = defaultdict(list)
        for registro in registros_libres:
            clave = normalizar_id(getattr(registro, criterio))
            if clave:
                indice[clave].append(registro)
        quedan = []
        for receta in recetas_libres:
            clave = normalizar_id(getattr(receta, criterio))
            if clave and indice.get(clave):
                registro = indice[clave].pop(0)
                pares.append((receta, registro, criterio))
                registros_libres.remove(registro)
            else:
                quedan.append(receta)
        recetas_libres = quedan

    # Sin números en común: mismo afiliado y receta compatible (fecha o medicamentos).
    por_afiliado: dict[str, list[RegistroSistema]] = defaultdict(list)
    for registro in registros_libres:
        afiliado = _base_afiliado(registro.nro_afiliado)
        if afiliado:
            por_afiliado[afiliado].append(registro)
    candidatos = []
    for i, receta in enumerate(recetas_libres):
        for j, registro in enumerate(por_afiliado.get(_base_afiliado(receta.nro_afiliado), [])):
            puntaje = _puntaje_heuristico(receta, registro, reglas)
            if puntaje > 0:
                candidatos.append((puntaje, -i, -j, receta, registro))
    candidatos.sort(key=lambda c: c[:3], reverse=True)
    usadas, usados = set(), set()
    for _puntaje, _i, _j, receta, registro in candidatos:
        if id(receta) in usadas or id(registro) in usados:
            continue
        usadas.add(id(receta))
        usados.add(id(registro))
        pares.append((receta, registro, Criterio.AFILIADO_FECHA))

    return (
        pares,
        [r for r in recetas_libres if id(r) not in usadas],
        [r for r in registros_libres if id(r) not in usados],
    )


def _puntaje_heuristico(receta: Receta, registro: RegistroSistema, reglas: Reglas) -> int:
    puntaje = 0
    if receta.fecha_prescripcion and receta.fecha_prescripcion == registro.fecha_prescripcion:
        puntaje += 2
    if receta.fecha_dispensa and registro.fecha_dispensa:
        if abs((receta.fecha_dispensa - registro.fecha_dispensa).days) <= 3:
            puntaje += 1
    pares, _, _ = emparejar_items(receta.items, registro.items, reglas)
    if any(p >= reglas.similitud.umbral_producto for _, _, p in pares):
        puntaje += 1
    return puntaje


# --- Comparación campo por campo ---------------------------------------------------------------


def comparar(receta: Receta, registro: RegistroSistema, reglas: Reglas) -> list[Hallazgo]:
    reglas_os = reglas.para(receta.obra_social or registro.obra_social)
    hallazgos = (
        _comparar_obra_social(receta, registro, reglas)
        + _comparar_afiliado(receta, registro, reglas)
        + _comparar_medico(receta, registro)
        + _comparar_fechas(receta, registro, reglas_os)
        + _comparar_items(receta, registro, reglas)
        + _comparar_importes(receta, registro, reglas_os)
        + controles_receta(receta, reglas_os)
    )
    return _marcar_dudosos(receta, hallazgos)


def controles_receta(receta: Receta, reglas_os: ReglasObraSocial) -> list[Hallazgo]:
    """Requisitos de la receta en sí (no dependen de lo cargado)."""
    hallazgos: list[Hallazgo] = []
    if reglas_os.exigir_firma_medico:
        hallazgos += _presencia(receta.firma_medico, "firma_medico", "la firma del médico")
    if reglas_os.exigir_sello_medico:
        hallazgos += _presencia(receta.sello_medico, "sello_medico", "el sello del médico")
    if reglas_os.exigir_firma_afiliado:
        hallazgos += _presencia(receta.firma_afiliado, "firma_afiliado", "la firma del afiliado en el dorso")
    if reglas_os.exigir_diagnostico and not receta.diagnostico:
        hallazgos.append(
            Hallazgo("diagnostico", Severidad.ERROR, "La receta no tiene diagnóstico y esta obra social lo exige.")
        )
    if not receta.items:
        hallazgos.append(Hallazgo("items", Severidad.ADVERTENCIA, "No se pudo leer ningún medicamento en la receta."))
    elif len(receta.items) > reglas_os.max_items_por_receta:
        hallazgos.append(
            Hallazgo(
                "items",
                Severidad.ERROR,
                f"La receta tiene {len(receta.items)} medicamentos y el máximo para esta obra social "
                f"es {reglas_os.max_items_por_receta}.",
            )
        )
    return hallazgos


def _presencia(valor: bool | None, campo: str, descripcion: str) -> list[Hallazgo]:
    if valor is False:
        return [Hallazgo(campo, Severidad.ERROR, f"Falta {descripcion}.")]
    if valor is None:
        return [Hallazgo(campo, Severidad.ADVERTENCIA, f"No se pudo verificar {descripcion} (no se ve en la imagen).")]
    return []


def _comparar_obra_social(receta: Receta, registro: RegistroSistema, reglas: Reglas) -> list[Hallazgo]:
    hallazgos = []
    if not receta.obra_social:
        hallazgos.append(
            Hallazgo(
                "obra_social",
                Severidad.ADVERTENCIA,
                "No se pudo leer la obra social en la receta.",
                None,
                registro.obra_social,
            )
        )
    elif registro.obra_social and not reglas.misma_obra_social(receta.obra_social, registro.obra_social):
        hallazgos.append(
            Hallazgo(
                "obra_social",
                Severidad.ERROR,
                "La obra social de la receta no coincide con la cargada. Si es la misma con otro "
                "nombre, agregarla como alias en config/reglas.toml.",
                receta.obra_social,
                registro.obra_social,
            )
        )
    if receta.plan and registro.plan and normalizar_texto(receta.plan) != normalizar_texto(registro.plan):
        hallazgos.append(
            Hallazgo(
                "plan",
                Severidad.ADVERTENCIA,
                "El plan no coincide (puede cambiar el porcentaje de cobertura).",
                receta.plan,
                registro.plan,
            )
        )
    return hallazgos


def _base_afiliado(valor: str | None) -> str:
    """Número de afiliado sin el sufijo de parentesco ("123456/01" -> "123456")."""
    if not valor:
        return ""
    return normalizar_id(valor.rsplit("/", 1)[0])


def _comparar_afiliado(receta: Receta, registro: RegistroSistema, reglas: Reglas) -> list[Hallazgo]:
    hallazgos = []
    en_receta, en_sistema = normalizar_id(receta.nro_afiliado), normalizar_id(registro.nro_afiliado)
    if not en_receta:
        hallazgos.append(
            Hallazgo(
                "nro_afiliado",
                Severidad.ADVERTENCIA,
                "No se pudo leer el número de afiliado en la receta.",
                None,
                registro.nro_afiliado,
            )
        )
    elif en_sistema and en_receta != en_sistema:
        if _base_afiliado(receta.nro_afiliado) == _base_afiliado(registro.nro_afiliado):
            hallazgos.append(
                Hallazgo(
                    "nro_afiliado",
                    Severidad.ADVERTENCIA,
                    "El número de afiliado coincide pero cambia el sufijo (¿parentesco?). Verificar.",
                    receta.nro_afiliado,
                    registro.nro_afiliado,
                )
            )
        else:
            hallazgos.append(
                Hallazgo(
                    "nro_afiliado",
                    Severidad.ERROR,
                    "El número de afiliado no coincide.",
                    receta.nro_afiliado,
                    registro.nro_afiliado,
                )
            )

    if receta.afiliado_nombre and registro.afiliado_nombre:
        parecido = similitud_nombres(receta.afiliado_nombre, registro.afiliado_nombre)
        if parecido < reglas.similitud.umbral_nombre_dudoso:
            hallazgos.append(
                Hallazgo(
                    "afiliado_nombre",
                    Severidad.ERROR,
                    "El nombre del afiliado no coincide.",
                    receta.afiliado_nombre,
                    registro.afiliado_nombre,
                )
            )
        elif parecido < reglas.similitud.umbral_nombre_ok:
            hallazgos.append(
                Hallazgo(
                    "afiliado_nombre",
                    Severidad.ADVERTENCIA,
                    "El nombre del afiliado se parece pero no es igual. Verificar.",
                    receta.afiliado_nombre,
                    registro.afiliado_nombre,
                )
            )
    return hallazgos


def _comparar_medico(receta: Receta, registro: RegistroSistema) -> list[Hallazgo]:
    en_receta = normalizar_matricula(receta.medico_matricula)
    en_sistema = normalizar_matricula(registro.medico_matricula)
    if not en_receta:
        return [
            Hallazgo(
                "medico_matricula",
                Severidad.ADVERTENCIA,
                "No se pudo leer la matrícula del médico en la receta.",
                None,
                registro.medico_matricula,
            )
        ]
    if en_sistema and en_receta != en_sistema:
        return [
            Hallazgo(
                "medico_matricula",
                Severidad.ERROR,
                "La matrícula del médico no coincide.",
                receta.medico_matricula,
                registro.medico_matricula,
            )
        ]
    return []


def _comparar_fechas(receta: Receta, registro: RegistroSistema, reglas_os: ReglasObraSocial) -> list[Hallazgo]:
    hallazgos = []
    if receta.fecha_prescripcion is None:
        hallazgos.append(
            Hallazgo(
                "fecha_prescripcion",
                Severidad.ADVERTENCIA,
                "No se pudo leer la fecha de prescripción.",
                None,
                formatear_fecha(registro.fecha_prescripcion),
            )
        )
    elif registro.fecha_prescripcion and receta.fecha_prescripcion != registro.fecha_prescripcion:
        hallazgos.append(
            Hallazgo(
                "fecha_prescripcion",
                Severidad.ERROR,
                "La fecha de prescripción cargada no coincide con la de la receta.",
                formatear_fecha(receta.fecha_prescripcion),
                formatear_fecha(registro.fecha_prescripcion),
            )
        )

    if receta.fecha_dispensa and registro.fecha_dispensa and receta.fecha_dispensa != registro.fecha_dispensa:
        hallazgos.append(
            Hallazgo(
                "fecha_dispensa",
                Severidad.ADVERTENCIA,
                "La fecha de dispensa de la receta no coincide con la cargada.",
                formatear_fecha(receta.fecha_dispensa),
                formatear_fecha(registro.fecha_dispensa),
            )
        )

    prescripcion = receta.fecha_prescripcion or registro.fecha_prescripcion
    dispensa = registro.fecha_dispensa or receta.fecha_dispensa
    if prescripcion and dispensa:
        dias = (dispensa - prescripcion).days
        if dias < 0:
            hallazgos.append(
                Hallazgo(
                    "fecha_dispensa",
                    Severidad.ERROR,
                    "La fecha de dispensa es anterior a la de prescripción.",
                    formatear_fecha(prescripcion),
                    formatear_fecha(dispensa),
                )
            )
        elif dias > reglas_os.dias_validez_receta:
            hallazgos.append(
                Hallazgo(
                    "fecha_prescripcion",
                    Severidad.ERROR,
                    f"Receta vencida al dispensar: pasaron {dias} días desde la prescripción "
                    f"(máximo {reglas_os.dias_validez_receta}).",
                    formatear_fecha(prescripcion),
                    formatear_fecha(dispensa),
                )
            )
    return hallazgos


def emparejar_items(
    items_receta: list[ItemReceta], items_registro: list[ItemRegistro], reglas: Reglas
) -> tuple[list[tuple[ItemReceta, ItemRegistro, float]], list[ItemReceta], list[ItemRegistro]]:
    """Asocia cada producto cargado con un medicamento de la receta (el par más parecido primero)."""
    candidatos = []
    for i, recetado in enumerate(items_receta):
        for j, cargado in enumerate(items_registro):
            puntaje = _puntaje_producto(recetado, cargado)
            if puntaje >= reglas.similitud.umbral_producto_minimo:
                candidatos.append((puntaje, -i, -j))
    candidatos.sort(reverse=True)
    pares, usados_receta, usados_registro = [], set(), set()
    for puntaje, menos_i, menos_j in candidatos:
        i, j = -menos_i, -menos_j
        if i in usados_receta or j in usados_registro:
            continue
        usados_receta.add(i)
        usados_registro.add(j)
        pares.append((items_receta[i], items_registro[j], puntaje))
    return (
        pares,
        [x for i, x in enumerate(items_receta) if i not in usados_receta],
        [x for j, x in enumerate(items_registro) if j not in usados_registro],
    )


def _puntaje_producto(recetado: ItemReceta, cargado: ItemRegistro) -> float:
    for campo in ("troquel", "codigo_barras"):
        a, b = normalizar_id(getattr(recetado, campo)), normalizar_id(getattr(cargado, campo))
        if a and b and a == b:
            return 1.0
    return similitud_productos(recetado.descripcion, cargado.descripcion, cargado.monodroga)


def _comparar_items(receta: Receta, registro: RegistroSistema, reglas: Reglas) -> list[Hallazgo]:
    hallazgos = []
    pares, solo_receta, solo_sistema = emparejar_items(receta.items, registro.items, reglas)
    for recetado, cargado, puntaje in pares:
        if puntaje < reglas.similitud.umbral_producto:
            hallazgos.append(
                Hallazgo(
                    "items",
                    Severidad.ADVERTENCIA,
                    f"Verificar que «{cargado.descripcion}» sea lo recetado («{recetado.descripcion}»).",
                    recetado.descripcion,
                    cargado.descripcion,
                )
            )
        conc_receta, conc_sistema = concentraciones(recetado.descripcion), concentraciones(cargado.descripcion)
        if conc_receta and conc_sistema and not conc_receta & conc_sistema:
            hallazgos.append(
                Hallazgo(
                    "items",
                    Severidad.ERROR,
                    f"La concentración cargada no coincide con la recetada para «{recetado.descripcion}».",
                    _texto_concentraciones(conc_receta),
                    _texto_concentraciones(conc_sistema),
                )
            )
        for campo, nombre in (("troquel", "El troquel"), ("codigo_barras", "El código de barras")):
            a, b = getattr(recetado, campo), getattr(cargado, campo)
            if normalizar_id(a) and normalizar_id(b) and normalizar_id(a) != normalizar_id(b):
                hallazgos.append(
                    Hallazgo(
                        campo,
                        Severidad.ERROR,
                        f"{nombre} de la receta no coincide con el cargado para «{cargado.descripcion}».",
                        a,
                        b,
                    )
                )
        if cargado.cantidad is not None:
            if recetado.cantidad is None and cargado.cantidad > 1:
                hallazgos.append(
                    Hallazgo(
                        "cantidad",
                        Severidad.ADVERTENCIA,
                        f"La receta no indica cantidad y se cargaron {cargado.cantidad} de «{cargado.descripcion}».",
                        None,
                        str(cargado.cantidad),
                    )
                )
            elif recetado.cantidad is not None and cargado.cantidad > recetado.cantidad:
                hallazgos.append(
                    Hallazgo(
                        "cantidad",
                        Severidad.ERROR,
                        f"Se cargaron {cargado.cantidad} de «{cargado.descripcion}» y la receta indica "
                        f"{recetado.cantidad}.",
                        str(recetado.cantidad),
                        str(cargado.cantidad),
                    )
                )
    for cargado in solo_sistema:
        hallazgos.append(
            Hallazgo(
                "items",
                Severidad.ERROR,
                f"Se cargó «{cargado.descripcion}» y no figura en la receta.",
                None,
                cargado.descripcion,
            )
        )
    for recetado in solo_receta:
        hallazgos.append(
            Hallazgo(
                "items",
                Severidad.INFO,
                f"«{recetado.descripcion}» está recetado pero no se cargó (si se entregó, falta cargarlo).",
                recetado.descripcion,
                None,
            )
        )
    return hallazgos


def _texto_concentraciones(valores: set[tuple[Decimal, str]]) -> str:
    return ", ".join(f"{numero} {unidad}" for numero, unidad in sorted(valores))


def _comparar_importes(receta: Receta, registro: RegistroSistema, reglas_os: ReglasObraSocial) -> list[Hallazgo]:
    hallazgos = []
    for campo, nombre in (
        ("importe_total", "El importe total"),
        ("importe_obra_social", "El importe a cargo de la obra social"),
    ):
        en_receta, en_sistema = getattr(receta, campo), getattr(registro, campo)
        if en_receta is None or en_sistema is None:
            continue
        if abs(Decimal(str(en_receta)) - Decimal(str(en_sistema))) > reglas_os.tolerancia_importe:
            hallazgos.append(
                Hallazgo(
                    campo,
                    Severidad.ERROR,
                    f"{nombre} del ticket no coincide con el cargado.",
                    str(en_receta),
                    str(en_sistema),
                )
            )
    return hallazgos


_CAMPOS_DE_ITEMS = {"items", "cantidad", "troquel", "codigo_barras"}


def _marcar_dudosos(receta: Receta, hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Si la IA leyó el campo con dudas, el hallazgo puede ser un error de lectura: avisarlo."""
    dudosos = set(receta.campos_dudosos or [])
    for hallazgo in hallazgos:
        campo = "items" if hallazgo.campo in _CAMPOS_DE_ITEMS else hallazgo.campo
        if campo in dudosos and hallazgo.severidad != Severidad.INFO:
            hallazgo.mensaje += " (Ojo: la lectura de este dato en la receta es dudosa; confirmar en la imagen.)"
    return hallazgos


def fecha_referencia(objeto: Receta | RegistroSistema) -> date | None:
    """Fecha para filtrar por período: dispensa, si no prescripción, si no la de carga en Gestifarma."""
    fecha = objeto.fecha_dispensa or objeto.fecha_prescripcion
    if fecha is None and isinstance(objeto, Receta) and objeto.creada_en:
        fecha = objeto.creada_en.date()
    return fecha
