"""Conciliación de recetas leídas SIN IA: se buscan en el texto de la imagen los datos de la carga.

Una receta leída por OCR no tiene sus datos ordenados en campos confiables. En lugar de interpretarla,
se toma cada dato de la carga del sistema y se busca en el texto:
- aparece: confirmado;
- aparece algo muy parecido (un dígito distinto, otra fecha, otra obra social): posible diferencia;
- no aparece: no se pudo confirmar, hay que mirarlo.

Los datos de la receta se buscan solo en el FRENTE: el ticket de validación del dorso lo imprime el
propio sistema con lo cargado, así que confirmaría cualquier cosa. Del dorso se toman el número de
autorización, los troqueles y sus códigos de barras.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property

from ..busqueda import (
    CONFIRMADO,
    NO_ENCONTRADO,
    Busqueda,
    Estado,
    buscar_fecha,
    buscar_nombre,
    buscar_numero,
    buscar_producto,
    cantidad_en,
    concentraciones_en,
    contiene_frase,
    fechas,
    numeros,
    renglon,
    solo_digitos,
)
from ..modelos import EstadoReceta, ItemRegistro, Receta, RegistroSistema
from ..normalizacion import concentraciones, formatear_fecha, normalizar_matricula, normalizar_texto
from .reglas import Reglas
from .tipos import Criterio, Hallazgo, Severidad, hallazgos_vigencia

AVISO_LECTURA = " (Lectura automática: confirmar en la imagen.)"
PUNTAJE_MINIMO = 5


@dataclass
class TextoReceta:
    frente: str
    dorso: str = ""
    codigos: list[str] = field(default_factory=list)

    @classmethod
    def de(cls, receta: Receta) -> TextoReceta | None:
        """Texto de una receta leída sin IA y todavía no revisada por una persona (si no, None)."""
        lectura = receta.extraccion or {}
        if lectura.get("lector") != "local" or receta.estado != EstadoReceta.PARA_REVISAR:
            return None
        paginas = lectura.get("paginas") or []
        return cls(
            frente="\n".join(p.get("texto", "") for p in paginas if p.get("lado") == "frente"),
            dorso="\n".join(p.get("texto", "") for p in paginas if p.get("lado") != "frente"),
            codigos=[c for p in paginas for c in p.get("codigos", [])],
        )

    @cached_property
    def todo(self) -> str:
        return "\n".join([self.frente, self.dorso, *self.codigos])

    @cached_property
    def numeros_frente(self) -> set[str]:
        return numeros(self.frente)

    @cached_property
    def numeros_todo(self) -> set[str]:
        return numeros(self.todo)

    @cached_property
    def fechas_frente(self) -> set:
        return set(fechas(self.frente))


@dataclass
class Verificacion:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    confirmados: list[str] = field(default_factory=list)
    valores: dict = field(default_factory=dict)

    def confirmar(self, etiqueta: str, campo: str | None = None, valor=None) -> None:
        self.confirmados.append(etiqueta)
        if campo:
            self.valores[campo] = valor

    def agregar(self, campo: str, severidad: str, mensaje: str, receta=None, sistema=None) -> None:
        self.hallazgos.append(Hallazgo(campo, severidad, mensaje, _texto(receta), _texto(sistema)))


def _texto(valor) -> str | None:
    return None if valor is None else str(valor)


# --- Emparejamiento por los números que aparecen en la imagen ----------------------------------


def _base_afiliado(valor: str | None) -> str:
    """Número de afiliado sin el sufijo de parentesco ("123456/01" -> "123456")."""
    return solo_digitos(valor.rsplit("/", 1)[0]) if valor and "/" in valor else ""


def emparejar_por_texto(
    recetas: list[Receta], textos: dict[int, TextoReceta], registros: list[RegistroSistema], reglas: Reglas
) -> tuple[list[tuple[Receta, RegistroSistema, str]], list[Receta], list[RegistroSistema]]:
    """Empareja cada receta con la carga cuyos números (autorización, receta, afiliado) aparecen en su
    imagen; la fecha y los medicamentos desempatan (por ejemplo, dos recetas del mismo afiliado)."""
    indice: dict[str, set[int]] = defaultdict(set)
    for receta in recetas:
        for numero in textos[id(receta)].numeros_todo:
            indice[numero].add(id(receta))
    por_id = {id(r): r for r in recetas}
    orden = {id(r): i for i, r in enumerate(recetas)}

    candidatos = []
    for j, registro in enumerate(registros):
        puntajes: Counter = Counter()
        for valor, peso in ((registro.nro_autorizacion, 6), (registro.nro_receta, 6)):
            numero = solo_digitos(valor)
            if len(numero) >= 4:
                for receta_id in indice.get(numero, ()):
                    puntajes[receta_id] += peso
        afiliado, base = solo_digitos(registro.nro_afiliado), _base_afiliado(registro.nro_afiliado)
        con_afiliado = indice.get(afiliado, set()) if len(afiliado) >= 4 else set()
        con_base = indice.get(base, set()) if len(base) >= 4 else set()
        for receta_id in con_afiliado | con_base:
            puntajes[receta_id] += 5 if receta_id in con_afiliado else 4
        for receta_id, puntaje in puntajes.items():
            texto = textos[receta_id]
            if registro.fecha_prescripcion and registro.fecha_prescripcion in texto.fechas_frente:
                puntaje += 3
            if any(_producto(item, texto, reglas).confirmado for item in registro.items):
                puntaje += 2
            if puntaje >= PUNTAJE_MINIMO:
                candidatos.append((-puntaje, orden[receta_id], j, receta_id))

    pares, usadas, usados = [], set(), set()
    for _, _, j, receta_id in sorted(candidatos):
        if receta_id in usadas or j in usados:
            continue
        usadas.add(receta_id)
        usados.add(j)
        pares.append((por_id[receta_id], registros[j], Criterio.EN_IMAGEN))
    return (
        pares,
        [r for r in recetas if id(r) not in usadas],
        [r for j, r in enumerate(registros) if j not in usados],
    )


# --- Verificación de cada dato -------------------------------------------------------------------


def _producto(item: ItemRegistro, texto: TextoReceta, reglas: Reglas) -> Busqueda:
    return buscar_producto(item.descripcion, item.monodroga, texto.frente, reglas.similitud.umbral_producto)


def _obra_social(esperada: str | None, texto: str, reglas: Reglas, otras: set[str]) -> Busqueda:
    if not esperada:
        return NO_ENCONTRADO
    canonica = reglas.canonica(esperada)
    nombres = {esperada, canonica} | {alias for alias, c in reglas.alias.items() if c == canonica}
    if any(contiene_frase(nombre, texto) for nombre in nombres):
        return CONFIRMADO
    for otra in sorted(otras):
        if not reglas.misma_obra_social(otra, esperada) and contiene_frase(otra, texto):
            return Busqueda(Estado.PARECIDO, leido=otra)
    return NO_ENCONTRADO


def verificar(
    texto: TextoReceta, registro: RegistroSistema, reglas: Reglas, otras_obras_sociales: set[str]
) -> Verificacion:
    v = Verificacion()
    reglas_os = reglas.para(registro.obra_social)
    error, advertencia = Severidad.ERROR, Severidad.ADVERTENCIA

    if registro.obra_social:
        b = _obra_social(registro.obra_social, texto.frente, reglas, otras_obras_sociales)
        if b.confirmado:
            v.confirmar("obra social")  # no se copia: la receta puede usar otro nombre (alias)
        elif b.estado == Estado.PARECIDO:
            v.agregar(
                "obra_social",
                error,
                f"La receta parece ser de {b.leido} y se cargó {registro.obra_social}." + AVISO_LECTURA,
                b.leido,
                registro.obra_social,
            )
        else:
            v.agregar(
                "obra_social",
                advertencia,
                "No se pudo confirmar la obra social en la imagen.",
                None,
                registro.obra_social,
            )

    if registro.plan:
        if contiene_frase(registro.plan, texto.frente):
            v.confirmar("plan", "plan", registro.plan)
        else:
            otro = _plan_en(texto.frente)
            if otro and normalizar_texto(otro) != normalizar_texto(registro.plan):
                v.agregar(
                    "plan",
                    advertencia,
                    f"El plan de la receta parece ser {otro} y se cargó {registro.plan} "
                    "(puede cambiar el porcentaje de cobertura)." + AVISO_LECTURA,
                    otro,
                    registro.plan,
                )

    if registro.nro_afiliado:
        b = buscar_numero(registro.nro_afiliado, texto.frente, texto.numeros_frente)
        base = _base_afiliado(registro.nro_afiliado)
        if b.confirmado:
            v.confirmar("número de afiliado", "nro_afiliado", registro.nro_afiliado)
        elif base and base in texto.numeros_frente:
            v.agregar(
                "nro_afiliado",
                advertencia,
                "El número de afiliado coincide pero no se pudo confirmar el sufijo (¿parentesco?). Verificar.",
                None,
                registro.nro_afiliado,
            )
        elif b.estado == Estado.PARECIDO:
            v.agregar(
                "nro_afiliado",
                error,
                "Posible diferencia en el número de afiliado." + AVISO_LECTURA,
                b.leido,
                registro.nro_afiliado,
            )
        else:
            v.agregar(
                "nro_afiliado",
                advertencia,
                "No se pudo confirmar el número de afiliado en la imagen.",
                None,
                registro.nro_afiliado,
            )

    if registro.afiliado_nombre:
        b = buscar_nombre(registro.afiliado_nombre, texto.frente, reglas.similitud.umbral_nombre_ok)
        if b.confirmado:
            v.confirmar("nombre del afiliado", "afiliado_nombre", registro.afiliado_nombre)
        elif b.estado == Estado.PARECIDO:
            v.agregar(
                "afiliado_nombre",
                advertencia,
                "El nombre del afiliado se parece pero no es igual. Verificar.",
                b.leido,
                registro.afiliado_nombre,
            )
        else:
            v.agregar(
                "afiliado_nombre",
                advertencia,
                "No se pudo confirmar el nombre del afiliado en la imagen.",
                None,
                registro.afiliado_nombre,
            )

    if registro.medico_matricula:
        b = buscar_numero(normalizar_matricula(registro.medico_matricula), texto.frente, texto.numeros_frente)
        if b.confirmado:
            v.confirmar("matrícula del médico", "medico_matricula", registro.medico_matricula)
        elif b.estado == Estado.PARECIDO:
            v.agregar(
                "medico_matricula",
                error,
                "Posible diferencia en la matrícula del médico." + AVISO_LECTURA,
                b.leido,
                registro.medico_matricula,
            )
        else:
            v.agregar(
                "medico_matricula",
                advertencia,
                "No se pudo confirmar la matrícula del médico en la imagen.",
                None,
                registro.medico_matricula,
            )

    if registro.fecha_prescripcion:
        b = buscar_fecha(registro.fecha_prescripcion, texto.frente)
        sistema = formatear_fecha(registro.fecha_prescripcion)
        if b.confirmado:
            v.confirmar("fecha de prescripción", "fecha_prescripcion", registro.fecha_prescripcion)
        elif b.estado == Estado.PARECIDO:
            v.agregar(
                "fecha_prescripcion", error, "La fecha de la receta parece ser otra." + AVISO_LECTURA, b.leido, sistema
            )
        else:
            v.agregar(
                "fecha_prescripcion",
                advertencia,
                "No se pudo confirmar la fecha de prescripción en la imagen.",
                None,
                sistema,
            )
    v.hallazgos += hallazgos_vigencia(registro.fecha_prescripcion, registro.fecha_dispensa, reglas_os)

    if (
        registro.nro_autorizacion
        and buscar_numero(registro.nro_autorizacion, texto.todo, texto.numeros_todo).confirmado
    ):
        v.confirmar("número de autorización", "nro_autorizacion", registro.nro_autorizacion)

    for item in registro.items:
        _verificar_item(v, item, texto, reglas)

    if len(registro.items) > reglas_os.max_items_por_receta:
        v.agregar(
            "items",
            error,
            f"Se cargaron {len(registro.items)} medicamentos y el máximo para esta obra social "
            f"es {reglas_os.max_items_por_receta}.",
        )
    if reglas_os.exigir_diagnostico and not re.search(r"\bDIAGN|\bDX\b", normalizar_texto(texto.frente)):
        v.agregar("diagnostico", advertencia, "No se encontró el diagnóstico en la receta y esta obra social lo exige.")
    return v


def _verificar_item(v: Verificacion, item: ItemRegistro, texto: TextoReceta, reglas: Reglas) -> None:
    error, advertencia = Severidad.ERROR, Severidad.ADVERTENCIA
    nombre = item.descripcion
    b = _producto(item, texto, reglas)
    if b.estado == Estado.NO_ENCONTRADO:
        v.agregar("items", advertencia, f"No se pudo confirmar «{nombre}» en la receta.", None, nombre)
    elif b.estado == Estado.PARECIDO:
        v.agregar(
            "items",
            advertencia,
            f"Verificar que «{nombre}» sea lo recetado: en la receta se lee «{b.leido}».",
            b.leido,
            nombre,
        )
    else:
        zona = renglon(texto.frente, b.linea, siguientes=1)
        en_receta, cargada = concentraciones_en(zona), concentraciones(nombre)
        if en_receta and cargada and not en_receta & cargada:
            v.agregar(
                "items",
                error,
                f"La concentración recetada para «{nombre}» parece ser otra." + AVISO_LECTURA,
                _concentraciones(en_receta),
                _concentraciones(cargada),
            )
        else:
            v.confirmar(nombre)
        cantidad = cantidad_en(zona)
        if item.cantidad is not None:
            if cantidad is not None and item.cantidad > cantidad:
                v.agregar(
                    "cantidad",
                    error,
                    f"Se cargaron {item.cantidad} de «{nombre}» y en la receta se lee {cantidad}." + AVISO_LECTURA,
                    cantidad,
                    item.cantidad,
                )
            elif cantidad is None and item.cantidad > 1:
                v.agregar(
                    "cantidad",
                    advertencia,
                    f"Se cargaron {item.cantidad} de «{nombre}»: confirmar la cantidad recetada.",
                    None,
                    item.cantidad,
                )

    hay_dorso = bool(texto.dorso.strip() or texto.codigos)
    for campo, etiqueta in (("troquel", "troquel"), ("codigo_barras", "código de barras")):
        valor = getattr(item, campo)
        if not valor:
            continue
        en_codigos = solo_digitos(valor) in {solo_digitos(c) for c in texto.codigos}
        if en_codigos or buscar_numero(valor, texto.dorso).confirmado:
            v.confirmar(f"{etiqueta} {valor}")
        elif hay_dorso:
            v.agregar(campo, advertencia, f"No se pudo confirmar el {etiqueta} {valor} en el dorso.", None, valor)


def _plan_en(texto: str) -> str | None:
    """ "Plan 210", "PLAN: 310" o "Plan Oro" tal como figura en la receta."""
    coincidencia = re.search(r"\bPLAN\s*:?\s*([A-Z0-9]+)\b", normalizar_texto(texto))
    return f"PLAN {coincidencia.group(1)}" if coincidencia else None


def _concentraciones(valores) -> str:
    return ", ".join(f"{numero} {unidad}" for numero, unidad in sorted(valores))
