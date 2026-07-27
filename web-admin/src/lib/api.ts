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
    // Chat agents (5 routes)
    listChatAgents: () => request<ChatAgent[]>('GET', '/chat-agents'),
    createChatAgent: (agent: Omit<ChatAgent, 'agent_key'>) =>
      request<ChatAgent>('POST', '/chat-agents', agent),
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
