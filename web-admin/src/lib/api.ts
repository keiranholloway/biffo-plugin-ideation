// Admin API client for managing chat agents and model catalog entries.
// Both bases are same-origin and authenticated with the Cognito id token from
// the shared portal session; they differ in who serves the route.
//
// - ADMIN_BASE: this plugin's own admin app, running in the shared plugin host.
//   Chat agents live here because the plugin proxies Core's admin routes for
//   them — there is no declared api_route to serve them.
// - CATALOG_BASE: the model catalog's five CRUD routes are declared in
//   biffo.plugin.json's api_routes, so Core generates them and the plugin host
//   forwards them to Core (biffo-template#684, core >=0.136.0), authorised by
//   the table's own admin-only permissions. Calling that route directly is one
//   hop; routing it through the admin app instead made the host call itself and
//   then forward on to Core — three hops, and a 500 when they outran the
//   client's timeout (biffo-template#652).
//
// The request core (fetch wrapper, bearer auth, error handling, base
// resolution) is shared across every plugin's web-admin — see ./api-core.ts
// (biffo-template#1492). Only this plugin's own endpoint surface lives here.
import { createRequest, ApiError, type GetIdToken } from './api-core'

export { ApiError }

const ADMIN_BASE = '/api/v1/plugins/ideation/admin'
const CATALOG_BASE = '/api/v1/plugins/ideation'

export interface ChatAgent {
  agent_key: string
  agent_name: string
  role: string
  system_prompt: string
  model: string
  required_group: string
  active: boolean
  max_history_messages: number
  max_output_tokens: number
  timeout_seconds: number
}

export interface ModelCatalogEntry {
  id: string
  model_id: string
  label: string
  active: boolean
  is_default: boolean
  /** Can this model search the web (issue #92) — for OpenRouter, does
   * model_id carry the ':online' suffix. Declared explicitly per row rather
   * than parsed from the id here, so a future provider with a different
   * mechanism still fits. */
  web_capable: boolean
}

// ── effective configuration ─────────────────────────────────────────────────
//
// The lists above are *tables*. The engine does not stop working when they are
// empty — it runs on built-in prompts and models, so an empty table rendered as
// "nothing configured" told an admin the opposite of the truth, and "Add New
// Agent" silently overrode an invisible default (issue #58). /effective-config
// reports those built-ins so the panel can show what is actually in use.

/** A built-in agent the engine falls back to when no stored row overrides it. */
export interface BuiltinAgent {
  agent_key: string
  agent_name: string
  role: string
  system_prompt: string
  model: string
  required_group: string
  active: boolean
}

/**
 * Where a model actually comes from, resolved server-side against the stored
 * chat-agent rows — never asserted from this plugin's constants.
 *
 * - `stored`       a stored row is what runs; the built-in is not consulted.
 * - `unconfigured` nothing is stored and there is no fallback (chat only:
 *                  with chat_agents_dynamic on, Core has nothing to resolve
 *                  and every turn fails).
 * - `unknown`      the stored rows could not be read, so no claim is made.
 * - `env`/`built-in` a genuine fallback is in force (analysis only).
 */
export type ModelSource = 'stored' | 'unconfigured' | 'unknown' | 'env' | 'built-in'

/** A model actually reaching the runtime, and where its value came from. */
export interface EffectiveModel {
  purpose: string
  label: string
  /** Null when the source is `unconfigured` or `unknown` — there is no value. */
  model_id: string | null
  source: ModelSource
  /** The stored row this purpose resolves against. */
  agent_key: string
  env_var: string
  /** False for chat: the var only decides what a *seed* would write. */
  env_var_is_runtime_fallback: boolean
  /** What a seed or "store a copy to edit" would put in the row. */
  builtin_model_id: string
  /** The explanation, worded server-side next to the resolution rule. */
  detail: string
}

export interface EffectiveConfig {
  agents: BuiltinAgent[]
  models: EffectiveModel[]
}

// ── Brain-Storm sessions (every user's, read-only) ──────────────────────────

/** Totals over a session's runs. `total_cost_usd` is null when no run is priced:
 * unpriced runs are counted in `unpriced_runs`, never summed as zero. */
export interface CostSummary {
  runs: number
  total_cost_usd: number | null
  priced_runs: number
  unpriced_runs: number
  input_tokens: number
  output_tokens: number
}

export interface SessionSummary {
  session_id: string
  owner_sub: string
  owner_email: string | null
  /** False for sessions created before the email was recorded. */
  owner_email_known: boolean
  /** The email when known, else the raw sub. */
  owner_display: string
  title: string | null
  target: string | null
  status: string
  created_at: string | null
  turn_count: number
  deleted: boolean
  /** Null when the usage read failed (see cost_error). */
  cost: CostSummary | null
  cost_error: boolean
}

