import type { EffectiveModel, ModelCatalogEntry } from '../lib/api'

interface ModelCatalogListProps {
  entries: ModelCatalogEntry[]
  /** The models actually reaching the runtime, catalog or no catalog. */
  effectiveModels: EffectiveModel[]
  currentDefault: string | null
  onSetDefault: (entryId: string, currentDefault: string | null) => void
  onDelete: (entryId: string) => void
}

const SOURCE_BADGE: Record<EffectiveModel['source'], { className: string; text: string }> = {
  stored: { className: 'badge-stored', text: 'from its stored agent row' },
  unconfigured: { className: 'badge-danger', text: 'not configured — this path fails' },
  unknown: { className: 'badge-unknown', text: 'unknown — could not read the stored rows' },
  env: { className: 'badge-env', text: 'from the environment' },
  'built-in': { className: 'badge-builtin', text: 'built-in default — nothing stored over it' },
}

/**
 * The models the engine is running on right now. Rendered above the catalog
 * because the catalog is an admin-curated list of *choices* that nothing in the
 * request path reads — so an empty catalog never meant "no models", and saying
 * "No catalog entries yet" and stopping there was the misleading half of issue
 * #58.
 *
 * The values themselves are resolved server-side against the stored chat-agent
 * rows (issue #67). This component deliberately does no resolving of its own:
 * the previous version rendered the built-in constants with the badge "built-in
 * default — not stored (set IDEATION_CHAT_MODEL to change)", which was false
 * for the challenger under any table at all — that env var never reaches Core,
 * so setting it would have changed this line without changing what ran.
 */
function EffectiveModels({ models }: { models: EffectiveModel[] }) {
  if (models.length === 0) return null

  return (
    <div className="admin-effective">
      <h3>Models in use</h3>
      <p className="admin-note">
        What the engine runs on today, resolved against the stored agent rows — not catalog
        entries. Adding or removing a catalog entry below does not change them; editing the agent
        on the Chat Agents tab does.
      </p>
      <ul className="admin-effective-list">
        {models.map((model) => {
          const badge = SOURCE_BADGE[model.source]
          return (
            <li key={model.purpose}>
              <strong>{model.label}:</strong>{' '}
              {model.model_id ?? <em>none</em>}{' '}
              <span className={badge.className}>{badge.text}</span>
              <p className="admin-note admin-effective-detail">{model.detail}</p>
              {model.model_id !== model.builtin_model_id && (
                <p className="admin-note admin-effective-detail">
                  Built-in default (what seeding this agent would store):{' '}
                  <code>{model.builtin_model_id}</code>
                  {model.env_var_is_runtime_fallback
                    ? `, overridable with ${model.env_var}.`
                    : `. ${model.env_var} only changes that seed value — it is never sent to Core.`}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function ModelCatalogList({
  entries,
  effectiveModels,
  currentDefault,
  onSetDefault,
  onDelete,
}: ModelCatalogListProps) {
  if (entries.length === 0) {
    return (
      <>
        <EffectiveModels models={effectiveModels} />
        <p className="admin-empty">
          No catalog entries stored. The catalog is an optional curated list for admins; the engine
          is running on the models above.
        </p>
      </>
    )
  }

  return (
    <>
      <EffectiveModels models={effectiveModels} />
      <div className="admin-list">
      {entries.map((entry) => (
        <div key={entry.id} className="admin-list-item">
          <div className="admin-list-content">
            <h3>{entry.label}</h3>
            <p>
              <strong>Model ID:</strong> {entry.model_id}
            </p>
            <p>
              <strong>Status:</strong> <span className={entry.active ? 'badge-active' : 'badge-inactive'}>
                {entry.active ? 'Active' : 'Inactive'}
              </span>
            </p>
            <p>
              <strong>Default:</strong>{' '}
              <span className={entry.is_default ? 'badge-default' : 'badge-not-default'}>
                {entry.is_default ? 'Yes' : 'No'}
              </span>
            </p>
            <p>
              {/* Issue #92: the only place an admin can see, at a glance,
                  which entries a search-dependent agent (e.g. the ideation
                  analyst) can actually be pointed at. */}
              <strong>Web-capable:</strong>{' '}
              <span className={entry.web_capable ? 'badge-active' : 'badge-inactive'}>
                {entry.web_capable ? 'Yes' : 'No'}
              </span>
            </p>
          </div>
          <div className="admin-list-actions">
            {!entry.is_default && (
              <button
                onClick={() => onSetDefault(entry.id, currentDefault)}
                className="admin-btn-secondary"
              >
                Set as Default
              </button>
            )}
            <button
              onClick={() => onDelete(entry.id)}
              className="admin-btn-danger"
            >
              Delete
            </button>
          </div>
        </div>
      ))}
      </div>
    </>
  )
}
