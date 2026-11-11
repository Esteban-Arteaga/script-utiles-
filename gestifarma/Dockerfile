FROM python:3.12-slim

# Versión con la que se construye la imagen (la pasa el kit de instalación); se ve en /salud.
ARG VERSION=local

ENV GESTIFARMA_VERSION_IMAGEN=$VERSION \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GESTIFARMA_DATA_DIR=/datos \
    GESTIFARMA_CONFIG_DIR=/app/config

# OCR para la lectura sin IA (Tesseract con datos de español)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[postgres]"

COPY config ./config
COPY ejemplos ./ejemplos

RUN useradd --create-home --uid 1000 gestifarma \
    && mkdir -p /datos \
    && chown gestifarma /datos
USER gestifarma
VOLUME ["/datos"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud')" || exit 1

CMD ["gestifarma", "servidor", "--host", "0.0.0.0", "--port", "8000"]
