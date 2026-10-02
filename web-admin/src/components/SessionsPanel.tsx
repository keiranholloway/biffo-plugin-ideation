import { useEffect, useState } from 'react'
import type { Api, SessionQuery, SessionSummary } from '../lib/api'
import { SessionDetailView } from './SessionDetailView'
import { formatCost } from './format'

const STATUSES = ['qualifying', 'researching', 'synthesising', 'complete', 'failed']

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** Every user's Brain-Storm sessions, read-only. Filtering and sorting are done
 * server-side (the cost sort needs every session's usage), so each control
 * change re-queries. */
export function SessionsPanel({ api }: { api: Pick<Api, 'listSessions' | 'getSession'> }) {
  const [user, setUser] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState<'date' | 'cost'>('date')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const q: SessionQuery = { user: user.trim(), status, sort, order }
    setError(null)
    api
      .listSessions(q)
      .then((r) => {
        if (!cancelled) setSessions(r.sessions)
      })
      .catch((e) => {
        if (!cancelled) setError(`Failed to load sessions: ${errorText(e)}`)
      })
    return () => {
      cancelled = true
    }
  }, [api, user, status, sort, order])

  if (openId)
    return <SessionDetailView api={api} sessionId={openId} onBack={() => setOpenId(null)} />

  return (
    <div className="sessions">
      {error && <div className="admin-error">{error}</div>}
      <div className="sessions-filters">
        <label>
          User
          <input
            type="text"
            placeholder="email or sub"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          />
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as 'date' | 'cost')}>
            <option value="date">Date</option>
            <option value="cost">Cost</option>
          </select>
        </label>
        <label>
          Order
          <select value={order} onChange={(e) => setOrder(e.target.value as 'asc' | 'desc')}>
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </label>
      </div>

      {sessions === null ? (
        <p>Loading…</p>
      ) : sessions.length === 0 ? (
        <p>No brain-storm sessions match.</p>
      ) : (
        <table className="sessions-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Title / target</th>
              <th>Status</th>
              <th>Created</th>
              <th>Turns</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.session_id} className={s.deleted ? 'session-row--deleted' : undefined}>
                <td>
                  {s.owner_display}
                  {!s.owner_email_known && <small> (email unknown)</small>}
                </td>
                <td>
                  <button className="link-button" onClick={() => setOpenId(s.session_id)}>
                    {s.title || s.target || s.session_id}
                  </button>
                </td>
                <td>
                  {s.status}
                  {s.deleted && <span className="badge badge--deleted"> Deleted</span>}
                </td>
                <td>{s.created_at ?? '—'}</td>
                <td>{s.turn_count}</td>
                <td>
                  {s.cost_error ? 'Cost unavailable' : formatCost(s.cost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
