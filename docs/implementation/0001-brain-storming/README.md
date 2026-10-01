# Feature: Brain-Storming tab for biffo-plugin-ideation

## Context

`biffo-plugin-ideation` currently ships one feature, "Ideation" / "Pressure Test": a chat
that pressure-tests an *already-stated* business idea, then runs one async "Analyst" agent
that does web research and produces a PRD + scorecard.

The owner wants a new "Brain-Storming" mode that runs *before* Pressure Test: give it a
target company and/or industry, a target geographic market, and a business problem/idea
statement; an interactive chat qualifies the specifics; then six parallel research agents
run (Pain & Intent, Market/Competition, Workflow/Jobs-to-be-done, Trend,
Economics/Commercial, Contrarian/White-space); one synthesis agent reconciles them into
ranked business opportunities; the user picks one to seed a new Pressure Test session.

The sibling plugin `biffo-plugin-idea-scout` already runs almost exactly this shape — 3
parallel research agents + 1 synthesis agent, fanned out/in via a proven platform
mechanism — for a different product surface. This plan reuses that *pattern*
deliberately, not its code (no cross-plugin code sharing exists in this estate; each
plugin's own copy of shared shapes like `Scorecard` is intentional).

## Success criteria

- A user can open a new "Brain-Storm" tab (alongside the existing "Pressure Test" tab,
  unchanged), state a target company/industry, geographic market, and a problem/idea, and
  have a qualifying chat pin down specifics — same interaction shape as today's Challenger
  chat.
- From a qualified brief, six research agents run in parallel and one synthesis agent
  reconciles them into ranked, observable business opportunities.
- The user can click an opportunity to seed a new Pressure Test session with it (reusing
  the `?seed=` mechanism Idea Scout already uses today).
- Every stage's status is visible to the user while it runs (qualifying → researching →
  synthesising → complete/failed), matching Idea Scout's existing polling UX.

## Scope / explicitly deferred

- **In scope**: everything above, built entirely inside `biffo-plugin-ideation` (backend
  + frontend), reusing the platform's existing generic fan-out/fan-in orchestrator
  primitive (already proven by Idea Scout) rather than building new job infrastructure.
- **Explicitly deferred**:
  - Any shared cross-plugin app-shell / tab framework. ADR-0021's frontend mount is
    unbuilt (`biffo-platform#558` Milestone 2) — this feature builds a real tab structure
    plugin-local, inside `biffo-plugin-ideation`'s own `web/src/App.tsx`, and does not
    wait on or attempt that shared infrastructure.
  - Any change to Idea Scout itself, or any new coupling between the two plugins beyond
    the URL-level `?seed=` deep-link that already exists.
  - Automatic session creation from a synthesized opportunity. The user always clicks to
    seed Pressure Test; nothing happens without that click.

## Current state (from research, verified against the real code)

- Ideation's chat ("Challenger") is synchronous, capped multi-turn (`MIN_TURNS`/
  `MAX_TURNS` in `definitions.py`), one `POST /sessions/{id}/messages` per turn, no
  streaming. This is the mechanism the new qualifying chat reuses, with a new
  blue-sky-framed system prompt.
- Ideation's `CoreGateway` (`src/ideation/ports.py`) has **no fan-out primitives today**
  — only `request_analysis` (one thread, one async run). Idea Scout's
  `request_agent_run(causation_id=...)`, `find_chain_run`, `get_agent_run` (with
  `.is_terminal`/`.succeeded`/`.never_started`) do not exist yet in this plugin and must
  be added from scratch to `ports.py`/`adapter.py`/`transport.py`, copying Idea Scout's
  shapes. These are shared files Pressure Test also uses — a real sequencing constraint.
