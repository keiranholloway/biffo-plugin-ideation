import { useState } from 'react'
import type { ChatAgent } from '../lib/api'

interface AgentFormProps {
  onSubmit: (agent: Omit<ChatAgent, 'agent_key'>) => void
}

export function AgentForm({ onSubmit }: AgentFormProps) {
  const [form, setForm] = useState<Omit<ChatAgent, 'agent_key'>>({
    agent_name: '',
    role: '',
    system_prompt: '',
    model: '',
    required_group: '',
    active: true,
    max_history_messages: 10,
    max_output_tokens: 2000,
    timeout_seconds: 30,
  })
  const [showForm, setShowForm] = useState(false)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSubmit(form)
    setForm({
      agent_name: '',
      role: '',
      system_prompt: '',
      model: '',
      required_group: '',
      active: true,
      max_history_messages: 10,
      max_output_tokens: 2000,
      timeout_seconds: 30,
    })
    setShowForm(false)
  }

  return (
    <div className="admin-form-container">
      <button
        onClick={() => setShowForm(!showForm)}
        className="admin-btn-primary"
      >
        {showForm ? 'Cancel' : 'Add New Agent'}
      </button>

      {showForm && (
        <form onSubmit={handleSubmit} className="admin-form">
          <label>
            Agent Name:
            <input
              type="text"
              required
              value={form.agent_name}
              onChange={(e) => setForm({ ...form, agent_name: e.target.value })}
            />
          </label>

          <label>
            Role:
            <input
              type="text"
              required
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
            />
          </label>

          <label>
            System Prompt:
            <textarea
              required
              value={form.system_prompt}
              onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
              rows={5}
            />
          </label>

          <label>
            Model:
            <input
              type="text"
              required
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
            />
          </label>

          <label>
            Required Group:
            <input
              type="text"
              value={form.required_group}
              onChange={(e) => setForm({ ...form, required_group: e.target.value })}
            />
          </label>

          <label>
            Max History Messages:
            <input
              type="number"
              value={form.max_history_messages}
              onChange={(e) => setForm({ ...form, max_history_messages: parseInt(e.target.value, 10) })}
            />
          </label>

          <label>
            Max Output Tokens:
            <input
              type="number"
              value={form.max_output_tokens}
              onChange={(e) => setForm({ ...form, max_output_tokens: parseInt(e.target.value, 10) })}
            />
          </label>

          <label>
            Timeout (seconds):
            <input
              type="number"
              value={form.timeout_seconds}
              onChange={(e) => setForm({ ...form, timeout_seconds: parseInt(e.target.value, 10) })}
            />
          </label>

          <label>
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => setForm({ ...form, active: e.target.checked })}
            />
            Active
          </label>

          <button type="submit" className="admin-btn-primary">
            Create Agent
          </button>
        </form>
      )}
    </div>
  )
}
