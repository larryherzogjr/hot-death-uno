# Hot Death Uno — web app image (engine + FastAPI server + static SPA).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install runtime deps first for layer caching.
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir --constraint constraints.txt -r requirements.txt

# App code: the pure engine and the server consumer (incl. static SPA).
COPY hdu/ ./hdu/
COPY server/ ./server/

# Run unprivileged.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Liveness probe — hits the cheap /healthz endpoint (no session work).
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# Single worker on purpose: game sessions are in-memory (v1). Scaling out later
# means a shared session store, not more workers.
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