- Idea Scout's fan-out→fan-in join is a **generic platform primitive**
  (`orchestrator/actions.py`'s `agent_fan_in`, driven by EventBridge `agent.run.completed`
  + Core's `causation_id`/`depth` chain tracking) — no new platform infrastructure is
  needed. Brain-Storming declares its own fan-in workflow on every plugin startup via
  `POST /internal/plugins/me/workflows/seed` (upsert, SigV4 service principal), so there is
  no operator script and no once-per-environment step.
- `app.py` and `admin_app.py` each have their own copy of the startup agent-config seeding
  hook (`_seed_agent_config`) — any milestone adding new agent roles touches both files.
- Idea Scout's model calls use OpenRouter's `:online` suffix (e.g.
  `"anthropic/claude-sonnet-4:online"`) for web-research-capable agents, with `tools: []`
  — *not* the `web_search` tool, which is silently dropped on dev (no Brave credential
  configured). The six research agents follow the same convention.
- `web/src/App.tsx` is a single flat SPA today — a `View` union (`'new' | 'live' |
  'report'`), no tabs, no router. Adding a Brain-Storm tab is real, non-trivial frontend
  scope, not a cheap addition — confirmed and accepted.
- Idea Scout's candidates already deep-link into Ideation via a `?seed=` query param
  (`readSeedParam()` in `App.tsx`, already live) — Brain-Storming's opportunities reuse
  this exact mechanism unchanged.

## Cross-repo boundary

None beyond the existing URL-level link to `biffo-plugin-idea-scout` (unchanged). All new
code lives inside `biffo-plugin-ideation`. No template/instance split applies — this is a
plugin, not a CRM-section/sibling placement question (confirmed: selectable/installable
plugin work stays in its own plugin repo).

## Milestones

M1 is a foundation with no reader (honest partial value: M2 reads it). M2→M3 and M2→M4 are
real sequential dependencies (shared files), not false parallelism. M3 and M4 are
read-disjoint and can run in parallel. M5 depends on both M3 and M4 landing first.

### M1: Brain-Storming schema and Core-gateway plumbing

Add `brainstorm_sessions` and `brainstorm_opportunities` to `biffo.plugin.json`
(Core-managed tables, no RLS/migration complexity, mirroring `idea_scout_runs`/
`idea_scout_candidates`'s shape) plus matching dataclasses. Extend `ports.py`'s
`CoreGateway` protocol with the missing fan-out primitives (`request_agent_run` with
`causation_id`, `find_chain_run`, `get_agent_run`) and brainstorm session/opportunity CRUD;
implement both in `adapter.py`/`transport.py`.

**Done**: a green test suite exercising the new adapter methods against a fake, same
pattern as `test_idea_scout_adapter.py`/`test_idea_scout_ports.py`. No routes, no UI yet.

**Depends on**: nothing. **Files**: `biffo.plugin.json`, `src/ideation/models.py`,
`src/ideation/ports.py`, `src/ideation/adapter.py`, `src/ideation/transport.py`, `tests/`.

### M2: Qualifying-chat backend and routes

New `brainstorm_definitions.py` (the qualifier agent's prompt, reusing Ideation's capped
synchronous multi-turn chat mechanism with new blue-sky framing) and a `BrainstormService`
(`start_session`/`chat_turn`/`get_session`/`list_sessions`/`delete_session`), wired into
`app.py` as new routes (`POST /brainstorm/sessions`, `POST
/brainstorm/sessions/{id}/messages`, `GET`/list/delete). Deliberately no "launch research"
action yet, so nothing dangles a button with no backend to call.

**Done**: API-level tests proving a session can be started and driven through a capped
qualifying conversation.

**Depends on**: M1. **Files**: `src/ideation/brainstorm_definitions.py`,
`src/ideation/service.py` (or new `brainstorm_service.py`), `src/ideation/app.py`,
`tests/`.

### M3: Research fan-out, synthesis, and finalise

Adds the six research agent prompts/schemas (Pain & Intent, Market/Competition,
Workflow/JTBD, Trend, Economics, Contrarian/White-space) plus the synthesis agent, a
`finalise()` method firing all six under one `chain_id` via M1's `request_agent_run`, and
the state-advance logic (`researching`→`synthesising`→`complete`/`failed`, mirroring Idea
Scout's `_advance_research`/`_advance_synthesis` including the "never started" vs "failed"
distinction). Also delivers the fan-in workflow declaration (`brainstorm_fan_in_definition`, six-agent
`expect_agents`, synthesis `agent_name`) with its own tests (mirroring
`test_idea_scout_seed_fan_in_workflow.py`), and extends both `app.py`'s and
`admin_app.py`'s startup seeding to cover all eight new agent roles.

**Done**: unit tests proving the state machine advances correctly against a fake; the seed
script's own tests green. Explicitly call out in the PR description that full live
behaviour additionally needs the seed script run once per environment (see Current State).

**Depends on**: M2 (same `service.py`/`app.py`/`admin_app.py`). Read-disjoint from M4.
**Files**: `src/ideation/brainstorm_definitions.py`, `src/ideation/service.py`,
`src/ideation/app.py`, `src/ideation/admin_app.py`,
`tests/`.

### M4: Brain-Storm tab scaffold and qualifying-chat UI

Introduces real tab state into `web/src/App.tsx` (a `Tab` union alongside the existing
`View` union) and a target-company/market/problem intake form plus the qualifying chat UI,
wired to M2's endpoints only. No "generate opportunities" action yet.

**Done**: a working Brain-Storm tab a user can open, fill in, and converse in, sitting
alongside the unchanged Pressure Test tab.

**Depends on**: M2. Can run in parallel with M3 (disjoint file sets: `web/src/` vs
`src/ideation/`), independently mergeable and useful on its own. **Files**:
`web/src/App.tsx`, new `web/src/components/Brainstorm*.tsx`, `web/src/lib/api.ts`.

### M5: Research progress, results, and hand-off to Pressure Test

Adds the "generate opportunities" action (calling M3's finalise route), progress polling
through `researching`/`synthesising` (same `window.setTimeout` pattern already in
`App.tsx`), a ranked-opportunities results view, and a "Pressure-test this" action per
opportunity reusing the `?seed=`/tab-switch mechanism.

**Done**: a full run from qualifying chat through six parallel agents to a ranked list the
user can click into Pressure Test.

**Depends on**: M3 (backend routes) and M4 (same `App.tsx`, sequential not parallel).
**Files**: `web/src/App.tsx`, `web/src/components/Brainstorm*.tsx`, `web/src/lib/api.ts`.

**Budget note**: M3 is the largest (six prompts + synthesis + the fan-in seed script) and
is scoped at the full ~80k rather than split further — splitting it would ship a partial
`expect_agents` set the fan-in join could never correctly satisfy, which is worse than one
coherent milestone.

## Testing plan

- Each backend milestone (M1-M3) ships its own unit/API-level test suite following Idea
  Scout's existing test patterns exactly (`test_idea_scout_adapter.py`,
  `test_idea_scout_ports.py`, `test_idea_scout_seed_fan_in_workflow.py` are the direct
  templates).
- M4/M5 are UI; verified by the implementer running the dev server and exercising the
  golden path (start a brainstorm, qualify, launch research, see progress, pick an
  opportunity, land in Pressure Test with it seeded) plus edge cases (a failed research
  agent, an empty/short qualifying chat).
- End-to-end live verification (after M5 merges) needs no operator step: the plugin declares its fan-in workflow itself on every startup
  via `POST /internal/plugins/me/workflows/seed` (upsert, keyed by `definition_key`).

## Rollout

File as a `biffo-plugin-ideation` epic via `/biffo-feature-plan`'s own mechanism: commit
this plan under `docs/implementation/NNNN-brain-storming/README.md` (or the plugin's
equivalent doc convention if different from the template's), open the epic issue, post
the 5-milestone decomposition comment with `Depends-on:` lines matching the dependencies
above, label `epic-plan-proposed` (labels were just backfilled onto this repo today,
confirmed present). The fleet's existing triage → ready → implement → prosecute → merge
pipeline builds each milestone once `epic-approved` is applied.
