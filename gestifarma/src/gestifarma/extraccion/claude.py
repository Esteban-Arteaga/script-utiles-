"""Lectura de recetas con Claude (visión + salida estructurada)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
from pydantic import ValidationError

from .esquema import ESQUEMA_EXTRACCION, ExtraccionReceta
from .imagenes import bloque_para_claude
from .prompt import INSTRUCCION, PROMPT_SISTEMA

log = logging.getLogger(__name__)

# Modelos que aceptan el reintento automático en otro modelo si un filtro de seguridad rechaza el
# pedido (parámetro `fallbacks`). Para el resto no se manda.
_MODELOS_CON_REINTENTO = {
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-fable-5",
}


class ErrorExtraccion(Exception):
    pass


@dataclass
class ResultadoExtraccion:
    datos: ExtraccionReceta
    modelo: str
    uso: dict = field(default_factory=dict)  # tokens o segundos consumidos: sirve para medir el costo real
    lector: str = "claude"  # "claude" (IA) o "local" (sin IA)
    extra: dict = field(default_factory=dict)  # lectura local: texto y códigos de cada página

    def como_json(self) -> dict:
        return {
            "lector": self.lector,
            "datos": self.datos.model_dump(mode="json"),
            "modelo": self.modelo,
            "uso": self.uso,
            **self.extra,
        }


class Extractor(Protocol):
    def extraer(self, archivos: list[tuple[bytes, str]]) -> ResultadoExtraccion: ...


class ExtractorClaude:
    def __init__(self, modelo: str, esfuerzo: str = "medium", cliente: anthropic.Anthropic | None = None):
        self.modelo = modelo
        self.esfuerzo = esfuerzo
        self.cliente = cliente or anthropic.Anthropic()

    def extraer(self, archivos: list[tuple[bytes, str]]) -> ResultadoExtraccion:
        """`archivos`: lista de (contenido, nombre). Todas las imágenes son de la MISMA receta."""
        if not archivos:
            raise ErrorExtraccion("La receta no tiene archivos.")
        contenido: list[dict] = []
        for numero, (datos, nombre) in enumerate(archivos, start=1):
            contenido.append({"type": "text", "text": f"Archivo {numero} de {len(archivos)}: {nombre}"})
            contenido.append(bloque_para_claude(datos, nombre))
        contenido.append({"type": "text", "text": INSTRUCCION})

        pedido: dict = {
            "model": self.modelo,
            "max_tokens": 16000,
            "system": [{"type": "text", "text": PROMPT_SISTEMA, "cache_control": {"type": "ephemeral"}}],
            "output_config": {
                "effort": self.esfuerzo,
                "format": {"type": "json_schema", "schema": ESQUEMA_EXTRACCION},
            },
            "messages": [{"role": "user", "content": contenido}],
        }
        if self.modelo in _MODELOS_CON_REINTENTO:
            pedido["betas"] = ["server-side-fallback-2026-07-01"]
            pedido["fallbacks"] = "default"

        respuesta = self.cliente.beta.messages.create(**pedido)

        if respuesta.stop_reason == "refusal":
            raise ErrorExtraccion("El modelo no procesó estas imágenes. Cargar los datos a mano.")
        if respuesta.stop_reason == "max_tokens":
            raise ErrorExtraccion("La respuesta del modelo quedó incompleta. Reintentar la lectura.")
        texto = next((bloque.text for bloque in respuesta.content if bloque.type == "text"), None)
        if not texto:
            raise ErrorExtraccion("La respuesta del modelo no trajo datos.")
        try:
            datos = ExtraccionReceta.model_validate_json(texto)
        except ValidationError as exc:
            raise ErrorExtraccion(f"La respuesta no respeta el formato esperado: {exc}") from exc

        uso = respuesta.usage.to_dict() if respuesta.usage is not None else {}
        log.info("Receta leída con %s (request %s): %s", respuesta.model, getattr(respuesta, "_request_id", "-"), uso)
        return ResultadoExtraccion(datos=datos, modelo=respuesta.model, uso=uso)
