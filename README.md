# biffo-plugin-ideation

The **Ideation Engine** — the first user-facing, agentic product module for the
Biffo platform. An approved founder describes an idea; the module runs a short,
sharp conversation that pressure-tests it, then produces a **high-level PRD** and
a **viability scorecard** (competitive landscape, build-vs-buy, complexity,
economic moat, market fit).

It is an [ADR-0003](https://github.com/keiranholloway/biffo-template/blob/main/docs/ADR/0003-plugin-system-and-marketplace.md)
plugin built on the [ADR-0016](https://github.com/keiranholloway/biffo-template/blob/main/docs/ADR/0016-the-prompt-assistant.md)
**synchronous run/thread spine**: the chat is a streamed *thread of agent runs*
through the runtime's Cognito-authed Function URL; the analysis is a single async
agent run. **Data always lives in Core** (ADR-0002) — this module declares tables;
Core owns and serves them.

## Data model (`biffo.plugin.json`)

Two Core-owned tables (declared here, deployed by Core; `id`/`tenant_id`/
`created_at`/`updated_at` are auto-injected):

- **`ideation_sessions`** — one per idea: `owner_sub`, `title`, `seed_idea`,
  `status` (`gathering → analysing → complete`), `thread_id` (the run thread
  carrying the chat transcript — ADR-0016 §2), `turn_count` (the 3–5 cap),
  `analysis_run_id`.
- **`ideation_reports`** — `session_id`, `prd` (JSON), `scorecard` (JSON), `model`.

All CRUD permissions are **closed**: access is owner-scoped through the module's
Lambda on the Function-URL spine, never the tenant-scoped generic-CRUD layer.

## Agent definitions (`src/ideation/definitions.py`)

- **Challenger** — synchronous, one focused question per turn, 3–5 turns, no
  solutions; winds down once there's enough for a PRD.
- **Analyst** — async: web-searches the competitive landscape, weighs build-vs-buy,
  scores viability/complexity/moat/market-fit (1–5 + rationale), drafts the PRD,
  and returns it via the `submit_ideation_report` tool (structured output as a
  tool call — the runtime does tools, not `response_format`).

## Build phasing

- ✅ **Data model + agent definitions** (this repo, pydantic-only, tested).
- ⬜ **Lambda orchestration** — session lifecycle + per-turn streamed chat +
  `finalise` (the async analysis run) + `report`, on the ADR-0016 Function-URL
  spine. Adds `biffo-plugin-sdk` / `aws-lambda-powertools` / `httpx`. **Gated on
  the spine's Function-URL + `run_as: user` pieces landing in biffo-template.**
- ⬜ **`/ideation` frontend** — the founder-gated chat + live scorecard/PRD.

## Development

```bash
uv sync
uv run pytest
uv run ruff check
```
