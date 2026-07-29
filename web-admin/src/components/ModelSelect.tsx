import type { ModelCatalogEntry } from '../lib/api'

interface ModelSelectProps {
  entries: ModelCatalogEntry[]
  value: string
  onChange: (modelId: string) => void
  required?: boolean
}

/** The catalog's active entries, default first, then by label. */
export function choosableModels(entries: ModelCatalogEntry[]): ModelCatalogEntry[] {
  return entries
    .filter((e) => e.active)
    .slice()
    .sort((a, b) => {
      if (a.is_default !== b.is_default) return a.is_default ? -1 : 1
      return a.label.localeCompare(b.label)
    })
}

/**
 * The model field on an agent — a picker over the catalog, not free text.
 *
 * This is the half of issue #67 that makes the catalog mean something: it is
 * the admin-curated list of models an agent is *chosen from*, and until now
 * nothing read it, so an agent's model was typed by hand. A slug the provider
 * does not serve is not loud — `anthropic/claude-opus-4-8` sat in this system
 * undetected because the only symptom was analysis failing at 2am while chat
 * kept working (#66). Constraining entry to a curated list is the validation
 * this repo can actually perform; checking a slug against OpenRouter's live
 * catalog would need provider egress the plugin host does not have.
 *
 * Falls back to a free-text input when the catalog is empty, so an empty
 * catalog cannot brick agent creation on a deployment that has never seeded
 * one — and says why, rather than presenting an empty dropdown.
 */
export function ModelSelect({ entries, value, onChange, required }: ModelSelectProps) {
  const choices = choosableModels(entries)

  if (choices.length === 0) {
    return (
      <>
        <input
          type="text"
          required={required}
          aria-label="Model"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="e.g., anthropic/claude-sonnet-4"
        />
        <small>
          The model catalog is empty, so this is free text and nothing checks it. Add entries on the
          Model Catalog tab to pick from a curated list instead.
        </small>
      </>
    )
  }

  // A stored agent may already carry a model that has since left the catalog.
  // Showing it as an extra option — flagged — beats silently rewriting the
  // agent's model to something else the moment an admin opens the edit form.
  const offCatalog = value !== '' && !choices.some((c) => c.model_id === value)

  return (
    <select
      required={required}
      aria-label="Model"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Select a model…</option>
      {choices.map((entry) => (
        <option key={entry.id} value={entry.model_id}>
          {entry.label} ({entry.model_id}){entry.is_default ? ' — catalog default' : ''}
        </option>
      ))}
      {offCatalog && <option value={value}>{value} — not in the catalog</option>}
    </select>
  )
}
