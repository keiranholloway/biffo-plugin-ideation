import { useEffect, useState } from 'react'

import { ApiError, type Api, type BrainstormOpportunity, type BrainstormState } from '../lib/api'

interface Msg {
  role: 'you' | 'ideation'
  text: string
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return `${e.status}: ${e.message}`
  return e instanceof Error ? e.message : String(e)
}

// Server-side max lengths of StartBrainstormRequest.
const MAX_TARGET = 4_000
const MAX_GEOGRAPHY = 4_000
const MAX_PROBLEM = 8_000

const POLL_MS = 3000

export function BrainStorm({
  api,
  onPressureTest,
}: {
  api: Api
  onPressureTest?: (seed: string) => void
}) {
  const [target, setTarget] = useState('')
  const [geography, setGeography] = useState('')
  const [problem, setProblem] = useState('')
  const [session, setSession] = useState<BrainstormState | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [opportunities, setOpportunities] = useState<BrainstormOpportunity[]>([])

  const isChatting =
    !!session && !['researching', 'synthesising', 'complete', 'failed'].includes(session.status)

  const canStart = !!(target.trim() || geography.trim() || problem.trim())

  async function start() {
    if (!canStart) return
    setBusy(true)
    setError(null)
    const intake = {
      ...(target.trim() ? { target: target.trim() } : {}),
      ...(geography.trim() ? { geography: geography.trim() } : {}),
      ...(problem.trim() ? { problem: problem.trim() } : {}),
    }
    try {
      const r = await api.startBrainstorm(intake)
      const opening = [
        intake.target && `Target: ${intake.target}`,
        intake.geography && `Geography: ${intake.geography}`,
        intake.problem && `Problem area: ${intake.problem}`,
      ]
        .filter(Boolean)
        .join('\n')
      setSession(r)
      setMessages([
        { role: 'you', text: opening },
        { role: 'ideation', text: r.reply },
      ])
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!session || !input.trim()) return
    const text = input.trim()
    setInput('')
    setBusy(true)
    setError(null)
    setMessages((m) => [...m, { role: 'you', text }])
    try {
      const r = await api.sendBrainstormMessage(session.session_id, text)
      setSession(r)
      setMessages((m) => [...m, { role: 'ideation', text: r.reply }])
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function generate() {
    if (!session) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.finaliseBrainstorm(session.session_id)
      setSession((s) => (s ? { ...s, status: r.status, failure_reason: r.failure_reason } : s))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  // While researching or synthesising, poll the session; it advances server-side
  // on each read. On completion, fetch the ranked opportunities.
  const sessionId = session?.session_id
  const status = session?.status
  useEffect(() => {
    if (!sessionId || (status !== 'researching' && status !== 'synthesising')) return
    let stopped = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const r = await api.getBrainstorm(sessionId)
        if (stopped) return
        if (r.status === 'complete') {
          const o = await api.getBrainstormOpportunities(sessionId)
          if (stopped) return
          setOpportunities(o.opportunities)
        }
        setSession((s) => (s ? { ...s, status: r.status, failure_reason: r.failure_reason } : s))
        if (r.status === 'researching' || r.status === 'synthesising') {
          timer = window.setTimeout(() => void tick(), POLL_MS)
        }
      } catch (e) {
        if (!stopped) setError(errorText(e))
      }
    }
    timer = window.setTimeout(() => void tick(), POLL_MS)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [api, sessionId, status])

  function reset() {
    setSession(null)
    setMessages([])
    setInput('')
    setOpportunities([])
    setError(null)
  }

  return (
    <section className="ide-brainstorm">
      {error && <div className="ide-error">{error}</div>}

      {!session && (
        <div className="ide-intake">
          <p>Tell me where to look. Fill in at least one of the fields below and I&apos;ll ask a few qualifying questions.</p>
          <label>
            Target company / industry
            <input
              aria-label="Target company or industry"
              value={target}
              maxLength={MAX_TARGET}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="e.g. independent physiotherapy clinics"
            />
          </label>
          <label>
            Geographic market
            <input
              aria-label="Geographic market"
              value={geography}
              maxLength={MAX_GEOGRAPHY}
              onChange={(e) => setGeography(e.target.value)}
              placeholder="e.g. UK and Ireland"
            />
          </label>
          <label>
            Problem / idea
            <textarea
              aria-label="Problem or idea"
              value={problem}
              maxLength={MAX_PROBLEM}
              onChange={(e) => setProblem(e.target.value)}
              rows={4}
              placeholder="e.g. no-shows are costing them revenue"
            />
          </label>
          <button onClick={() => void start()} disabled={busy || !canStart}>
            {busy ? 'Starting…' : 'Start brain-storm'}
          </button>
        </div>
      )}

      {session && (status === 'researching' || status === 'synthesising') && (
        <div className="ide-progress" role="status">
          <p>
            {status === 'researching'
              ? 'Researching: six agents are investigating your brief in parallel…'
              : 'Synthesising: ranking the opportunities…'}
          </p>
        </div>
      )}

      {session && status === 'failed' && (
        <div className="ide-failed">
          <p>{session.failure_reason ?? 'The brain-storm failed.'}</p>
          <button type="button" onClick={reset}>
            New brain-storm
          </button>
        </div>
      )}

      {session && status === 'complete' && (
        <div className="ide-opportunities">
          <h2>Ranked opportunities</h2>
          <ol>
            {opportunities.map((o) => (
              <li key={o.id} className="ide-opportunity">
                <h3>{o.title}</h3>
                <p>{o.pitch}</p>
                {o.rationale && <p className="ide-rationale">{o.rationale}</p>}
                {o.evidence.length > 0 && (
                  <ul className="ide-evidence">
                    {o.evidence.map((e, i) => (
                      <li key={i}>
                        <a href={e.url} target="_blank" rel="noopener noreferrer">
                          {e.url}
                        </a>
                        {e.note ? ` — ${e.note}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
                {onPressureTest && (
                  <button type="button" onClick={() => onPressureTest(`${o.title}: ${o.pitch}`)}>
                    Pressure-test this
                  </button>
                )}
              </li>
            ))}
          </ol>
          <button type="button" onClick={reset}>
            New brain-storm
          </button>
        </div>
      )}

      {session && isChatting && (
        <div className="ide-chat">
          <ul className="ide-messages">
            {messages.map((m, i) => (
              <li key={i} className={`ide-msg ide-msg--${m.role}`}>
                <span className="ide-who">{m.role === 'you' ? 'You' : 'Ideation'}</span>
                <p>{m.text}</p>
              </li>
            ))}
          </ul>
          <div className="ide-compose">
            <input
              aria-label="Your reply"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void send()}
              placeholder="Answer…"
              disabled={busy || session.turn_count >= session.max_turns}
            />
            <button onClick={() => void send()} disabled={busy || !input.trim()}>
              Send
            </button>
            <button type="button" onClick={() => void generate()} disabled={busy}>
              Generate opportunities
            </button>
            <button type="button" onClick={reset} disabled={busy}>
              New brain-storm
            </button>
            <span className="ide-turns">
              turn {session.turn_count} / {session.max_turns}
            </span>
          </div>
        </div>
      )}
    </section>
  )
}
