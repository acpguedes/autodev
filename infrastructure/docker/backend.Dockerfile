FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/workspace/.venv \
    PATH="/workspace/.venv/bin:$PATH"

WORKDIR /workspace

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv /workspace/.venv \
    && /workspace/.venv/bin/pip install --no-cache-dir --upgrade pip \
    && /workspace/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /workspace/backend
COPY tests /workspace/tests
COPY mypy.ini /workspace/mypy.ini
COPY Makefile /workspace/Makefile

# Run as an unprivileged user rather than root.
RUN useradd --system --no-create-home --uid 10001 autodev \
    && mkdir -p /data /workspace/tests/reports \
    && chown -R autodev:autodev /workspace /data
USER autodev

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
