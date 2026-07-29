import { useEffect, useState } from 'react'

import { getCurrentSession } from './lib/auth'
import {
  createApi,
  type Api,
  type BuiltinAgent,
  type ChatAgent,
  type EffectiveModel,
  type ModelCatalogEntry,
} from './lib/api'
import { AgentList } from './components/AgentList'
import { AgentForm } from './components/AgentForm'
import { ModelCatalogList } from './components/ModelCatalogList'
import { ModelCatalogForm } from './components/ModelCatalogForm'

type Tab = 'agents' | 'catalog'

function errorText(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

export default function App() {
  const [api, setApi] = useState<Api | null>(null)
  const [ready, setReady] = useState(false)
  const [tab, setTab] = useState<Tab>('agents')
  const [agents, setAgents] = useState<ChatAgent[]>([])
  const [catalogEntries, setCatalogEntries] = useState<ModelCatalogEntry[]>([])
  // What the engine is running on whether or not anything is stored. Without
  // this the panel reports table contents and calls an empty table "not
  // configured", which is the opposite of the truth (issue #58).
  const [builtinAgents, setBuiltinAgents] = useState<BuiltinAgent[]>([])
  const [effectiveModels, setEffectiveModels] = useState<EffectiveModel[]>([])
  const [error, setError] = useState<string | null>(null)

  // Read the shared portal session; no session → show a message.
  useEffect(() => {
    void getCurrentSession().then((s) => {
      if (!s) {
        setReady(true)
        return
      }
      setApi(createApi(() => s.getIdToken().getJwtToken()))
      setReady(true)
    })
  }, [])

  // Fetch agents and catalog when ready. refreshAgents pulls the effective
  // configuration too — it is derived from those same rows (#67).
  useEffect(() => {
    if (!api) return
    void refreshAgents()
    void refreshCatalog()
  }, [api])

  async function refreshEffectiveConfig() {
    if (!api) return
    try {
      const config = await api.getEffectiveConfig()
      setBuiltinAgents(config.agents)
      setEffectiveModels(config.models)
    } catch (e) {
      setError(`Failed to load effective configuration: ${errorText(e)}`)
    }
  }

  /** Reload the agent rows AND the effective configuration derived from them.
   * Since #67 the "Models in use" panel is resolved server-side from these
   * rows, so refreshing one without the other would leave the panel asserting
   * the model the admin just replaced. */
  async function refreshAgents() {
    if (!api) return
    try {
      const list = await api.listChatAgents()
      setAgents(list)
    } catch (e) {
      setError(`Failed to load agents: ${errorText(e)}`)
    }
    await refreshEffectiveConfig()
  }

  async function refreshCatalog() {
    if (!api) return
    try {
      const list = await api.listModelCatalog()
      setCatalogEntries(list)
    } catch (e) {
      setError(`Failed to load catalog: ${errorText(e)}`)
    }
  }

  async function handleCreateAgent(agentData: Omit<ChatAgent, 'agent_key'>) {
    if (!api) return
    setError(null)
    try {
      await api.createChatAgent(agentData)
      await refreshAgents()
    } catch (e) {
      setError(`Failed to create agent: ${errorText(e)}`)
    }
  }

  /** Store a built-in default verbatim so it becomes editable. Spelled out in
   * the confirm, because this is the moment an invisible default turns into a
   * row that overrides it — the trap issue #58 names. */
  async function handleStoreBuiltin(builtin: BuiltinAgent) {
    if (!api) return
    if (
      !window.confirm(
        `Store "${builtin.agent_key}" as an editable row?\n\n` +
          'It copies the built-in default exactly, so nothing changes now. ' +
          'From then on the stored row is what runs, and every edit you make ' +
          'here overrides the built-in default.',
      )
    )
      return
    setError(null)
    try {
      await api.storeBuiltinAgent(builtin)
      await refreshAgents()
    } catch (e) {
      setError(`Failed to store default: ${errorText(e)}`)
    }
  }

  async function handleUpdateAgent(agentKey: string, updates: Partial<ChatAgent>) {
    if (!api) return
    setError(null)
    try {
      await api.updateChatAgent(agentKey, updates)
      await refreshAgents()
    } catch (e) {
      setError(`Failed to update agent: ${errorText(e)}`)
    }
  }

  async function handleDeleteAgent(agentKey: string) {
    if (!api) return
    if (!window.confirm('Delete this agent? This action cannot be undone.')) return
    setError(null)
    try {
      await api.deleteChatAgent(agentKey)
      await refreshAgents()
    } catch (e) {
      setError(`Failed to delete agent: ${errorText(e)}`)
    }
  }

  async function handleCreateCatalogEntry(entryData: Omit<ModelCatalogEntry, 'id'>) {
    if (!api) return
    setError(null)
    try {
      await api.createModelCatalogEntry(entryData)
      await refreshCatalog()
    } catch (e) {
      setError(`Failed to create catalog entry: ${errorText(e)}`)
    }
  }

  async function handleSetDefault(entryId: string, currentDefault: string | null) {
    if (!api) return
    setError(null)
    try {
      // Set the new default
      await api.updateModelCatalogEntry(entryId, { is_default: true })
      // Unset the old default (if any)
      if (currentDefault && currentDefault !== entryId) {
        await api.updateModelCatalogEntry(currentDefault, { is_default: false })
      }
      await refreshCatalog()
    } catch (e) {
      setError(`Failed to set default: ${errorText(e)}`)
    }
  }

  async function handleDeleteCatalogEntry(entryId: string) {
    if (!api) return
    if (!window.confirm('Delete this entry? This action cannot be undone.')) return
    setError(null)
    try {
      await api.deleteModelCatalogEntry(entryId)
      await refreshCatalog()
    } catch (e) {
      setError(`Failed to delete entry: ${errorText(e)}`)
    }
  }

  if (!ready) return <main className="admin">Loading…</main>

  if (!api) {
    return (
      <main className="admin">
        <h1>Ideation Engine — Admin</h1>
        <p>No session found. Please sign in through the portal.</p>
      </main>
    )
  }

  const currentDefault = catalogEntries.find((e) => e.is_default)?.id ?? null

  return (
    <main className="admin">
      <h1>Ideation Engine — Admin</h1>

      {error && <div className="admin-error">{error}</div>}

      <div className="admin-tabs">
        <button
          className={`admin-tab ${tab === 'agents' ? 'admin-tab--active' : ''}`}
          onClick={() => setTab('agents')}
        >
          Chat Agents
        </button>
        <button
          className={`admin-tab ${tab === 'catalog' ? 'admin-tab--active' : ''}`}
          onClick={() => setTab('catalog')}
        >
          Model Catalog
        </button>
      </div>

      {tab === 'agents' && (
        <section className="admin-section">
          <h2>Chat Agents</h2>
          <AgentForm onSubmit={handleCreateAgent} catalogEntries={catalogEntries} />
          <AgentList
            agents={agents}
            builtins={builtinAgents}
            catalogEntries={catalogEntries}
            onUpdate={handleUpdateAgent}
            onDelete={handleDeleteAgent}
            onStoreBuiltin={handleStoreBuiltin}
          />
        </section>
      )}

      {tab === 'catalog' && (
        <section className="admin-section">
          <h2>Model Catalog</h2>
          <ModelCatalogForm onSubmit={handleCreateCatalogEntry} />
          <ModelCatalogList
            entries={catalogEntries}
            effectiveModels={effectiveModels}
            currentDefault={currentDefault}
            onSetDefault={handleSetDefault}
            onDelete={handleDeleteCatalogEntry}
          />
        </section>
      )}
    </main>
  )
}
