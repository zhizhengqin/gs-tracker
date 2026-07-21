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
# Default to a China-friendly PyPI mirror (JD Cloud builds pull much faster);
# override with --build-arg PIP_INDEX_URL=https://pypi.org/simple if needed.
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY src/ ./src/
COPY templates/ ./templates/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
CMD ["gunicorn", "src.web:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
