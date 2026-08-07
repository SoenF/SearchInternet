FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md .env.example Dockerfile ./
COPY src/ ./src/
COPY tests/ ./tests/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir -e .

# Built once at image build time, not on every request -- what's served at
# /download always matches exactly what's deployed, since it's the same
# image. See scripts/build_release_zip.py for what's included/excluded.
RUN python scripts/build_release_zip.py

VOLUME ["/app/data"]
ENV DEDUP_DB_PATH=/app/data/leadbridge_dedup.sqlite3
ENV TENANTS_DB_PATH=/app/data/leadbridge_tenants.sqlite3
ENV DOWNLOAD_ZIP_PATH=/app/dist/leadbridge-src.zip

EXPOSE 8000
CMD ["uvicorn", "leadbridge.main:app", "--host", "0.0.0.0", "--port", "8000"]
