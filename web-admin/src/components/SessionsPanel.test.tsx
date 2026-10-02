import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { SessionsPanel } from './SessionsPanel'
import type { SessionDetail, SessionSummary } from '../lib/api'

const cost = (total: number | null, unpriced = 0) => ({
  runs: 3,
  total_cost_usd: total,
  priced_runs: 3 - unpriced,
  unpriced_runs: unpriced,
  input_tokens: 30,
  output_tokens: 15,
})

const sessions: SessionSummary[] = [
  {
    session_id: 'a',
    owner_sub: 'sub-alice',
    owner_email: 'alice@x.com',
    owner_email_known: true,
    owner_display: 'alice@x.com',
    title: 'Alice logistics',
    target: null,
    status: 'complete',
    created_at: '2026-01-02',
    turn_count: 4,
    deleted: false,
    cost: cost(1.5),
    cost_error: false,
  },
  {
    session_id: 'b',
    owner_sub: 'sub-bob',
    owner_email: null,
    owner_email_known: false,
    owner_display: 'sub-bob',
    title: null,
    target: 'Bob retail',
    status: 'failed',
    created_at: '2026-01-03',
    turn_count: 2,
    deleted: true,
    cost: cost(null, 3),
    cost_error: false,
  },
]

const detail: SessionDetail = {
  ...sessions[0],
  geography: 'UK',
  problem: 'late deliveries',
  brief: { ready: true },
  failure_reason: null,
  transcript: [
    { role: 'user', content: 'hello there' },
    { role: 'assistant', content: 'which market?' },
  ],
  opportunities: [{ rank: 1, title: 'Opp One', pitch: 'pitch', rationale: null, evidence: null, model: 'm' }],
  cost: {
    ...cost(0.75, 1),
    rows: [
      { stage: 'qualifying', label: 'Qualifying turn 1', run_id: 'r0', agent_name: 'q', model: 'model-q', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: 0.5, priced: true },
      { stage: 'research', label: 'market', run_id: 'r1', agent_name: 'market', model: 'model-r', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: 0.25, priced: true },
      { stage: 'synthesis', label: 'Synthesis', run_id: 'r2', agent_name: 'syn', model: 'model-s', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: null, priced: false },
    ],
  },
}

function makeApi() {
  return {
    listSessions: vi.fn().mockResolvedValue({ sessions }),
    getSession: vi.fn().mockResolvedValue(detail),
  }
}

describe('SessionsPanel', () => {
  it('lists every user’s sessions with email, unknown-email fallback, deleted marker and cost', async () => {
    render(<SessionsPanel api={makeApi()} />)
    expect(await screen.findByText('alice@x.com')).toBeInTheDocument()
    expect(screen.getByText('sub-bob')).toBeInTheDocument()
    expect(screen.getByText(/email unknown/)).toBeInTheDocument()
    expect(screen.getByText('Deleted')).toBeInTheDocument()
    expect(screen.getByText('$1.5000')).toBeInTheDocument()
    // unpriced is flagged, never rendered as $0
    expect(screen.getByText('unpriced (3 unpriced runs)')).toBeInTheDocument()
    expect(screen.queryByText(/\$0\.0000/)).not.toBeInTheDocument()
  })

  it('re-queries with the chosen filters and sort', async () => {
    const api = makeApi()
    render(<SessionsPanel api={api} />)
    await screen.findByText('alice@x.com')
    fireEvent.change(screen.getByLabelText('User'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'failed' } })
    fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'cost' } })
    fireEvent.change(screen.getByLabelText('Order'), { target: { value: 'asc' } })
    await waitFor(() =>
      expect(api.listSessions).toHaveBeenLastCalledWith({
        user: 'alice',
        status: 'failed',
        sort: 'cost',
        order: 'asc',
      }),
    )
  })

  it('opens a session and shows transcript, opportunities and the cost breakdown', async () => {
    const api = makeApi()
    render(<SessionsPanel api={api} />)
    fireEvent.click(await screen.findByText('Alice logistics'))
    expect(await screen.findByText(/hello there/)).toBeInTheDocument()
    expect(screen.getByText(/which market\?/)).toBeInTheDocument()
    expect(screen.getByText('Opp One')).toBeInTheDocument()
    expect(api.getSession).toHaveBeenCalledWith('a')
    expect(screen.getByText('model-q')).toBeInTheDocument()
    expect(screen.getByText('model-r')).toBeInTheDocument()
    expect(screen.getByText('$0.5000')).toBeInTheDocument()
    // the unpriced synthesis row is flagged, and the total says so
    expect(screen.getAllByText('unpriced').length).toBeGreaterThan(0)
    expect(screen.getByText('$0.7500 (1 unpriced run)')).toBeInTheDocument()
  })

  it('shows an error when the list fails', async () => {
    const api = makeApi()
    api.listSessions.mockRejectedValue(new Error('boom'))
    render(<SessionsPanel api={api} />)
    expect(await screen.findByText(/Failed to load sessions: boom/)).toBeInTheDocument()
  })
})

