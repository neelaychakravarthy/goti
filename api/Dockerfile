FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg + general builds.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install -r /app/api/requirements.txt

COPY api /app/api

EXPOSE 8000

# docker-compose overrides the command to also run the AgentField reasoner
# sidecar; the default command serves uvicorn so this image is usable on
# its own (e.g. for Zeabur deploy of just the FastAPI layer).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
