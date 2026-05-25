FROM python:3.12-slim

ARG UID=1000
ARG GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATABASE_PATH=/app/data/scoreboard.db \
    KIOSK_LAYOUT_FILE=/app/config/kiosk-slides.json \
    KIOSK_TEMPLATE_FILE=/app/config/kiosk-templates.json \
    VISUAL_SCENE_TEMPLATE_FILE=/app/config/visual-scene-templates.json

WORKDIR /app

RUN groupadd --gid "${GID}" scoreboard \
    && useradd --uid "${UID}" --gid scoreboard --create-home scoreboard

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=scoreboard:scoreboard . .

RUN mkdir -p /app/config /app/data \
    && cp /app/static/kiosk-slides.json /app/config/kiosk-slides.json \
    && cp /app/static/kiosk-templates.json /app/config/kiosk-templates.json \
    && cp /app/static/visual-scene-templates.json /app/config/visual-scene-templates.json \
    && chown -R scoreboard:scoreboard /app

USER scoreboard

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/health', timeout=4).read()"

CMD ["python", "wsgi.py"]
