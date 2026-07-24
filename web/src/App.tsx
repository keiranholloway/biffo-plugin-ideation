import { useEffect, useState } from 'react'

import { getCurrentSession } from './lib/auth'
import { ApiError, createApi, type Api, type Report, type SessionState } from './lib/api'

interface Msg {
  role: 'you' | 'ideation'
  text: string
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return `${e.status}: ${e.message}`
  return e instanceof Error ? e.message : String(e)
}

export default function App() {
  const [api, setApi] = useState<Api | null>(null)
  const [ready, setReady] = useState(false)
  const [seed, setSeed] = useState('')
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Read the shared portal session; no session → redirect to the portal login.
  useEffect(() => {
    void getCurrentSession().then((s) => {
      if (!s) {
        window.location.href = `/login?return_to=${encodeURIComponent('/ideation/')}`
        return
      }
      setApi(createApi(() => s.getIdToken().getJwtToken()))
      setReady(true)
    })
  }, [])

  // While analysing, poll for the report (it is materialised on the poll).
  useEffect(() => {
    if (!api || !session || session.status !== 'analysing') return
    let stopped = false
    const tick = async () => {
      try {
        const r = await api.getReport(session.session_id)
        if (stopped) return
        if (r.report) {
          setReport(r.report)
          setSession((s) => (s ? { ...s, status: 'complete' } : s))
          return
        }
        window.setTimeout(() => void tick(), 3000)
      } catch (e) {
        if (!stopped) setError(errorText(e))
      }
    }
    const t = window.setTimeout(() => void tick(), 2000)
    return () => {
      stopped = true
      window.clearTimeout(t)
    }
  }, [api, session])

  async function start() {
    if (!api || !seed.trim()) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.startSession(seed.trim())
      setSession(r)
      setMessages([
        { role: 'you', text: seed.trim() },
        { role: 'ideation', text: r.reply },
      ])
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!api || !session || !input.trim()) return
    const text = input.trim()
    setInput('')
    setBusy(true)
    setError(null)
    setMessages((m) => [...m, { role: 'you', text }])
    try {
      const r = await api.sendMessage(session.session_id, text)
      setSession(r)
      setMessages((m) => [...m, { role: 'ideation', text: r.reply }])
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function finalise() {
    if (!api || !session) return
    setBusy(true)
    setError(null)
    try {
      await api.finalise(session.session_id)
      setSession((s) => (s ? { ...s, status: 'analysing' } : s))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  if (!ready) return <main className="ide">Loading…</main>

  return (
    <main className="ide">
      <h1>Ideation Engine</h1>
      {error && <div className="ide-error">{error}</div>}

      {!session && (
        <section className="ide-seed">
          <p>Describe your idea. I&apos;ll pressure-test it over a few questions, then produce a PRD and a viability scorecard.</p>
          <textarea
            aria-label="Your idea"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="e.g. a scheduling assistant for independent coaches…"
            rows={4}
          />
          <button onClick={() => void start()} disabled={busy || !seed.trim()}>
            {busy ? 'Starting…' : 'Start'}
          </button>
        </section>
      )}

      {session && !report && (
        <section className="ide-chat">
          <ul className="ide-messages">
            {messages.map((m, i) => (
              <li key={i} className={`ide-msg ide-msg--${m.role}`}>
                <span className="ide-who">{m.role === 'you' ? 'You' : 'Ideation'}</span>
                <p>{m.text}</p>
              </li>
            ))}
          </ul>

          {session.status === 'gathering' && (
            <div className="ide-compose">
              <input
                aria-label="Your answer"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void send()}
                placeholder="Answer…"
                disabled={busy || session.turn_count >= session.max_turns}
              />
              <button onClick={() => void send()} disabled={busy || !input.trim()}>
                Send
              </button>
              <button
                className="ide-finalise"
                onClick={() => void finalise()}
                disabled={busy || !session.can_finalise}
                title={session.can_finalise ? '' : `Answer a few more (min ${session.min_turns})`}
              >
                Generate review
              </button>
              <span className="ide-turns">
                turn {session.turn_count} / {session.max_turns}
              </span>
            </div>
          )}

          {session.status === 'analysing' && (
            <p className="ide-analysing">Analysing your idea — researching the landscape and scoring it…</p>
          )}
        </section>
      )}

      {report && <ReportView report={report} />}
    </main>
  )
}

function Axis({ label, axis }: { label: string; axis: { score: number; rationale: string } }) {
  return (
    <div className="ide-axis">
      <div className="ide-axis-head">
        <strong>{label}</strong>
        <span className="ide-score">{axis.score}/5</span>
      </div>
      <p>{axis.rationale}</p>
    </div>
  )
}

function ReportView({ report }: { report: Report }) {
  const { prd, scorecard } = report
  return (
    <section className="ide-report">
      <h2>Viability scorecard</h2>
      <p className="ide-summary">{scorecard.summary}</p>
      <div className="ide-axes">
        <Axis label="Viability" axis={scorecard.viability} />
        <Axis label="Complexity" axis={scorecard.complexity} />
        <Axis label="Economic moat" axis={scorecard.economic_moat} />
        <Axis label="Market fit" axis={scorecard.market_fit} />
      </div>
      <p>
        <strong>Build vs buy:</strong> {scorecard.build_vs_buy}
      </p>
      {scorecard.competitors.length > 0 && (
        <>
          <h3>Competitors</h3>
          <ul>
            {scorecard.competitors.map((c, i) => (
              <li key={i}>
                <strong>{c.name}</strong>
                {c.url ? ` (${c.url})` : ''} — {c.note}
              </li>
            ))}
          </ul>
        </>
      )}

      <h2>High-level PRD</h2>
      <p>
        <strong>Problem:</strong> {prd.problem}
      </p>
      <PrdList label="Target users" items={prd.target_users} />
      <PrdList label="Workflows" items={prd.workflows} />
      <PrdList label="Data entities" items={prd.data_entities} />
      <PrdList label="Capabilities" items={prd.capabilities} />
      <PrdList label="Out of scope" items={prd.out_of_scope} />
    </section>
  )
}

function PrdList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <strong>{label}:</strong>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  )
}
