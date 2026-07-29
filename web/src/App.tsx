import { useEffect, useState } from 'react'

import { getCurrentSession, getFreshIdToken } from './lib/auth'
import { ApiError, createApi, type Agent, type Api, type Report, type SessionState, type SessionSummary } from './lib/api'
import { isFounder, REQUIRED_GROUP } from './lib/roles'
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

// Matches StartSessionRequest.seed_idea's max_length server-side, so an
// over-long deep-link is trimmed in the box the founder can still edit
// rather than 422-ing when they hit Start.
const MAX_SEED_LENGTH = 16_000

// Idea Scout deep-links a candidate here as ?seed=… so the founder can
// pressure-test it. Ordinary untrusted text: it only ever becomes the value
// of a controlled input, and it is never auto-submitted.
function readSeedParam(): string {
  if (typeof window === 'undefined') return ''
  const seed = new URLSearchParams(window.location.search).get('seed')
  return seed ? seed.slice(0, MAX_SEED_LENGTH) : ''
}

export default function App() {
  const [api, setApi] = useState<Api | null>(null)
  const [ready, setReady] = useState(false)
  // Signed in, but not in the manifest's declared group. Distinct from "signed
  // out" (which redirects to the portal login) — re-authenticating would not
  // help, so say so instead of bouncing them round a loop.
  const [notPermitted, setNotPermitted] = useState(false)
  const [view, setView] = useState<View>({ kind: 'new' })
  // Lazy initialiser: read once, at mount. After this the box belongs to the
  // founder — editing or clearing it is never overwritten by the param.
  const [seed, setSeed] = useState(readSeedParam)
  const [session, setSession] = useState<SessionState | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [reportTitle, setReportTitle] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  // "We could not load your runs" is a different fact from "you have no runs",
  // and the sidebar must not tell the second story when the first is true — an
  // empty list that is really a failed load reads as data loss (#69).
  const [sessionsFailed, setSessionsFailed] = useState(false)
  const [sessionsLoaded, setSessionsLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submittedIdea, setSubmittedIdea] = useState<string | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [agentKey, setAgentKey] = useState<string>('')

  // Read the shared portal session; no session → redirect to the portal login.
  // A session that is not in the declared group never gets an API client at all
  // — the client-side half of `user_frontend.required_group` (ADR-0018 §2). The
  // server enforces the same group independently (see lib/roles.ts); this only
  // saves a non-founder from a UI where every action returns 403.
  useEffect(() => {
    void getCurrentSession().then((s) => {
      if (!s) {
        window.location.href = `/login?return_to=${encodeURIComponent('/ideation/')}`
        return
      }
      if (!isFounder(s)) {
        setNotPermitted(true)
        setReady(true)
        return
      }
      // The client resolves a token per request rather than closing over `s`.
      // `s` is an immutable snapshot whose ID token stops working the moment it
      // expires — capturing it here made every call 401 for the rest of the
      // page's life, with no recovery short of a reload (#69).
      setApi(createApi(getFreshIdToken))
      setReady(true)
    })
  }, [])

  // Drop ?seed= from the address bar once it has been read, so a refresh
  // mid-edit doesn't re-prefill over the founder's changes.
  useEffect(() => {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('seed')) return
    url.searchParams.delete('seed')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])

  // Fetch the session list once ready.
  useEffect(() => {
    if (!api) return
    void refreshSessions()
    void api.getSubmittedIdea().then((r) => setSubmittedIdea(r.idea)).catch(() => {})
    void api.getAgents().then(setAgents).catch(() => {})
  }, [api])

  async function refreshSessions() {
    if (!api) return
    try {
      const list = await api.listSessions()
      setSessions(list)
      setSessionsFailed(false)
    } catch (e) {
      setSessionsFailed(true)
      setError(errorText(e))
    } finally {
      // Settled either way — the sidebar may now speak about an empty list.
      setSessionsLoaded(true)
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
          setReportTitle(r.title)
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
    setReportTitle(null)
    setInput('')
    setAgentKey('')
  }

  async function handleSelectSession(clicked: SessionSummary) {
    // Stop any polling tied to a previously-viewed live session (its effect
    // depends on `session`, so clearing it unmounts that poll) and clear a
    // stale report from whatever was viewed before — both views below set
    // exactly the state they need, no leftovers from the prior selection.
    setSession(null)
    setReport(null)
    setReportTitle(null)
    setMessages([])

    if (clicked.status === 'complete') {
      setView({ kind: 'report', sessionId: clicked.session_id })
      try {
        const r = await api!.getReport(clicked.session_id)
        if (r.report) {
          setReport(r.report)
          setReportTitle(r.title)
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
      const r = await api.startSession(seed.trim(), agentKey || null)
      setView({ kind: 'live', sessionId: r.session_id })
      setSession(r)
      setMessages([
        { role: 'you', text: seed.trim() },
        { role: 'ideation', text: r.reply },
      ])
      // The row exists now, so the nav must stop showing the list as it was at
      // mount. Before this, the only refresh after mount was the one that fires
      // when a report materialises — so a run that was never finalised, or whose
      // report poll errored out, stayed invisible in the sidebar for the whole
      // life of the page while sitting in the database (#69).
      void refreshSessions()
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

  if (notPermitted) {
    return (
      <main className="ide ide-not-permitted">
        <h1>Ideation Engine</h1>
        <p>
          This area is available to members of the <code>{REQUIRED_GROUP}</code> group only.
        </p>
        <p>
          Your account is signed in but not in that group, so the Ideation Engine will not load.
          Ask an administrator if you think that is wrong.
        </p>
      </main>
    )
  }

  const activeSessionId = view.kind === 'live' || view.kind === 'report' ? view.sessionId : null

  return (
    <div className="ide-layout">
      <Sidebar sessions={sessions} activeId={activeSessionId} onSelect={handleSelectSession} onNewIdea={handleNewIdea} onDelete={handleDeleteSession} loadFailed={sessionsFailed} loaded={sessionsLoaded} />
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
            {agents.length > 1 && (
              <label className="ide-agent-picker">
                Challenger persona
                <select
                  aria-label="Challenger persona"
                  value={agentKey}
                  onChange={(e) => setAgentKey(e.target.value)}
                >
                  <option value="">Default</option>
                  {agents.map((a) => (
                    <option key={a.agent_key} value={a.agent_key}>
                      {a.agent_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
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

        {view.kind === 'report' && report && <ReportCard report={report} title={reportTitle ?? undefined} />}
      </main>
    </div>
  )
}
