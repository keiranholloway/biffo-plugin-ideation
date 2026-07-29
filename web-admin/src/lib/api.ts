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
const ADMIN_BASE = '/api/v1/plugins/ideation/admin'
const CATALOG_BASE = '/api/v1/plugins/ideation'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

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

export type Api = ReturnType<typeof createApi>

export function createApi(getIdToken: () => string | null) {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    base: string = ADMIN_BASE,
  ): Promise<T> {
    const token = getIdToken()
    const res = await fetch(`${base}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token != null ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText)
      throw new ApiError(res.status, detail)
    }
    return res.json() as Promise<T>
  }

  return {
    // What the engine is running on, stored or not
    getEffectiveConfig: () => request<EffectiveConfig>('GET', '/effective-config'),

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
