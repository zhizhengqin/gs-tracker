FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

WORKDIR /app

# Install build dependencies for pandas/matplotlib.
# Default to a China-friendly apt mirror: the deploy server (JD Cloud) pulls
# from deb.debian.org at KB/s, which blew past the 10-minute SSH deploy
# timeout. Override with --build-arg APT_MIRROR=deb.debian.org if needed.
ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Default to a China-friendly PyPI mirror (JD Cloud builds pull much faster);
# override with --build-arg PIP_INDEX_URL=https://pypi.org/simple if needed.
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
# Single worker: pipeline job state and SSE progress live in process memory.
CMD ["gunicorn", "src.web:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--timeout", "600"]
