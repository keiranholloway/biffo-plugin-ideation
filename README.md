# biffo-plugin-ideation

The **Ideation Engine** — the first user-facing, agentic product module for the
Biffo platform. An approved founder describes an idea; the module runs a short,
sharp conversation that pressure-tests it, then produces a **high-level PRD** and
a **viability scorecard** (competitive landscape, build-vs-buy, complexity,
economic moat, market fit).

It is an [ADR-0003](https://github.com/keiranholloway/biffo-template/blob/main/docs/ADR/0003-plugin-system-and-marketplace.md)
plugin built on the [ADR-0016](https://github.com/keiranholloway/biffo-template/blob/main/docs/ADR/0016-the-prompt-assistant.md)
**synchronous chat spine** (the *buffered* amendment): the chat is a *thread of
agent runs* where **Core is the ingress** — it authenticates the founder, fences
their message as untrusted data, assembles the turn, synchronously invokes the
runtime, and returns the whole reply (no streaming; the Lambda/Python runtime
buffers). The analysis is a single async agent run. **Data always lives in Core**
(ADR-0002) — this module declares tables; Core owns and serves them.

## Data model (`biffo.plugin.json`)

Two Core-owned tables (declared here, deployed by Core; `id`/`tenant_id`/
`created_at`/`updated_at` are auto-injected):

- **`ideation_sessions`** — one per idea: `owner_sub`, `title`, `seed_idea`,
  `status` (`gathering → analysing → complete`), `thread_id` (the run thread
  carrying the chat transcript — ADR-0016 §2), `turn_count` (the 3–5 cap),
  `analysis_run_id`.
- **`ideation_reports`** — `session_id`, `prd` (JSON), `scorecard` (JSON), `model`.

All CRUD permissions are **closed**: access is owner-scoped through the module's
orchestration on Core's chat spine, never the tenant-scoped generic-CRUD layer.

## Agent definitions (`src/ideation/definitions.py`)

- **Challenger** — synchronous, one focused question per turn, 3–5 turns, no
  solutions; winds down once there's enough for a PRD.
- **Analyst** — async: web-searches the competitive landscape, weighs build-vs-buy,
  scores viability/complexity/moat/market-fit (1–5 + rationale), drafts the PRD,
  and returns it via the `submit_ideation_report` tool (structured output as a
  tool call — the runtime does tools, not `response_format`).

## Build phasing

- ✅ **Data model + agent definitions** (pydantic-only, tested).
- ✅ **Orchestration logic** (`src/ideation/{models,ports,service}.py`) — session
  lifecycle, the buffered `chat_turn`, `finalise` (the async analysis run),
  `complete_analysis` → stored report, owner-scoped `get_report`. Transport-agnostic
  behind one `CoreGateway` port; fenced/assembled by Core's trusted spine, never
  here. Fully unit-tested against an in-memory fake Core.
- ⬜ **Core capability + adapter** — Core generalises #497's prompt-assistant spine
  into a reusable, founder-gated buffered chat capability a plugin can drive (its
  own system prompt + `agent_name` + group gate), plus the async analyst run
  accepting a plugin-provided structured-output tool schema. Then a thin adapter
  binds `CoreGateway` to it. **Gated on that capability landing in biffo-template.**
- ⬜ **`/ideation` frontend** — the founder-gated chat + live scorecard/PRD.

## Development

```bash
uv sync
uv run pytest
uv run ruff check
```
