import type { SessionSummary } from '../lib/api'

export interface SidebarProps<T = SessionSummary> {
  sessions: T[]
  activeId: string | null
  onSelect: (session: T) => void
  onNewIdea: () => void
  onDelete: (session: T) => void
  /** Accessors; default to the Pressure Test `SessionSummary` shape. */
  getId?: (item: T) => string
  getTitle?: (item: T) => string
  getStatus?: (item: T) => string
  getDate?: (item: T) => string | null | undefined
  /** Text of the top button (default "Ideate"). */
  newLabel?: string
  loadingText?: string
  emptyText?: string
  failedText?: string
  /** aria-label of each row's delete button. */
  deleteLabel?: (item: T) => string
  /** Disable select/new while something is in flight. */
  disabled?: boolean
  /** The last list load failed, so `sessions` is unknown rather than empty. */
  loadFailed?: boolean
  /**
   * The list has been fetched at least once, so an empty `sessions` means the
   * founder genuinely has none. Defaults true so a caller that never fetches
   * (a static list) keeps behaving as before; App sets it from its own state.
   */
  loaded?: boolean
}

export function Sidebar<T = SessionSummary>({
  sessions,
  activeId,
  onSelect,
  onNewIdea,
  onDelete,
  loadFailed = false,
  loaded = true,
  getId = (i) => (i as SessionSummary).session_id,
  getTitle = (i) => (i as SessionSummary).title,
  getStatus = (i) => (i as SessionSummary).status,
  getDate = (i) => (i as SessionSummary).created_at,
  newLabel = 'Ideate',
  loadingText = 'Loading your past runs…',
  emptyText = 'No past runs yet',
  failedText = "Couldn't load your past runs",
  deleteLabel = () => 'Delete this idea',
  disabled = false,
}: SidebarProps<T>) {
  return (
    <nav className="ide-sidebar">
      <div className="ide-sidebar-header">
        <button className="ide-sidebar-new" onClick={onNewIdea} disabled={disabled}>
          {newLabel}
        </button>
      </div>

      {sessions.length === 0 && loadFailed ? (
        // Never claim "no past runs" off a failed load: to a founder whose runs
        // are right there in the database, that empty state reads as data loss,
        // and it is the reason #69 was filed against the wrong layer twice.
        <p className="ide-sidebar-empty ide-sidebar-empty--error" role="status">
          {failedText}
        </p>
      ) : sessions.length === 0 && !loaded ? (
        // Three states exist — not yet asked, asked and empty, asked and
        // failed — and until #83 this component modelled two. Between mount
        // and the first fetch resolving, `sessions` is [] and `loadFailed` is
        // false, which is indistinguishable from a completed empty load, so
        // the founder was told "No past runs yet" before anyone had looked.
        <p className="ide-sidebar-empty" role="status">
          {loadingText}
        </p>
      ) : sessions.length === 0 ? (
        <p className="ide-sidebar-empty">{emptyText}</p>
      ) : (
        <ul className="ide-sidebar-list">
          {sessions.map((session) => {
            const id = getId(session)
            const status = getStatus(session)
            const date = getDate(session)
            return (
              <li key={id} className="ide-sidebar-row">
                <button
                  className={`ide-sidebar-item ${activeId === id ? 'ide-sidebar-item--active' : ''}`}
                  onClick={() => onSelect(session)}
                  disabled={disabled}
                >
                  <div className="ide-sidebar-item-title">{getTitle(session)}</div>
                  <div className="ide-sidebar-item-meta">
                    <span className="ide-sidebar-item-date">
                      {date ? new Date(date).toLocaleDateString() : ''}
                    </span>
                    <span className={`ide-sidebar-item-status ide-sidebar-item-status--${status}`}>{status}</span>
                  </div>
                </button>
                <button
                  type="button"
                  className="ide-sidebar-delete"
                  aria-label={deleteLabel(session)}
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(session)
                  }}
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </nav>
  )
}
