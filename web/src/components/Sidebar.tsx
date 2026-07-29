import type { SessionSummary } from '../lib/api'

export interface SidebarProps {
  sessions: SessionSummary[]
  activeId: string | null
  onSelect: (session: SessionSummary) => void
  onNewIdea: () => void
  onDelete: (session: SessionSummary) => void
  /** The last list load failed, so `sessions` is unknown rather than empty. */
  loadFailed?: boolean
  /**
   * The list has been fetched at least once, so an empty `sessions` means the
   * founder genuinely has none. Defaults true so a caller that never fetches
   * (a static list) keeps behaving as before; App sets it from its own state.
   */
  loaded?: boolean
}

export function Sidebar({ sessions, activeId, onSelect, onNewIdea, onDelete, loadFailed = false, loaded = true }: SidebarProps) {
  return (
    <nav className="ide-sidebar">
      <div className="ide-sidebar-header">
        <button className="ide-sidebar-new" onClick={onNewIdea}>
          Ideate
        </button>
      </div>

      {sessions.length === 0 && loadFailed ? (
        // Never claim "no past runs" off a failed load: to a founder whose runs
        // are right there in the database, that empty state reads as data loss,
        // and it is the reason #69 was filed against the wrong layer twice.
        <p className="ide-sidebar-empty ide-sidebar-empty--error" role="status">
          Couldn&apos;t load your past runs
        </p>
      ) : sessions.length === 0 && !loaded ? (
        // Three states exist — not yet asked, asked and empty, asked and
        // failed — and until #83 this component modelled two. Between mount
        // and the first fetch resolving, `sessions` is [] and `loadFailed` is
        // false, which is indistinguishable from a completed empty load, so
        // the founder was told "No past runs yet" before anyone had looked.
        <p className="ide-sidebar-empty" role="status">
          Loading your past runs…
        </p>
      ) : sessions.length === 0 ? (
        <p className="ide-sidebar-empty">No past runs yet</p>
      ) : (
        <ul className="ide-sidebar-list">
          {sessions.map((session) => (
            <li key={session.session_id} className="ide-sidebar-row">
              <button
                className={`ide-sidebar-item ${activeId === session.session_id ? 'ide-sidebar-item--active' : ''}`}
                onClick={() => onSelect(session)}
              >
                <div className="ide-sidebar-item-title">{session.title}</div>
                <div className="ide-sidebar-item-meta">
                  <span className="ide-sidebar-item-date">
                    {new Date(session.created_at).toLocaleDateString()}
                  </span>
                  <span className={`ide-sidebar-item-status ide-sidebar-item-status--${session.status}`}>
                    {session.status}
                  </span>
                </div>
              </button>
              <button
                type="button"
                className="ide-sidebar-delete"
                aria-label="Delete this idea"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(session)
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}
