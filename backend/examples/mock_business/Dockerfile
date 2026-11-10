# Mock business API — standalone so it can run without the platform's venv.
# Build context is this directory: docker build -t nexusdesk/mock-business-api .
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

# Optional overrides for networks that cannot reach Docker Hub / PyPI directly,
# e.g. --build-arg PYTHON_IMAGE=<mirror>/library/python:3.12-slim-bookworm
#      --build-arg PIP_INDEX_URL=https://<mirror>/simple
ARG PIP_INDEX_URL=

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Pinned to the versions the platform's own venv resolves, so the OpenAPI
# document the importer reads does not drift between local and container runs.
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    "fastapi==0.142.2" "uvicorn[standard]==0.54.0"

COPY __init__.py app.py fixtures.py /app/mock_business/

RUN useradd --uid 10001 --create-home mock \
    && chown -R mock:mock /app
USER mock

EXPOSE 8010

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=2)"

CMD ["python", "-m", "uvicorn", "mock_business.app:app", "--host", "0.0.0.0", "--port", "8010"]
