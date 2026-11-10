"""Normalización de datos para poder comparar lo que dice la receta con lo cargado en el sistema.

La receta y el sistema escriben lo mismo de formas distintas ("00123/01" vs "123/01",
"GOMEZ, María" vs "MARIA GOMEZ", "03/11/26" vs "2026-11-03"): acá se lleva todo a una forma común.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%Y/%m/%d")

PALABRAS_VACIAS_NOMBRE = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "E"}

# Palabras de presentación/forma farmacéutica que no ayudan a identificar la droga.
PALABRAS_VACIAS_PRODUCTO = {
    "X",
    "MG",
    "MCG",
    "UG",
    "G",
    "GR",
    "ML",
    "UI",
    "U",
    "DE",
    "EN",
    "CON",
    "POR",
    "PARA",
    "COMP",
    "COMPR",
    "COMPRIMIDO",
    "COMPRIMIDOS",
    "REC",
    "RECUBIERTOS",
    "TAB",
    "TABLETA",
    "TABLETAS",
    "CAP",
    "CAPS",
    "CAPSULA",
    "CAPSULAS",
    "JBE",
    "JARABE",
    "SUSP",
    "SUSPENSION",
    "GOTAS",
    "GTS",
    "AMP",
    "AMPOLLA",
    "AMPOLLAS",
    "INY",
    "INYECTABLE",
    "SOL",
    "SOLUCION",
    "CREMA",
    "GEL",
    "UNGUENTO",
    "SPRAY",
    "AEROSOL",
    "POLVO",
    "SOBRE",
    "SOBRES",
    "FCO",
    "FRASCO",
    "ENV",
    "ENVASE",
    "ENVASES",
    "CAJA",
    "UNIDADES",
    "UNID",
    "ORAL",
    "LIB",
    "PROLONGADA",
    "DISP",
    "DISPERSABLES",
    "MASTICABLES",
    "EFERV",
    "EFERVESCENTES",
    "BLISTER",
}

_UNIDADES = {"MG": "MG", "MCG": "MCG", "UG": "MCG", "G": "G", "GR": "G", "ML": "ML", "UI": "UI", "%": "%"}
_RE_CONCENTRACION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(MCG|UG|MG|GR|G|ML|UI|%)(?![A-Z])")


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_texto(texto: object) -> str:
    """Mayúsculas, sin acentos ni signos, con espacios simples."""
    if texto is None:
        return ""
    limpio = sin_acentos(str(texto)).upper()
    return re.sub(r"[^A-Z0-9]+", " ", limpio).strip()


def texto_o_none(valor: object) -> str | None:
    """Convierte un valor de planilla a texto. Evita que Excel convierta 123456 en '123456.0'."""
    if valor is None:
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, datetime):
        valor = valor.date()
    texto = str(valor).strip()
    return texto or None


def normalizar_id(valor: object) -> str:
    """Identificadores (afiliado, receta, autorización, troquel): solo letras y dígitos, sin ceros adelante."""
    texto = texto_o_none(valor)
    if texto is None:
        return ""
    limpio = re.sub(r"[^A-Z0-9]", "", sin_acentos(texto).upper())
    return limpio.lstrip("0") or ("0" if limpio else "")


def normalizar_matricula(valor: object) -> str:
    """Matrícula del médico: solo el número (se ignora el prefijo MN / MP / M.P.)."""
    digitos = re.sub(r"\D", "", texto_o_none(valor) or "")
    return digitos.lstrip("0")


def parsear_fecha(valor: object, formato: str | None = None) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.split()[0]  # descarta la hora si viene "03/11/2026 14:35"
    formatos = ((formato,) if formato else ()) + FORMATOS_FECHA
    for f in formatos:
        try:
            return datetime.strptime(texto, f).date()
        except ValueError:
            continue
    raise ValueError(f"fecha no reconocida: {texto!r}")


def parsear_importe(valor: object, separador_decimal: str = ",") -> Decimal | None:
    """Importes en formato argentino ("$ 1.234,56") o numérico.

    Con separador_decimal="auto" (lo que tipea una persona) se deduce: "1.234,56", "1234,56",
    "1234.56" y "1.234" se interpretan como se leen en Argentina.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ValueError(f"importe no reconocido: {valor!r}")
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    texto = str(valor).replace("$", "").replace(" ", "").strip()
    if not texto:
        return None
    if separador_decimal == "auto":
        if "," in texto:
            separador_decimal = ","
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
            separador_decimal = ","  # "1.234" o "12.345.678": puntos de miles
        else:
            separador_decimal = "."
    if separador_decimal == ",":
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", "")
    try:
        return Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"importe no reconocido: {valor!r}") from exc


