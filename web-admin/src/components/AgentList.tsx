import { useState } from 'react'
import type { BuiltinAgent, ChatAgent, ModelCatalogEntry } from '../lib/api'
import { ModelSelect } from './ModelSelect'

interface AgentListProps {
  agents: ChatAgent[]
  /** The agents the engine falls back to when no stored row overrides them. */
  builtins: BuiltinAgent[]
  /** The curated list the model is chosen from (issue #67). */
  catalogEntries: ModelCatalogEntry[]
  onUpdate: (key: string, updates: Partial<ChatAgent>) => void
  onDelete: (key: string) => void
  onStoreBuiltin: (builtin: BuiltinAgent) => void
}

/**
 * One row of the merged view: a stored row, or a built-in with nothing stored
 * over it. The panel lists both because the table alone does not describe what
 * the engine is running (issue #58).
 */
type Row =
  | { kind: 'stored'; agent: ChatAgent; overridesBuiltin: boolean }
  | { kind: 'builtin'; agent: BuiltinAgent }

export function mergeAgentRows(agents: ChatAgent[], builtins: BuiltinAgent[]): Row[] {
  const storedKeys = new Set(agents.map((a) => a.agent_key))
  const builtinKeys = new Set(builtins.map((b) => b.agent_key))
  return [
    ...agents.map(
      (agent): Row => ({
        kind: 'stored',
        agent,
        overridesBuiltin: builtinKeys.has(agent.agent_key),
      }),
    ),
    ...builtins
      .filter((b) => !storedKeys.has(b.agent_key))
      .map((agent): Row => ({ kind: 'builtin', agent })),
  ]
}

export function AgentList({
  agents,
  builtins,
  catalogEntries,
  onUpdate,
  onDelete,
  onStoreBuiltin,
}: AgentListProps) {
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<ChatAgent>>({})

  function handleEdit(agent: ChatAgent) {
    setEditingKey(agent.agent_key)
    setEditForm({ ...agent })
  }

  function handleSaveEdit() {
    if (!editingKey) return
    onUpdate(editingKey, editForm)
    setEditingKey(null)
    setEditForm({})
  }

  function handleCancel() {
    setEditingKey(null)
    setEditForm({})
  }

  const rows = mergeAgentRows(agents, builtins)

  if (rows.length === 0) {
    return <p className="admin-empty">No agents stored, and no built-in defaults reported.</p>
  }

  return (
    <>
      {agents.length === 0 && (
        <p className="admin-note">
          No agents are stored. The engine is running on the built-in defaults below — it is
          configured, just not from this table.
        </p>
      )}

      <div className="admin-list">
        {rows.map((row) =>
          row.kind === 'builtin' ? (
            <div key={row.agent.agent_key} className="admin-list-item admin-list-item--builtin">
              <div className="admin-list-content">
                <h3>{row.agent.agent_name}</h3>
                <p>
                  <strong>Source:</strong>{' '}
                  <span className="badge-builtin">Default — not stored</span>
                </p>
                <p>
                  <strong>Key:</strong> {row.agent.agent_key}
                </p>
                <p>
                  <strong>Role:</strong> {row.agent.role}
                </p>
                <p>
                  <strong>Model:</strong> {row.agent.model}
                </p>
                <details>
                  <summary>System prompt (in use)</summary>
                  <pre className="admin-prompt">{row.agent.system_prompt}</pre>
                </details>
              </div>
              <div className="admin-list-actions">
                <button onClick={() => onStoreBuiltin(row.agent)} className="admin-btn-secondary">
                  Store a copy to edit
                </button>
              </div>
            </div>
          ) : (
            <div key={row.agent.agent_key} className="admin-list-item">
              {editingKey === row.agent.agent_key ? (
                <div className="admin-edit-form">
                  <label>
                    Name:
                    <input
                      type="text"
                      value={editForm.agent_name ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, agent_name: e.target.value })}
                    />
                  </label>
                  <label>
                    Role:
                    <input
                      type="text"
                      value={editForm.role ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                    />
                  </label>
                  {/* A picker, not free text: this row's model is what Core
                      resolves the challenger on (chat_agents_dynamic), and a
                      slug the provider does not serve fails silently at
                      request time rather than at entry (#66, #67). */}
                  <label>
                    Model:
                    <ModelSelect
                      entries={catalogEntries}
                      value={editForm.model ?? ''}
                      onChange={(model) => setEditForm({ ...editForm, model })}
                    />
                  </label>
                  {/*
                    Without this field a stored row's prompt was editable by
                    nothing: the form omitted it, and a stored row overrides the
                    built-in constant, so changing definitions.py no longer
                    reached the runtime either. "Store a copy to edit" invited
                    exactly the action that froze the prompt.
                  */}
                  <label>
                    System prompt:
                    <textarea
                      className="admin-prompt-input"
                      rows={14}
                      value={editForm.system_prompt ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, system_prompt: e.target.value })}
                    />
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={editForm.active ?? false}
                      onChange={(e) => setEditForm({ ...editForm, active: e.target.checked })}
                    />
                    Active
                  </label>
                  <div className="admin-form-actions">
                    <button onClick={handleSaveEdit} className="admin-btn-primary">
                      Save
                    </button>
                    <button onClick={handleCancel} className="admin-btn-secondary">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="admin-list-content">
                    <h3>{row.agent.agent_name}</h3>
                    <p>
                      <strong>Source:</strong>{' '}
                      <span className="badge-stored">
                        {row.overridesBuiltin
                          ? 'Stored — overrides the built-in default'
                          : 'Stored'}
                      </span>
                    </p>
                    <p>
                      <strong>Key:</strong> {row.agent.agent_key}
                    </p>
                    <p>
                      <strong>Role:</strong> {row.agent.role}
                    </p>
                    <p>
                      <strong>Model:</strong> {row.agent.model}
                    </p>
                    <p>
                      <strong>Status:</strong>{' '}
                      <span className={row.agent.active ? 'badge-active' : 'badge-inactive'}>
                        {row.agent.active ? 'Active' : 'Inactive'}
                      </span>
                    </p>
                    {/* Built-in rows have shown their prompt since #60; stored
                        rows did not, so storing a copy made the prompt that is
                        actually running less visible than the one it replaced. */}
                    <details>
                      <summary>System prompt (in use)</summary>
                      <pre className="admin-prompt">{row.agent.system_prompt}</pre>
                    </details>
                  </div>
                  <div className="admin-list-actions">
                    <button onClick={() => handleEdit(row.agent)} className="admin-btn-secondary">
                      Edit
                    </button>
                    <button
                      onClick={() => onDelete(row.agent.agent_key)}
                      className="admin-btn-danger"
                    >
                      Delete
                    </button>
                  </div>
                </>
              )}
            </div>
          ),
        )}
      </div>
    </>
  )
}
