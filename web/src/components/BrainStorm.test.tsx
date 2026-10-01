import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

import { BrainStorm } from './BrainStorm'
import type { Api } from '../lib/api'

const state = {
  session_id: 's1',
  status: 'gathering',
  title: 't',
  target: 'clinics',
  geography: null,
  problem: null,
  turn_count: 1,
  max_turns: 8,
  created_at: '',
}

describe('BrainStorm', () => {
  it('requires intake, starts a session and converses', async () => {
    const api = {
      startBrainstorm: vi.fn().mockResolvedValue({ ...state, reply: 'Who pays?' }),
      sendBrainstormMessage: vi.fn().mockResolvedValue({ ...state, turn_count: 2, reply: 'Thanks' }),
    } as unknown as Api
    render(<BrainStorm api={api} />)

    const start = screen.getByRole('button', { name: /Start brain-storm/ })
    expect(start).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Target company or industry'), { target: { value: 'clinics' } })
    fireEvent.click(start)

    await waitFor(() => expect(screen.getByText('Who pays?')).toBeInTheDocument())
    expect(api.startBrainstorm).toHaveBeenCalledWith({ target: 'clinics' })

    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'The owner' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByText('Thanks')).toBeInTheDocument())
    expect(api.sendBrainstormMessage).toHaveBeenCalledWith('s1', 'The owner')
  })
})

describe('BrainStorm research flow', () => {
  it('finalises, polls to completion, lists opportunities and hands off', async () => {
    const opp = { id: 'o1', rank: 1, title: 'Slot filler', pitch: 'Fill no-shows', rationale: 'why', evidence: [] }
    const api = {
      startBrainstorm: vi
        .fn()
        .mockResolvedValue({ ...state, status: 'qualifying', ready: true, reply: 'Q?' }),
      finaliseBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'researching' }),
      getBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'complete' }),
      getBrainstormOpportunities: vi.fn().mockResolvedValue({ opportunities: [opp] }),
    } as unknown as Api
    const onPressureTest = vi.fn()
    render(<BrainStorm api={api} onPressureTest={onPressureTest} />)
    fireEvent.change(screen.getByLabelText('Target company or industry'), { target: { value: 'clinics' } })
    fireEvent.click(screen.getByRole('button', { name: /Start brain-storm/ }))
    await waitFor(() => expect(screen.getByText('Q?')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Run research' }))
    await waitFor(() => expect(screen.getByText(/Researching/)).toBeInTheDocument())
    expect(api.finaliseBrainstorm).toHaveBeenCalledWith('s1')

    await waitFor(() => expect(screen.getByText('Slot filler')).toBeInTheDocument(), { timeout: 6000 })
    fireEvent.click(screen.getByRole('button', { name: 'Pressure-test this' }))
    expect(onPressureTest).toHaveBeenCalledWith('Slot filler: Fill no-shows')
  }, 10000)
})


describe('BrainStorm "Run research" call to action', () => {
  async function startWith(extra: Record<string, unknown>) {
    const api = {
      startBrainstorm: vi
        .fn()
        .mockResolvedValue({ ...state, status: 'qualifying', reply: 'Q?', ...extra }),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.change(screen.getByLabelText('Target company or industry'), { target: { value: 'clinics' } })
    fireEvent.click(screen.getByRole('button', { name: /Start brain-storm/ }))
    await waitFor(() => expect(screen.getByText('Q?')).toBeInTheDocument())
  }

  it('is hidden before the brief is ready', async () => {
    await startWith({ ready: false, at_ceiling: false })
    expect(screen.queryByRole('button', { name: 'Run research' })).toBeNull()
    expect(screen.queryByText('Generate opportunities')).toBeNull()
  })

  it('is shown with the brief summary once ready', async () => {
    await startWith({
      ready: true,
      brief: { ready: true, summary: 'Clinics losing money to no-shows', business_problem: 'No-shows' },
    })
    expect(screen.getByRole('button', { name: 'Run research' })).toBeInTheDocument()
    expect(screen.getByText('Clinics losing money to no-shows')).toBeInTheDocument()
    expect(screen.getByText('No-shows')).toBeInTheDocument()
  })

  it('is shown with the gaps at the ceiling even when not ready', async () => {
    await startWith({
      ready: false,
      at_ceiling: true,
      turn_count: 8,
      max_turns: 8,
      gaps: ['Budget unknown'],
    })
    expect(screen.getByRole('button', { name: 'Run research' })).toBeInTheDocument()
    expect(screen.getByText('Budget unknown')).toBeInTheDocument()
  })
})

describe('BrainStorm early research option', () => {
  async function startWith(extra: Record<string, unknown>) {
    const api = {
      startBrainstorm: vi
        .fn()
        .mockResolvedValue({ ...state, status: 'qualifying', reply: 'Q?', early_research_turn: 3, ...extra }),
      finaliseBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'researching' }),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.change(screen.getByLabelText('Target company or industry'), { target: { value: 'clinics' } })
    fireEvent.click(screen.getByRole('button', { name: /Start brain-storm/ }))
    await waitFor(() => expect(screen.getByText('Q?')).toBeInTheDocument())
    return api
  }
  const early = /Brainstorm with what I've given so far/

  it('is hidden at turns 1 and 2', async () => {
    await startWith({ turn_count: 2, gaps: ['Budget'] })
    expect(screen.queryByRole('button', { name: early })).toBeNull()
  })

  it('shows at turn 3 with gaps and calls finalise', async () => {
    const api = await startWith({ turn_count: 3, gaps: ['Budget unknown'] })
    expect(screen.getByText('Budget unknown')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: early }))
    await waitFor(() => expect(api.finaliseBrainstorm).toHaveBeenCalledWith('s1'))
  })

  it('is hidden once the full panel shows', async () => {
    await startWith({ turn_count: 4, ready: true })
    expect(screen.queryByRole('button', { name: early })).toBeNull()
    expect(screen.getByRole('button', { name: 'Run research' })).toBeInTheDocument()
  })
})
