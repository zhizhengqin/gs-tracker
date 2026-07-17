FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

WORKDIR /app

# Install build dependencies for pandas/matplotlib
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY templates/ ./templates/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
CMD ["gunicorn", "src.web:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
