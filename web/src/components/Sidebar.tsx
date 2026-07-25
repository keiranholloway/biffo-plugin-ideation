import type { SessionSummary } from '../lib/api'

export interface SidebarProps {
  sessions: SessionSummary[]
  activeId: string | null
  onSelect: (session: SessionSummary) => void
  onNewIdea: () => void
}

export function Sidebar({ sessions, activeId, onSelect, onNewIdea }: SidebarProps) {
  return (
    <nav className="ide-sidebar">
      <div className="ide-sidebar-header">
        <button className="ide-sidebar-new" onClick={onNewIdea}>
          + New idea
        </button>
      </div>

      {sessions.length === 0 ? (
        <p className="ide-sidebar-empty">No past runs yet</p>
      ) : (
        <ul className="ide-sidebar-list">
          {sessions.map((session) => (
            <li key={session.session_id}>
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
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}