def parsear_entero(valor: object) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ValueError(f"cantidad no reconocida: {valor!r}")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    coincidencia = re.fullmatch(r"(\d+)(?:[.,]0+)?", str(valor).strip())
    if not coincidencia:
        raise ValueError(f"cantidad no reconocida: {valor!r}")
    return int(coincidencia.group(1))


def similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _parecido_palabra(palabra: str, otras: list[str]) -> float:
    if len(palabra) == 1:  # inicial: "J" coincide con "JUAN"
        return 1.0 if any(o.startswith(palabra) for o in otras) else 0.0
    mejor = 0.0
    for otra in otras:
        if len(palabra) >= 4 and len(otra) >= 4 and (otra.startswith(palabra) or palabra.startswith(otra)):
            mejor = max(mejor, 0.9)  # abreviatura: "AMOXI" / "AMOXICILINA"
        mejor = max(mejor, similitud(palabra, otra))
    return mejor


def _cobertura(origen: list[str], destino: list[str]) -> float:
    """Qué tan bien aparecen las palabras de `origen` dentro de `destino` (0 a 1)."""
    if not origen or not destino:
        return 0.0
    return sum(_parecido_palabra(p, destino) for p in origen) / len(origen)


def similitud_nombres(a: str | None, b: str | None) -> float:
    """0 a 1. Tolera orden distinto, segundos nombres de más, iniciales y errores de tipeo."""
    tokens_a = [t for t in normalizar_texto(a).split() if t not in PALABRAS_VACIAS_NOMBRE]
    tokens_b = [t for t in normalizar_texto(b).split() if t not in PALABRAS_VACIAS_NOMBRE]
    corto, largo = sorted((tokens_a, tokens_b), key=len)
    return _cobertura(corto, largo)


def palabras_producto(descripcion: str | None) -> list[str]:
    return [t for t in normalizar_texto(descripcion).split() if t not in PALABRAS_VACIAS_PRODUCTO and not t.isdigit()]


def similitud_productos(receta: str | None, sistema: str | None, monodroga: str | None = None) -> float:
    """Compara solo el nombre de la droga (sin concentración ni presentación), en ambos sentidos:
    "Amoxicilina" contra "Amoxicilina + Ácido clavulánico" da un puntaje intermedio, no un 1."""
    tokens_receta = palabras_producto(receta)
    mejor = 0.0
    for candidato in (palabras_producto(sistema), palabras_producto(monodroga)):
        puntaje = (_cobertura(tokens_receta, candidato) + _cobertura(candidato, tokens_receta)) / 2
        mejor = max(mejor, puntaje)
    return mejor


def concentraciones(descripcion: str | None) -> set[tuple[Decimal, str]]:
    """Concentraciones mencionadas en una descripción: "Enalapril 10 mg" -> {(10, "MG")}."""
    # "µg": el signo micro y la mu griega se escriben igual pero son caracteres distintos
    texto = sin_acentos((descripcion or "").replace("\u00b5", "u").replace("\u03bc", "u")).upper()
    return {
        (Decimal(numero.replace(",", ".")), _UNIDADES[unidad]) for numero, unidad in _RE_CONCENTRACION.findall(texto)
    }


def formatear_fecha(valor: date | None) -> str | None:
    return valor.strftime("%d/%m/%Y") if valor else None
