# ---- Stage 1: builder ----
# Installs every Python dep into a venv. Keeps the heavy build-essential
# toolchain (~400MB of C compilers, headers, libstdc++ debug symbols) out
# of the runtime layer — those are only needed during pip install for
# packages with C extensions (greenlet, pillow, etc.).
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build into a self-contained venv so we can copy just the venv into
# the runtime stage. Keeps the runtime image lean.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install -r /app/api/requirements.txt

# ---- Stage 2: runtime ----
# python:3.11-slim base only — no build-essential. Just copies the
# pre-built venv and the application code.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY api /app/api

EXPOSE 8000

# Both processes run inside the same container:
#   - AgentField agent server (self-hosted, :8080 internal — not exposed)
#   - uvicorn FastAPI (:8000 — the port Zeabur health-checks + routes)
# FastAPI reaches the agent server via http://localhost:8080. `wait -n`
# exits if either process dies so the orchestrator restarts the container.
# Both processes' logs interleave to stdout.
CMD ["bash", "-c", "python -m api.agents.clarifier & uvicorn api.main:app --host 0.0.0.0 --port 8000 & wait -n"]
