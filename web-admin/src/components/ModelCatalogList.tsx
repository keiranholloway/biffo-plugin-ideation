import type { ModelCatalogEntry } from '../lib/api'

interface ModelCatalogListProps {
  entries: ModelCatalogEntry[]
  currentDefault: string | null
  onSetDefault: (entryId: string, currentDefault: string | null) => void
  onDelete: (entryId: string) => void
}

export function ModelCatalogList({
  entries,
  currentDefault,
  onSetDefault,
  onDelete,
}: ModelCatalogListProps) {
  if (entries.length === 0) {
    return <p className="admin-empty">No catalog entries yet.</p>
  }

  return (
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
  )
}
