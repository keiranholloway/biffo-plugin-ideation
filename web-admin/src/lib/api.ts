// Admin API client for managing chat agents and model catalog entries.
// Called through the shared plugin host at /api/v1/plugins/ideation/admin/*,
// authenticated via Cognito id token forwarded from the shared portal session.

const API_BASE = '/api/v1/plugins/ideation/admin'

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
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = getIdToken()
    const res = await fetch(`${API_BASE}${path}`, {
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

    // Model catalog (5 routes)
    listModelCatalog: () => request<ModelCatalogEntry[]>('GET', '/model-catalog'),
    createModelCatalogEntry: (entry: Omit<ModelCatalogEntry, 'id'>) =>
      request<ModelCatalogEntry>('POST', '/model-catalog', entry),
    getModelCatalogEntry: (entryId: string) =>
      request<ModelCatalogEntry>('GET', `/model-catalog/${entryId}`),
    updateModelCatalogEntry: (entryId: string, updates: Partial<ModelCatalogEntry>) =>
      request<ModelCatalogEntry>('PUT', `/model-catalog/${entryId}`, updates),
    deleteModelCatalogEntry: (entryId: string) =>
      request<void>('DELETE', `/model-catalog/${entryId}`),
  }
}