export interface CostRow {
  stage: 'qualifying' | 'research' | 'synthesis'
  label: string
  run_id: string
  agent_name: string | null
  model: string | null
  status: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  priced: boolean
}

export interface SessionOpportunity {
  rank: number
  title: string
  pitch: string
  rationale: string | null
  evidence: unknown
  model: string | null
}

export interface SessionDetail extends Omit<SessionSummary, 'cost' | 'cost_error'> {
  geography: string | null
  problem: string | null
  brief: Record<string, unknown> | null
  failure_reason: string | null
  transcript: { role: 'user' | 'assistant'; content: string }[]
  opportunities: SessionOpportunity[]
  cost: CostSummary & { rows: CostRow[] }
}

export interface PressureTestCostRow extends Omit<CostRow, 'stage'> {
  stage: 'chat' | 'analysis'
}

export interface PressureTestSummary extends SessionSummary {
  seed_idea: string
}

export interface PressureTestReport {
  prd: unknown
  scorecard: unknown
  model: string | null
}

export interface PressureTestDetail extends Omit<PressureTestSummary, 'cost' | 'cost_error'> {
  challenger_agent_key: string
  transcript: { role: 'user' | 'assistant'; content: string }[]
  /** Null until the analyst has produced one. */
  report: PressureTestReport | null
  cost: CostSummary & { rows: PressureTestCostRow[] }
}

export interface SessionQuery {
  user?: string
  status?: string
  sort?: 'date' | 'cost'
  order?: 'asc' | 'desc'
}

export type Api = ReturnType<typeof createApi>

export function createApi(getIdToken: GetIdToken) {
  const request = createRequest(getIdToken, ADMIN_BASE)

  return {
    // What the engine is running on, stored or not
    getEffectiveConfig: () => request<EffectiveConfig>('GET', '/effective-config'),

    // Brain-Storm sessions across all users
    listSessions: (q: SessionQuery = {}) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(q)) if (v) params.set(k, v)
      const qs = params.toString()
      return request<{ sessions: SessionSummary[] }>('GET', `/sessions${qs ? `?${qs}` : ''}`)
    },
    getSession: (id: string) =>
      request<SessionDetail>('GET', `/sessions/${encodeURIComponent(id)}`),

    // Pressure Test sessions across all users
    listPressureTestSessions: (q: SessionQuery = {}) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(q)) if (v) params.set(k, v)
      const qs = params.toString()
      return request<{ sessions: PressureTestSummary[] }>(
        'GET',
        `/pressure-test/sessions${qs ? `?${qs}` : ''}`,
      )
    },
    getPressureTestSession: (id: string) =>
      request<PressureTestDetail>('GET', `/pressure-test/sessions/${encodeURIComponent(id)}`),

    // Chat agents (5 routes)
    listChatAgents: () => request<ChatAgent[]>('GET', '/chat-agents'),
    createChatAgent: (agent: Omit<ChatAgent, 'agent_key'>) =>
      request<ChatAgent>('POST', '/chat-agents', agent),
    // Store a built-in default verbatim, so the row that starts overriding it
    // is a copy of what was already running rather than a new definition.
    storeBuiltinAgent: (agent: BuiltinAgent) => request<ChatAgent>('POST', '/chat-agents', agent),
    getChatAgent: (agentKey: string) => request<ChatAgent>('GET', `/chat-agents/${agentKey}`),
    updateChatAgent: (agentKey: string, updates: Partial<ChatAgent>) =>
      request<ChatAgent>('PUT', `/chat-agents/${agentKey}`, updates),
    deleteChatAgent: (agentKey: string) => request<void>('DELETE', `/chat-agents/${agentKey}`),

    // Model catalog (5 routes) — Core's declared api_routes, not an admin proxy
    listModelCatalog: () =>
      request<ModelCatalogEntry[]>('GET', '/model-catalog', undefined, CATALOG_BASE),
    createModelCatalogEntry: (entry: Omit<ModelCatalogEntry, 'id'>) =>
      request<ModelCatalogEntry>('POST', '/model-catalog', entry, CATALOG_BASE),
    getModelCatalogEntry: (entryId: string) =>
      request<ModelCatalogEntry>('GET', `/model-catalog/${entryId}`, undefined, CATALOG_BASE),
    updateModelCatalogEntry: (entryId: string, updates: Partial<ModelCatalogEntry>) =>
      request<ModelCatalogEntry>('PUT', `/model-catalog/${entryId}`, updates, CATALOG_BASE),
    deleteModelCatalogEntry: (entryId: string) =>
      request<void>('DELETE', `/model-catalog/${entryId}`, undefined, CATALOG_BASE),
  }
}
