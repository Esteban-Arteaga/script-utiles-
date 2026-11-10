"""Búsqueda tolerante de datos en el texto leído por OCR.

El OCR confunde letras con números (O/0, I/1, S/5), corta números con espacios ("12345678901 2/00") y
pierde signos. En lugar de interpretar la receta campo por campo, se busca en el texto cada dato que
figura en la carga del sistema y se informa si aparece igual, parecido (un dígito distinto: posible
diferencia) o no aparece (hay que mirarlo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .normalizacion import (
    PALABRAS_VACIAS_NOMBRE,
    concentraciones,
    normalizar_id,
    normalizar_texto,
    palabras_producto,
    similitud,
    sin_acentos,
)


class Estado:
    CONFIRMADO = "confirmado"
    PARECIDO = "parecido"  # aparece algo muy parecido: posible diferencia (o error de lectura)
    NO_ENCONTRADO = "no_encontrado"


@dataclass(frozen=True)
class Busqueda:
    estado: str
    leido: str | None = None  # lo que se leyó, cuando es PARECIDO
    linea: int | None = None  # dónde se encontró (para productos)

    @property
    def confirmado(self) -> bool:
        return self.estado == Estado.CONFIRMADO


CONFIRMADO = Busqueda(Estado.CONFIRMADO)
NO_ENCONTRADO = Busqueda(Estado.NO_ENCONTRADO)

_CONFUNDIBLES = "OQDILZSBG|!"
_CONFUSIONES = str.maketrans(
    {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "!": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
)
_RE_FECHA = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})(?!\d)")
_NUMEROS_EN_LETRAS = {"UN": 1, "UNO": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6}


def _es_numerico(token: str) -> bool:
    """Token que es un número aunque el OCR haya confundido algún dígito con una letra ("1O/11/2O26")."""
    if not any(c.isdigit() for c in token):
        return False
    utiles = sum(1 for c in token if c.isdigit() or c in _CONFUNDIBLES or c in "/.-")
    return utiles / len(token) >= 0.6


_UNIDAD_MAL_LEIDA = re.compile(r"(?<=\d)\s*(?:M9|RNG|MQ)\b")  # "20 m9", "20 rng" = "20 mg"


def corregir_numeros(texto: str) -> str:
    """Mayúsculas sin acentos y con las confusiones típicas corregidas dentro de los números."""
    lineas = []
    for linea in sin_acentos(texto).upper().splitlines():
        linea = " ".join(t.translate(_CONFUSIONES) if _es_numerico(t) else t for t in linea.split())
        lineas.append(_UNIDAD_MAL_LEIDA.sub(" MG", linea))
    return "\n".join(lineas)


def solo_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "").lstrip("0")


def numeros(texto: str) -> set[str]:
    """Números del texto como dígitos sin ceros adelante: cada grupo ("123/00" -> "123"), el número
    completo sin separadores ("12300") y la unión de hasta 3 números seguidos en la misma línea,
    porque el OCR a veces corta un número con un espacio."""
    resultado: set[str] = set()
    for linea in corregir_numeros(texto).splitlines():
        corridas, actual = [], []
        for token in (t.strip(".,:;()[]") for t in linea.split()):
            if token and any(c.isdigit() for c in token) and re.fullmatch(r"[0-9/.\-]+", token):
                actual.append(token)
            elif actual:
                corridas.append(actual)
                actual = []
        if actual:
            corridas.append(actual)
        for corrida in corridas:
            for i in range(len(corrida)):
                for j in range(i + 1, min(i + 3, len(corrida)) + 1):
                    unidos = "".join(corrida[i:j])
                    resultado.add(solo_digitos(unidos))
                    resultado.update(solo_digitos(grupo) for grupo in re.split(r"[/.\-]", unidos))
    resultado.discard("")
    return resultado


def _a_lo_sumo_un_cambio(a: str, b: str) -> bool:
    """Distancia de edición <= 1 (un dígito cambiado, de más o de menos)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    corto, largo = sorted((a, b), key=len)
    i = 0
    while i < len(corto) and corto[i] == largo[i]:
        i += 1
    return corto[i:] == largo[i + 1 :]


def buscar_numero(esperado: str | None, texto: str, candidatos: set[str] | None = None) -> Busqueda:
    """¿Aparece en el texto el número cargado (afiliado, matrícula, autorización, troquel...)?"""
    if not esperado:
        return NO_ENCONTRADO
    if re.search(r"[A-Za-z]", esperado):  # identificador con letras: se busca tal cual, sin signos
        plano = re.sub(r"[^A-Z0-9]", "", corregir_numeros(texto))
        return CONFIRMADO if normalizar_id(esperado) in plano else NO_ENCONTRADO
    objetivo = solo_digitos(esperado)
    if len(objetivo) < 3:
        return NO_ENCONTRADO
    candidatos = numeros(texto) if candidatos is None else candidatos
    if objetivo in candidatos or (len(objetivo) >= 8 and any(objetivo in c for c in candidatos)):
        return CONFIRMADO
    if len(objetivo) >= 5:
        for candidato in sorted(candidatos, key=lambda c: (len(c), c)):
            if _a_lo_sumo_un_cambio(objetivo, candidato):
                return Busqueda(Estado.PARECIDO, leido=candidato)
    return NO_ENCONTRADO


