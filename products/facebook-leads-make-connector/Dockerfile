FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

VOLUME ["/app/data"]
ENV DEDUP_DB_PATH=/app/data/leadbridge_dedup.sqlite3

EXPOSE 8000
CMD ["uvicorn", "leadbridge.main:app", "--host", "0.0.0.0", "--port", "8000"]
