import type { EffectiveModel, ModelCatalogEntry } from '../lib/api'

interface ModelCatalogListProps {
  entries: ModelCatalogEntry[]
  /** The models actually reaching the runtime, catalog or no catalog. */
  effectiveModels: EffectiveModel[]
  currentDefault: string | null
  onSetDefault: (entryId: string, currentDefault: string | null) => void
  onDelete: (entryId: string) => void
}

/**
 * The models the engine is running on right now. Rendered above the catalog
 * because the catalog is an admin-curated list of *choices* that nothing in the
 * request path reads — so an empty catalog never meant "no models", and saying
 * "No catalog entries yet" and stopping there was the misleading half of issue
 * #58.
 */
function EffectiveModels({ models }: { models: EffectiveModel[] }) {
  if (models.length === 0) return null

  return (
    <div className="admin-effective">
      <h3>Models in use</h3>
      <p className="admin-note">
        What the engine runs on today. These are inherited, not catalog entries — adding or
        removing a catalog entry below does not change them.
      </p>
      <ul className="admin-effective-list">
        {models.map((model) => (
          <li key={model.purpose}>
            <strong>{model.label}:</strong> {model.model_id}{' '}
            <span className={model.source === 'env' ? 'badge-env' : 'badge-builtin'}>
              {model.source === 'env'
                ? `from ${model.env_var}`
                : `built-in default — not stored (set ${model.env_var} to change)`}
            </span>
          </li>
        ))}
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
