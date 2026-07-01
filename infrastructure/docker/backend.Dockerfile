FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend

# Run as an unprivileged user rather than root.
RUN useradd --system --no-create-home --uid 10001 autodev \
    && chown -R autodev:autodev /app
USER autodev

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
