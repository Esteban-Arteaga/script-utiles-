import base64
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from gestifarma.extraccion import ESQUEMA_EXTRACCION, ErrorExtraccion, ExtraccionReceta, ExtractorClaude
from gestifarma.extraccion.imagenes import ArchivoNoSoportado, bloque_para_claude

RESPUESTA = {
    "es_receta": True,
    "tipo_receta": "manuscrita",
    "obra_social": "PAMI",
    "plan": None,
    "nro_afiliado": "123456789012/00",
    "afiliado_nombre": "Gomez Maria Elena",
    "afiliado_dni": None,
    "medico_nombre": "Juan Perez",
    "medico_matricula": "MP 12345",
    "fecha_prescripcion": "2026-11-02",
    "fecha_dispensa": None,
    "nro_receta": None,
    "nro_autorizacion": "98123",
    "diagnostico": None,
    "firma_medico": True,
    "sello_medico": True,
    "firma_afiliado": None,
    "importe_total": None,
    "importe_obra_social": None,
    "items": [{"descripcion": "Enalapril 10 mg", "cantidad": 1, "troquel": None, "codigo_barras": None}],
    "campos_dudosos": ["medico_matricula"],
    "observaciones": None,
}


class ClienteFalso:
    """Imita client.beta.messages.create y guarda el pedido para inspeccionarlo."""

    def __init__(self, texto=json.dumps(RESPUESTA), stop_reason="end_turn"):
        self.pedidos = []
        uso = SimpleNamespace(to_dict=lambda: {"input_tokens": 3000, "output_tokens": 900})
        self.respuesta = SimpleNamespace(
            stop_reason=stop_reason,
            model="claude-opus-5-5",
            usage=uso,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **pedido):
        self.pedidos.append(pedido)
        return self.respuesta


def foto(ancho=4000, alto=3000, orientacion=None) -> bytes:
    salida = BytesIO()
    imagen = Image.new("RGB", (ancho, alto), "white")
    if orientacion:
        exif = Image.Exif()
        exif[0x0112] = orientacion
        imagen.save(salida, format="JPEG", exif=exif)
    else:
        imagen.save(salida, format="JPEG")
    return salida.getvalue()


def test_arma_el_pedido_y_devuelve_los_datos_validados():
    cliente = ClienteFalso()
    resultado = ExtractorClaude("claude-opus-5-5", "medium", cliente).extraer(
        [(foto(), "frente.jpg"), (foto(), "dorso.jpg")]
    )

    assert resultado.datos.nro_afiliado == "123456789012/00"
    assert str(resultado.datos.fecha_prescripcion) == "2026-11-02"
    assert resultado.uso["output_tokens"] == 900

    (pedido,) = cliente.pedidos
    assert pedido["model"] == "claude-opus-5-5"
    assert pedido["output_config"]["format"] == {"type": "json_schema", "schema": ESQUEMA_EXTRACCION}
    assert pedido["output_config"]["effort"] == "medium"
    assert pedido["fallbacks"] == "default" and pedido["betas"] == ["server-side-fallback-2026-07-01"]
    tipos = [bloque["type"] for bloque in pedido["messages"][0]["content"]]
    assert tipos == ["text", "image", "text", "image", "text"]


def test_las_fotos_se_achican_al_maximo_util_y_se_enderezan():
    bloque = bloque_para_claude(foto(4000, 3000, orientacion=6), "foto.jpg")  # 6 = rotada 90°
    imagen = Image.open(BytesIO(base64.b64decode(bloque["source"]["data"])))
    assert imagen.size == (1932, 2576)  # quedó vertical y con el lado mayor en 2576 px


def test_pdf_va_como_documento():
    bloque = bloque_para_claude(b"%PDF-1.7 contenido", "receta.pdf")
    assert bloque["type"] == "document"
    assert bloque["source"]["media_type"] == "application/pdf"


def test_archivo_que_no_es_imagen_ni_pdf():
    with pytest.raises(ArchivoNoSoportado):
        bloque_para_claude(b"hola", "nota.txt")


def test_modelos_sin_reintento_no_mandan_fallbacks():
    cliente = ClienteFalso()
    ExtractorClaude("claude-haiku-5-5", "low", cliente).extraer([(foto(), "frente.jpg")])
    assert "fallbacks" not in cliente.pedidos[0] and "betas" not in cliente.pedidos[0]


@pytest.mark.parametrize(("stop_reason", "texto"), [("refusal", ""), ("max_tokens", "{"), ("end_turn", "{}x")])
def test_respuestas_que_no_sirven_dan_error_claro(stop_reason, texto):
    with pytest.raises(ErrorExtraccion):
        ExtractorClaude("claude-opus-5-5", "medium", ClienteFalso(texto, stop_reason)).extraer([(foto(), "f.jpg")])


def test_esquema_y_modelo_tienen_los_mismos_campos():
    assert set(ESQUEMA_EXTRACCION["properties"]) == set(ExtraccionReceta.model_fields)
    assert set(ESQUEMA_EXTRACCION["required"]) == set(ExtraccionReceta.model_fields)
