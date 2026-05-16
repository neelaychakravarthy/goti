# Goti

Your personal agentic negotiator. Goti runs parallel, human-in-the-loop negotiations across online marketplaces, using cross-negotiation BATNA leverage to close better deals than you can alone.

See [SPEC.md](./SPEC.md) for the project context, sponsors, tech stack, and MVP scope.
See [CLAUDE.md](./CLAUDE.md) for the project-root rules and build/run/test/deploy commands.

## Run locally

Prereqs: Docker + Docker Compose v2.

```bash
cp .env.example .env
# Fill in at minimum TOKENROUTER_API_KEY and EVEROS_API_KEY for the
# wired POST /api/goals path; everything else can stay blank for now.

docker compose up --build
```

This boots three services:

- **`postgres`** on `:5432` — Stream B's tables (`jobs`, `message_threads`, `approval_queue`) are auto-migrated on api startup.
- **`af-server`** on `:8080` — AgentField control plane.
- **`api`** on `:8000` — FastAPI app + the `goti` AgentField sidecar hosting four reasoners (clarifier, valuation, negotiator, coordinator) on a single shared Agent.

Quick sanity checks (in another terminal):

```bash
# Swagger UI for the full A↔B REST contract:
open http://localhost:8000/docs

# Stub endpoint returns fixture JSON:
curl http://localhost:8000/api/jobs

# The one wired end-to-end path — needs real TOKENROUTER_API_KEY in .env.
# Hits AgentField -> TokenRouter -> GLM-5.1 -> EverOS Case stub-write.
curl -X POST http://localhost:8000/api/goals \
  -H 'Content-Type: application/json' \
  -d '{"text":"standing desk under $250 in SF"}'
```

To tear down: `docker compose down` (add `-v` to also drop the postgres volume).

### Frontend dev (Stream A)

`web/` lives in its own README — see `web/README.md` once Stream A lands.
