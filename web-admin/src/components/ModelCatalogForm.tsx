import { useState } from 'react'
import type { ModelCatalogEntry } from '../lib/api'

interface ModelCatalogFormProps {
  onSubmit: (entry: Omit<ModelCatalogEntry, 'id'>) => void
}

export function ModelCatalogForm({ onSubmit }: ModelCatalogFormProps) {
  const [form, setForm] = useState<Omit<ModelCatalogEntry, 'id'>>({
    model_id: '',
    label: '',
    active: true,
    is_default: false,
    web_capable: false,
  })
  const [showForm, setShowForm] = useState(false)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSubmit(form)
    setForm({
      model_id: '',
      label: '',
      active: true,
      is_default: false,
      web_capable: false,
    })
    setShowForm(false)
  }

  return (
    <div className="admin-form-container">
      <button
        onClick={() => setShowForm(!showForm)}
        className="admin-btn-primary"
      >
        {showForm ? 'Cancel' : 'Add Catalog Entry'}
      </button>

      {showForm && (
        <form onSubmit={handleSubmit} className="admin-form">
          <label>
            Model ID:
            <input
              type="text"
              required
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
              placeholder="e.g., claude-3-sonnet-20240229"
            />
          </label>

          <label>
            Label:
            <input
              type="text"
              required
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="e.g., Claude 3 Sonnet"
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

          <label>
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
            />
            Set as Default
          </label>

          <label>
            <input
              type="checkbox"
              checked={form.web_capable}
              onChange={(e) => setForm({ ...form, web_capable: e.target.checked })}
            />
            Web-capable (model id carries OpenRouter's ':online' suffix)
          </label>

          <button type="submit" className="admin-btn-primary">
            Create Entry
          </button>
        </form>
      )}
    </div>
  )
}
