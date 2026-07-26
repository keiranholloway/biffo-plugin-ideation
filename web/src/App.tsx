import { useEffect, useState } from 'react'

import { getCurrentSession } from './lib/auth'
import { ApiError, createApi, type Api, type Report, type SessionState, type SessionSummary } from './lib/api'
import { ReportCard } from './components/ReportCard'
import { Sidebar } from './components/Sidebar'

interface Msg {
  role: 'you' | 'ideation'
  text: string
}

type View =
  | { kind: 'new' }
  | { kind: 'live'; sessionId: string }
  | { kind: 'report'; sessionId: string }

function errorText(e: unknown): string {
  if (e instanceof ApiError) return `${e.status}: ${e.message}`
  return e instanceof Error ? e.message : String(e)
}

export default function App() {
  const [api, setApi] = useState<Api | null>(null)
  const [ready, setReady] = useState(false)
  const [view, setView] = useState<View>({ kind: 'new' })
  const [seed, setSeed] = useState('')
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submittedIdea, setSubmittedIdea] = useState<string | null>(null)

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

  // Fetch the session list once ready.
  useEffect(() => {
    if (!api) return
    void refreshSessions()
    void api.getSubmittedIdea().then((r) => setSubmittedIdea(r.idea)).catch(() => {})
  }, [api])

  async function refreshSessions() {
    if (!api) return
    try {
      const list = await api.listSessions()
      setSessions(list)
    } catch (e) {
      setError(errorText(e))
    }
  }

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
          setView({ kind: 'report', sessionId: session.session_id })
          await refreshSessions()
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

  function handleNewIdea() {
    setView({ kind: 'new' })
    setSeed('')
    setSession(null)
    setMessages([])
    setReport(null)
    setInput('')
  }

  async function handleSelectSession(clicked: SessionSummary) {
    // Stop any polling tied to a previously-viewed live session (its effect
    // depends on `session`, so clearing it unmounts that poll) and clear a
    // stale report from whatever was viewed before — both views below set
    // exactly the state they need, no leftovers from the prior selection.
    setSession(null)
    setReport(null)
    setMessages([])

    if (clicked.status === 'complete') {
      setView({ kind: 'report', sessionId: clicked.session_id })
      try {
        const r = await api!.getReport(clicked.session_id)
        if (r.report) {
          setReport(r.report)
        }
      } catch (e) {
        setError(errorText(e))
      }
    } else if (clicked.status === 'gathering' || clicked.status === 'analysing') {
      setView({ kind: 'live', sessionId: clicked.session_id })
      try {
        const sessionState = await api!.getSession(clicked.session_id)
        setSession(sessionState)
        setMessages([])
      } catch (e) {
        setError(errorText(e))
      }
    }
  }

  async function start() {
    if (!api || !seed.trim()) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.startSession(seed.trim())
      setView({ kind: 'live', sessionId: r.session_id })
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

  async function handleDeleteSession(clicked: SessionSummary) {
    if (!api) return
    if (!window.confirm(`Delete "${clicked.title}"? This can't be undone from here.`)) return
    try {
      await api.deleteSession(clicked.session_id)
      const activeId = view.kind === 'live' || view.kind === 'report' ? view.sessionId : null
      if (activeId === clicked.session_id) {
        handleNewIdea()
      }
      await refreshSessions()
    } catch (e) {
      setError(errorText(e))
    }
  }

  if (!ready) return <main className="ide">Loading…</main>

  const activeSessionId = view.kind === 'live' || view.kind === 'report' ? view.sessionId : null

  return (
    <div className="ide-layout">
      <Sidebar sessions={sessions} activeId={activeSessionId} onSelect={handleSelectSession} onNewIdea={handleNewIdea} onDelete={handleDeleteSession} />
      <main className="ide">
        <h1>Ideation Engine</h1>
        {error && <div className="ide-error">{error}</div>}

        {view.kind === 'new' && !session && (
          <section className="ide-seed">
            <p>Describe your idea. I&apos;ll pressure-test it over a few questions, then produce a PRD and a viability scorecard.</p>
            {submittedIdea && (
              <button
                type="button"
                className="ide-use-original"
                onClick={() => setSeed(submittedIdea)}
              >
                Use my original idea
              </button>
            )}
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

        {view.kind === 'live' && session && !report && (
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

        {view.kind === 'report' && report && <ReportCard report={report} />}
      </main>
    </div>
  )
}