def fechas(texto: str) -> list[date]:
    """Fechas del texto (día/mes/año, con años de 2 o 4 dígitos), en el orden en que aparecen."""
    resultado = []
    for dia, mes, anio in _RE_FECHA.findall(corregir_numeros(texto)):
        try:
            resultado.append(date(int(anio) + (2000 if len(anio) == 2 else 0), int(mes), int(dia)))
        except ValueError:
            continue
    return resultado


def buscar_fecha(esperada: date | None, texto: str) -> Busqueda:
    """Si la receta tiene una sola fecha y es otra, es una posible diferencia. Con varias fechas
    (nacimiento, vencimiento de la credencial...) no se puede saber cuál es: queda para revisar."""
    if esperada is None:
        return NO_ENCONTRADO
    leidas = fechas(texto)
    if esperada in leidas:
        return CONFIRMADO
    if len(set(leidas)) == 1:
        return Busqueda(Estado.PARECIDO, leido=leidas[0].strftime("%d/%m/%Y"))
    return NO_ENCONTRADO


def lineas_normalizadas(texto: str) -> list[list[str]]:
    return [normalizar_texto(linea).split() for linea in corregir_numeros(texto).splitlines()]


def _parecido_en(palabra: str, palabras: list[str], iniciales: bool = False) -> float:
    mejor = 0.0
    for otra in palabras:
        if len(otra) == 1:
            if iniciales and palabra.startswith(otra):
                mejor = max(mejor, 0.9)  # inicial de un nombre: "E." por "ELENA"
            continue
        if len(palabra) >= 5 and len(otra) >= 5 and (otra.startswith(palabra) or palabra.startswith(otra)):
            mejor = max(mejor, 0.9)  # abreviatura: "AMOXI" / "AMOXICILINA"
        mejor = max(mejor, similitud(palabra, otra))
    return mejor


def buscar_nombre(esperado: str | None, texto: str, umbral: float = 0.85) -> Busqueda:
    """Nombre de una persona: tolera orden, iniciales, segundos nombres omitidos y algún error de lectura."""
    buscadas = [t for t in normalizar_texto(esperado).split() if t not in PALABRAS_VACIAS_NOMBRE and len(t) > 1]
    if not buscadas:
        return NO_ENCONTRADO
    lineas = [linea for linea in lineas_normalizadas(texto) if linea]
    mejor_cobertura, mejor_linea = 0.0, None
    for i, linea in enumerate(lineas):
        ventana = linea + (lineas[i + 1] if i + 1 < len(lineas) else [])
        puntajes = [_parecido_en(palabra, ventana, iniciales=True) for palabra in buscadas]
        encontradas = sum(p >= umbral for p in puntajes)
        if encontradas == len(buscadas) or encontradas >= 2:
            return CONFIRMADO
        cobertura = sum(puntajes) / len(puntajes)
        if cobertura > mejor_cobertura:
            mejor_cobertura, mejor_linea = cobertura, " ".join(linea)
    if mejor_cobertura >= 0.6:
        return Busqueda(Estado.PARECIDO, leido=mejor_linea)
    return NO_ENCONTRADO


def buscar_producto(descripcion: str, monodroga: str | None, texto: str, umbral: float = 0.85) -> Busqueda:
    """Busca la droga (monodroga si el reporte la trae; si no, el nombre del producto) en el texto."""
    buscadas = palabras_producto(monodroga) or palabras_producto(descripcion)
    if not buscadas:
        return NO_ENCONTRADO
    parcial = None
    for i, linea in enumerate(lineas_normalizadas(texto)):
        puntajes = [_parecido_en(palabra, linea) for palabra in buscadas]
        if all(p >= umbral for p in puntajes):
            return Busqueda(Estado.CONFIRMADO, linea=i)
        if parcial is None and any(p >= umbral for p in puntajes):
            parcial = Busqueda(Estado.PARECIDO, leido=" ".join(linea), linea=i)
    return parcial or NO_ENCONTRADO


def renglon(texto: str, indice: int, siguientes: int = 1) -> str:
    """El renglón `indice` del texto (con números corregidos) y los `siguientes`."""
    lineas = corregir_numeros(texto).splitlines()
    return "\n".join(lineas[indice : indice + 1 + siguientes])


def concentraciones_en(texto: str) -> set[tuple[Decimal, str]]:
    return concentraciones(corregir_numeros(texto))


def cantidad_en(texto: str) -> int | None:
    """Cantidad de envases escrita en la receta: "Cantidad: 2", "2 envases", "(dos)"."""
    plano = normalizar_texto(corregir_numeros(texto))
    for patron in (r"\bCANT(?:IDAD)?\s+(\d{1,2})\b", r"\b(\d{1,2})\s+(?:ENVASES?|ENV|CAJAS?)\b"):
        coincidencia = re.search(patron, plano)
        if coincidencia:
            return int(coincidencia.group(1))
    palabras = "|".join(_NUMEROS_EN_LETRAS)
    coincidencia = re.search(
        rf"\(\s*({palabras})\s*\)|\b({palabras})\s+(?:ENVASES?|ENV|CAJAS?)\b", corregir_numeros(texto)
    )
    if coincidencia:
        return _NUMEROS_EN_LETRAS[coincidencia.group(1) or coincidencia.group(2)]
    return None


def contiene_frase(frase: str | None, texto: str) -> bool:
    """La frase aparece completa (palabras enteras), sin importar mayúsculas, acentos ni signos."""
    buscada = " ".join(normalizar_texto(frase).split())
    if not buscada:
        return False
    plano = " " + " ".join(normalizar_texto(corregir_numeros(texto)).split()) + " "
    return f" {buscada} " in plano