describe('SessionsPanel — Pressure Test', () => {
  const ptSessions = [
    {
      ...sessions[0],
      session_id: 'p1',
      title: 'Alice pressure idea',
      seed_idea: 'an idea',
      status: 'complete',
    },
    {
      ...sessions[1],
      session_id: 'p2',
      title: null,
      target: null,
      seed_idea: 'Bob seed idea',
      status: 'gathering',
      deleted: true,
    },
  ]
  const ptDetail = {
    ...ptSessions[0],
    challenger_agent_key: 'challenger',
    transcript: [
      { role: 'user', content: 'my pitch' },
      { role: 'assistant', content: 'why now?' },
    ],
    report: { prd: { title: 'The PRD title' }, scorecard: { viability: 4 }, model: 'analyst-m' },
    cost: {
      ...cost(0.75, 1),
      rows: [
        { stage: 'chat', label: 'Challenger turn 1', run_id: 'c1', agent_name: 'c', model: 'model-c', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: 0.5, priced: true },
        { stage: 'chat', label: 'Challenger turn 2', run_id: 'c2', agent_name: 'c', model: 'model-c', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: 0.25, priced: true },
        { stage: 'analysis', label: 'Analyst run', run_id: 'a1', agent_name: 'a', model: 'model-a', status: 'completed', input_tokens: 10, output_tokens: 5, cost_usd: null, priced: false },
      ],
    },
  }
  function makePtApi() {
    return {
      listSessions: vi.fn(),
      getSession: vi.fn(),
      listPressureTestSessions: vi.fn().mockResolvedValue({ sessions: ptSessions }),
      getPressureTestSession: vi.fn().mockResolvedValue(ptDetail),
    }
  }

  it('lists pressure-test sessions from several users, with deleted marker and cost', async () => {
    const api = makePtApi()
    render(<SessionsPanel api={api} kind="pressure-test" />)
    expect(await screen.findByText('alice@x.com')).toBeInTheDocument()
    expect(screen.getByText('sub-bob')).toBeInTheDocument()
    expect(screen.getByText('Bob seed idea')).toBeInTheDocument()
    expect(screen.getByText('Deleted')).toBeInTheDocument()
    expect(screen.getByText('unpriced (3 unpriced runs)')).toBeInTheDocument()
    expect(api.listSessions).not.toHaveBeenCalled()
  })

  it('filters with pressure-test statuses', async () => {
    const api = makePtApi()
    render(<SessionsPanel api={api} kind="pressure-test" />)
    await screen.findByText('alice@x.com')
    expect(screen.getByRole('option', { name: 'gathering' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'researching' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'gathering' } })
    await waitFor(() =>
      expect(api.listPressureTestSessions).toHaveBeenLastCalledWith({
        user: '',
        status: 'gathering',
        sort: 'date',
        order: 'desc',
      }),
    )
  })

  it('opens to the transcript, report and cost breakdown', async () => {
    const api = makePtApi()
    render(<SessionsPanel api={api} kind="pressure-test" />)
    fireEvent.click(await screen.findByText('Alice pressure idea'))
    expect(await screen.findByText(/my pitch/)).toBeInTheDocument()
    expect(screen.getByText(/why now\?/)).toBeInTheDocument()
    expect(screen.getByText(/The PRD title/)).toBeInTheDocument()
    expect(screen.getByText(/viability/)).toBeInTheDocument()
    expect(api.getPressureTestSession).toHaveBeenCalledWith('p1')
    expect(screen.getByText('Analyst run')).toBeInTheDocument()
    expect(screen.getByText('model-a')).toBeInTheDocument()
    expect(screen.getByText('$0.7500 (1 unpriced run)')).toBeInTheDocument()
  })
})
