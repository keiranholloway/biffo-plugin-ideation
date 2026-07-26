import { useState } from 'react'
import type { ChatAgent } from '../lib/api'

interface AgentListProps {
  agents: ChatAgent[]
  onUpdate: (key: string, updates: Partial<ChatAgent>) => void
  onDelete: (key: string) => void
}

export function AgentList({ agents, onUpdate, onDelete }: AgentListProps) {
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

  if (agents.length === 0) {
    return <p className="admin-empty">No agents defined yet.</p>
  }

  return (
    <div className="admin-list">
      {agents.map((agent) => (
        <div key={agent.agent_key} className="admin-list-item">
          {editingKey === agent.agent_key ? (
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
              <label>
                Model:
                <input
                  type="text"
                  value={editForm.model ?? ''}
                  onChange={(e) => setEditForm({ ...editForm, model: e.target.value })}
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
                <h3>{agent.agent_name}</h3>
                <p>
                  <strong>Key:</strong> {agent.agent_key}
                </p>
                <p>
                  <strong>Role:</strong> {agent.role}
                </p>
                <p>
                  <strong>Model:</strong> {agent.model}
                </p>
                <p>
                  <strong>Status:</strong> <span className={agent.active ? 'badge-active' : 'badge-inactive'}>
                    {agent.active ? 'Active' : 'Inactive'}
                  </span>
                </p>
              </div>
              <div className="admin-list-actions">
                <button onClick={() => handleEdit(agent)} className="admin-btn-secondary">
                  Edit
                </button>
                <button
                  onClick={() => onDelete(agent.agent_key)}
                  className="admin-btn-danger"
                >
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  )
}
