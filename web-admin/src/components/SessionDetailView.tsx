import { useEffect, useState } from 'react'
import type { Api, SessionDetail } from '../lib/api'
import { formatCost, formatUsd } from './format'

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** One session, read-only: brief, full transcript, ranked opportunities, and
 * the models/tokens/cost per stage. */
export function SessionDetailView({
  api,
  sessionId,
  onBack,
}: {
  api: Pick<Api, 'getSession'>
  sessionId: string
  onBack: () => void
}) {
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getSession(sessionId)
      .then((d) => {
        if (!cancelled) setDetail(d)
      })
      .catch((e) => {
        if (!cancelled) setError(`Failed to load session: ${errorText(e)}`)
      })
    return () => {
      cancelled = true
    }
  }, [api, sessionId])

  return (
    <div className="session-detail">
      <button onClick={onBack}>← All sessions</button>
      {error && <div className="admin-error">{error}</div>}
      {!detail && !error && <p>Loading…</p>}
      {detail && (
        <>
          <h3>
            {detail.title || detail.target || detail.session_id}
            {detail.deleted && <span className="badge badge--deleted"> Deleted</span>}
          </h3>
          <p>
            Run by {detail.owner_display}
            {!detail.owner_email_known && ' (email unknown — only the user id was recorded)'} ·{' '}
            {detail.status} · {detail.created_at ?? '—'} · {detail.turn_count} turns
          </p>
          {detail.failure_reason && <p className="admin-error">{detail.failure_reason}</p>}

          <h4>Brief</h4>
          {detail.brief ? (
            <pre>{JSON.stringify(detail.brief, null, 2)}</pre>
          ) : (
            <p>
              {[detail.target, detail.geography, detail.problem].filter(Boolean).join(' · ') ||
                'No brief yet.'}
            </p>
          )}

          <h4>Qualifying transcript</h4>
          {detail.transcript.length === 0 ? (
            <p>No messages.</p>
          ) : (
            <ol className="transcript">
              {detail.transcript.map((m, i) => (
                <li key={i}>
                  <strong>{m.role === 'user' ? 'User' : 'Assistant'}:</strong> {m.content}
                </li>
              ))}
            </ol>
          )}

          <h4>Ranked opportunities</h4>
          {detail.opportunities.length === 0 ? (
            <p>No opportunities.</p>
          ) : (
            <ol className="opportunities">
              {detail.opportunities.map((o) => (
                <li key={o.rank}>
                  <strong>{o.title}</strong>
                  <p>{o.pitch}</p>
                  {o.rationale && <p>{o.rationale}</p>}
                </li>
              ))}
            </ol>
          )}

          <h4>Models and cost</h4>
          <table className="cost-table">
            <thead>
              <tr>
                <th>Stage</th>
                <th>Model</th>
                <th>Input tokens</th>
                <th>Output tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {detail.cost.rows.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.label}</td>
                  <td>{r.model ?? 'unknown'}</td>
                  <td>{r.input_tokens ?? '—'}</td>
                  <td>{r.output_tokens ?? '—'}</td>
                  <td className={r.priced ? undefined : 'cost--unpriced'}>
                    {formatUsd(r.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>Total</th>
                <th>{formatCost(detail.cost)}</th>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </div>
  )
}
