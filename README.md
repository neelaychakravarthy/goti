# Goti

Your personal agentic negotiator. Goti runs parallel, human-in-the-loop negotiations across online marketplaces, using cross-negotiation BATNA leverage to close better deals than you can alone.

See [SPEC.md](./SPEC.md) for the project context, sponsors, tech stack, and MVP scope.
See [CLAUDE.md](./CLAUDE.md) for the project-root rules and build/run/test/deploy commands.

## Run locally

Backend (`api/`) — Stream C scaffold landed; FastAPI app + agents are Stream B's first increment.

```bash
# 1. Bring up Postgres
docker compose up -d postgres

# 2. Install Python deps
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Apply DB migrations
alembic upgrade head

# 4. Run the mock-path test suite (no sponsor creds needed)
GOTI_USE_MOCKS=1 pytest
```

Live Bright Data smoke (one HTTP call, burns credits — opt-in only):

```bash
# Discover the FB Marketplace dataset id and paste it into .env (or your shell):
BRIGHT_DATA_API_KEY=... python -m api.integrations.bright_data.discover_datasets

export BRIGHT_DATA_API_KEY=...
export BRIGHT_DATA_FB_DATASET_ID=...
pytest -m live -k test_discovery_live
```

Frontend (`web/`) and the FastAPI HTTP app (`api/main.py`) arrive in Stream A and Stream B's first increments respectively.
