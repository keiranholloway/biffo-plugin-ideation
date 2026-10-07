import { useEffect, useState } from 'react'

import type { ReactNode } from 'react'

import { ChatComposer } from './ChatComposer'
import { Sidebar } from './Sidebar'
import {
  ApiError,
  type Api,
  type BrainstormBrief,
  type BrainstormOpportunity,
  type BrainstormState,
  type TranscriptMessage,
} from '../lib/api'

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

function toMsgs(turns: TranscriptMessage[]): Msg[] {
  return turns.map((t) => ({ role: t.role === 'user' ? 'you' : 'ideation', text: t.content }))
}

function Transcript({ messages }: { messages: Msg[] }) {
  return (
    <ul className="ide-messages">
      {messages.map((m, i) => (
        <li key={i} className={`ide-msg ide-msg--${m.role}`}>
          <span className="ide-who">{m.role === 'you' ? 'You' : 'Ideation'}</span>
          <p>{m.text}</p>
        </li>
      ))}
    </ul>
  )
}

function BriefDetails({ brief }: { brief?: BrainstormBrief | null }) {
  if (!brief) return null
  const w = brief.what_the_business_wants ?? {}
  const z = brief.size_and_shape ?? {}
  const rows: [string, string | undefined][] = [
    ['Goals', w.goals],
    ['Capabilities and assets', w.capabilities_and_assets],
    ['Target customer', w.target_customer],
    ['Business problem', brief.business_problem],
    ['Who and how many', z.who_and_how_many],
    ['Cost and frequency', z.cost_and_frequency],
    ['Current workarounds', z.current_workarounds],
    ['Boundaries and constraints', z.boundaries_and_constraints],
  ]
  const shown = rows.filter(([, v]) => v && v.trim())
  if (shown.length === 0) return null
  return (
    <dl className="ide-brief-details">
      {shown.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function historyTitle(s: BrainstormState): string {
  return s.title || s.target || s.problem || s.geography || 'Untitled brain-storm'
}

export function BrainStorm({
  api,
  onPressureTest,
  header,
}: {
  api: Api
  onPressureTest?: (seed: string) => void
  /** Rendered at the top of the main pane (title and tab bar), beside the history column. */
  header?: ReactNode
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
  const [history, setHistory] = useState<BrainstormState[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyFailed, setHistoryFailed] = useState(false)

  const isChatting =
    !!session && !['researching', 'synthesising', 'complete', 'failed'].includes(session.status)

  const atCeiling = !!session && (session.at_ceiling ?? session.turn_count >= session.max_turns)
  const showRun = !!session && (!!session.ready || atCeiling)
  const gaps = session?.gaps ?? session?.brief?.gaps ?? []
  const showEarly =
    !!session &&
    !showRun &&
    session.status === 'qualifying' &&
    session.early_research_turn !== undefined &&
    session.turn_count >= session.early_research_turn

  const canStart = !!(target.trim() || geography.trim() || problem.trim())

  async function loadHistory() {
    try {
      const list = await api.listBrainstorms()
      setHistory(Array.isArray(list) ? list : [])
      setHistoryFailed(false)
    } catch {
      setHistoryFailed(true)
    } finally {
      setHistoryLoaded(true)
    }
  }

  // The history column stays visible; load it on mount, and refresh when a
  // new session first appears (start) or we return to the intake form.
  const sessionIdForList = session?.session_id ?? null
  useEffect(() => {
    void loadHistory()
  }, [api, sessionIdForList])

  async function open(summary: BrainstormState) {
    setBusy(true)
    setError(null)
    try {
      // A fresh read: it also advances a researching/synthesising session.
      const state = await api.getBrainstorm(summary.session_id)
      const t = await api.getBrainstormMessages(summary.session_id)
      let opps: BrainstormOpportunity[] = []
      if (state.status === 'complete') {
        opps = (await api.getBrainstormOpportunities(summary.session_id)).opportunities
      }
      setMessages(toMsgs(t.messages))
      setOpportunities(opps)
      setInput('')
      setSession(state)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove(summary: BrainstormState) {
    if (!window.confirm(`Delete "${historyTitle(summary)}"? This can't be undone from here.`)) return
    try {
      await api.deleteBrainstorm(summary.session_id)
      if (session?.session_id === summary.session_id) reset()
      await loadHistory()
    } catch (e) {
      setError(errorText(e))
    }
  }

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
    <div className="ide-layout">
      <Sidebar
        sessions={history}
        activeId={session?.session_id ?? null}
        onSelect={(h) => void open(h)}
        onNewIdea={reset}
        onDelete={(h) => void remove(h)}
        loadFailed={historyFailed}
        loaded={historyLoaded}
        getId={(h) => h.session_id}
        getTitle={historyTitle}
        getStatus={(h) => h.status}
        getDate={(h) => h.created_at}
        newLabel="New brain-storm"
        loadingText="Loading your past brain-storms…"
        emptyText="No past brain-storms yet"
        failedText="Couldn&apos;t load your past brain-storms"
        deleteLabel={(h) => `Delete ${historyTitle(h)}`}
        disabled={busy}
      />
      <main className="ide">
        {header}
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

      {session && !isChatting && (
        <div className="ide-brief ide-brief--readonly">
          {session.brief?.summary && <p>{session.brief.summary}</p>}
          <BriefDetails brief={session.brief} />
        </div>
      )}

      {session && !isChatting && messages.length > 0 && <Transcript messages={messages} />}

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
          <Transcript messages={messages} />
          {showRun && (
            <div className="ide-brief" role="region" aria-label="Brief summary">
              <h2>{session.ready ? 'Your brief is ready' : 'Conversation limit reached'}</h2>
              {session.brief?.summary && <p>{session.brief.summary}</p>}
              <BriefDetails brief={session.brief} />
              {!session.ready && (
                <p>Some things are still unclear. You can run research anyway, knowing the gaps:</p>
              )}
              {gaps.length > 0 && (
                <ul className="ide-gaps" aria-label="Gaps">
                  {gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              )}
              <button type="button" className="ide-cta" onClick={() => void generate()} disabled={busy}>
                Run research
              </button>
            </div>
          )}
          {showEarly && (
            <div className="ide-early" role="region" aria-label="Early research">
              {gaps.length > 0 && (
                <>
                  <p>Research will lack these details:</p>
                  <ul className="ide-gaps" aria-label="Current gaps">
                    {gaps.map((g, i) => (
                      <li key={i}>{g}</li>
                    ))}
                  </ul>
                </>
              )}
              <button type="button" onClick={() => void generate()} disabled={busy}>
                Brainstorm with what I've given so far
              </button>
            </div>
          )}
          <ChatComposer
            label="Your reply"
            value={input}
            onChange={setInput}
            onSend={() => void send()}
            busy={busy}
            capped={session.turn_count >= session.max_turns}
          >
            <button type="button" onClick={reset} disabled={busy}>
              New brain-storm
            </button>
            <span className="ide-turns">
              turn {session.turn_count} / {session.max_turns}
            </span>
          </ChatComposer>
        </div>
      )}
    </section>
      </main>
    </div>
  )
}
