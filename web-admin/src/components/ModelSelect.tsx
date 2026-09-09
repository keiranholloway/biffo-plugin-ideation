import type { ModelCatalogEntry } from '../lib/api'

interface ModelSelectProps {
  entries: ModelCatalogEntry[]
  value: string
  onChange: (modelId: string) => void
  required?: boolean
  /** This field's agent role, so the picker can filter to web-capable models
   * when it requires search (issue #92). Optional: callers with no role in
   * scope (there are none left in this repo, but a future one might) simply
   * get the unfiltered picker rather than a required prop they cannot fill. */
  role?: string
}

/**
 * The one place "this role needs `:online`" is declared (issue #92's "Worth
 * deciding" — the plugin's own convention, matching the exact role string
 * ``ideation.effective_config.ANALYST_ROLE`` already uses server-side to
 * resolve the stored analyst row). Declaring it here rather than adding a
 * column to ``plugin_chat_agents`` (a Core-owned table this repo does not
 * define) or the manifest keeps the change to this plugin's own frontend,
 * reversible with no new schema or auth surface.
 */
export function roleRequiresWebSearch(role: string | undefined): boolean {
  return role === 'analyst'
}

/** The catalog's active entries, default first, then by label. */
export function choosableModels(
  entries: ModelCatalogEntry[],
  options?: { requireWebCapable?: boolean },
): ModelCatalogEntry[] {
  return entries
    .filter((e) => e.active)
    .filter((e) => !options?.requireWebCapable || e.web_capable)
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
 *
 * When ``role`` requires web search (issue #92), the dropdown filters to
 * ``web_capable`` entries — the same list-narrowing #67 already does for
 * "active" — rather than presenting the ten-model list a search-dependent
 * agent silently fails on eight of. If filtering would leave nothing to pick
 * (no catalog entry is marked web-capable yet), it falls back to every active
 * entry with an inline warning instead of stranding the admin with an empty
 * picker.
 */
export function ModelSelect({ entries, value, onChange, required, role }: ModelSelectProps) {
  const requiresWebSearch = roleRequiresWebSearch(role)
  const allActive = choosableModels(entries)

  if (allActive.length === 0) {
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

  const webCapableChoices = choosableModels(entries, { requireWebCapable: true })
  const filtering = requiresWebSearch && webCapableChoices.length > 0
  const choices = filtering ? webCapableChoices : allActive

  // A stored agent may already carry a model that has since left the catalog,
  // or — since #92 — one the catalog no longer (or never did) mark
  // web-capable while this role requires search. Either way: show it as an
  // extra option, flagged, rather than silently rewriting the agent's model
  // the moment an admin opens the edit form.
  const selectedEntry = allActive.find((c) => c.model_id === value)
  const flagged = value !== '' && !choices.some((c) => c.model_id === value)
  const flagText = !selectedEntry
    ? `${value} — not in the catalog`
    : `${value} — not web-capable, but this role requires search`

  return (
    <>
      {requiresWebSearch && (
        <small className={filtering ? 'admin-note' : 'admin-warning'}>
          {filtering
            ? 'This role requires web search — only web-capable (":online") models are shown.'
            : 'This role requires web search, but no catalog entry is marked web-capable yet. ' +
              'Showing every active model instead — pick one whose id carries the ":online" ' +
              'suffix, or add a web-capable entry on the Model Catalog tab.'}
        </small>
      )}
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
        {flagged && <option value={value}>{flagText}</option>}
      </select>
    </>
  )
}
