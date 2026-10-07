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

describe('BrainStorm history', () => {
  const past = [
    { ...state, session_id: 'a', status: 'qualifying', title: 'Clinics', created_at: '2026-10-01T10:00:00Z' },
    { ...state, session_id: 'b', status: 'complete', title: 'Vets', created_at: '2026-09-01T10:00:00Z' },
  ]

  it('lists past brain-storms from the API', async () => {
    const api = { listBrainstorms: vi.fn().mockResolvedValue(past) } as unknown as Api
    render(<BrainStorm api={api} />)
    await waitFor(() => expect(screen.getByText('Clinics')).toBeInTheDocument())
    expect(screen.getByText('Vets')).toBeInTheDocument()
    expect(screen.getByText('qualifying')).toBeInTheDocument()
  })

  it('reopens a qualifying session with its transcript and lets the next message send', async () => {
    const api = {
      listBrainstorms: vi.fn().mockResolvedValue(past),
      getBrainstorm: vi.fn().mockResolvedValue({ ...past[0], turn_count: 2 }),
      getBrainstormMessages: vi.fn().mockResolvedValue({
        messages: [
          { role: 'user', content: 'Target: clinics' },
          { role: 'assistant', content: 'Who pays?' },
        ],
      }),
      sendBrainstormMessage: vi.fn().mockResolvedValue({ ...past[0], turn_count: 3, reply: 'Got it' }),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.click(await screen.findByText('Clinics'))
    await waitFor(() => expect(screen.getByText('Who pays?')).toBeInTheDocument())
    expect(screen.getByText('Target: clinics')).toBeInTheDocument()
    expect(screen.getByText(/turn 2 \/ 8/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Your reply'), { target: { value: 'The owner' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByText('Got it')).toBeInTheDocument())
    expect(api.sendBrainstormMessage).toHaveBeenCalledWith('a', 'The owner')
  })

  it('reopens a complete session with brief, transcript and opportunities', async () => {
    const opp = { id: 'o1', rank: 1, title: 'Slot filler', pitch: 'Fill no-shows', rationale: null, evidence: [] }
    const api = {
      listBrainstorms: vi.fn().mockResolvedValue(past),
      getBrainstorm: vi.fn().mockResolvedValue({ ...past[1], brief: { summary: 'Vet brief summary' } }),
      getBrainstormMessages: vi.fn().mockResolvedValue({
        messages: [{ role: 'assistant', content: 'Earlier question' }],
      }),
      getBrainstormOpportunities: vi.fn().mockResolvedValue({ opportunities: [opp] }),
    } as unknown as Api
    render(<BrainStorm api={api} onPressureTest={vi.fn()} />)
    fireEvent.click(await screen.findByText('Vets'))
    await waitFor(() => expect(screen.getByText('Slot filler')).toBeInTheDocument())
    expect(screen.getByText('Vet brief summary')).toBeInTheDocument()
    expect(screen.getByText('Earlier question')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pressure-test this' })).toBeInTheDocument()
  })

  it('deletes from the history list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const api = {
      listBrainstorms: vi.fn().mockResolvedValueOnce(past).mockResolvedValue([past[1]]),
      deleteBrainstorm: vi.fn().mockResolvedValue(undefined),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete Clinics' }))
    await waitFor(() => expect(api.deleteBrainstorm).toHaveBeenCalledWith('a'))
    await waitFor(() => expect(screen.queryByText('Clinics')).not.toBeInTheDocument())
  })

  it('shows loading, then empty, in the left column', async () => {
    let resolve: (v: unknown[]) => void = () => {}
    const api = {
      listBrainstorms: vi.fn().mockReturnValue(new Promise((r) => (resolve = r))),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    expect(screen.getByText('Loading your past brain-storms…')).toBeInTheDocument()
    resolve([])
    await waitFor(() => expect(screen.getByText('No past brain-storms yet')).toBeInTheDocument())
    expect(document.querySelector('nav.ide-sidebar')).not.toBeNull()
  })

  it('says the load failed rather than empty', async () => {
    const api = { listBrainstorms: vi.fn().mockRejectedValue(new Error('boom')) } as unknown as Api
    render(<BrainStorm api={api} />)
    await waitFor(() => expect(screen.getByText(/Couldn.t load your past brain-storms/)).toBeInTheDocument())
    expect(screen.queryByText('No past brain-storms yet')).toBeNull()
  })

  it('keeps the column visible, highlights the open row and resets via the new button', async () => {
    const api = {
      listBrainstorms: vi.fn().mockResolvedValue(past),
      getBrainstorm: vi.fn().mockResolvedValue({ ...past[0], turn_count: 2 }),
      getBrainstormMessages: vi.fn().mockResolvedValue({ messages: [{ role: 'assistant', content: 'Who pays?' }] }),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.click(await screen.findByText('Clinics'))
    await waitFor(() => expect(screen.getByText('Who pays?')).toBeInTheDocument())
    const row = screen.getByText('Clinics').closest('button')!
    expect(row).toHaveClass('ide-sidebar-item--active')
    expect(screen.getByText('Vets').closest('button')).not.toHaveClass('ide-sidebar-item--active')
    expect(screen.queryByText('Your past brain-storms')).toBeNull()

    const nav = document.querySelector('nav.ide-sidebar') as HTMLElement
    fireEvent.click(nav.querySelector('.ide-sidebar-new')!)
    await waitFor(() => expect(screen.getByLabelText('Target company or industry')).toBeInTheDocument())
    expect(screen.queryByText('Who pays?')).toBeNull()
  })

  it('deleting the open brain-storm returns to intake; deleting another keeps the view', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const api = {
      listBrainstorms: vi.fn().mockResolvedValue(past),
      getBrainstorm: vi.fn().mockResolvedValue({ ...past[0], turn_count: 2 }),
      getBrainstormMessages: vi.fn().mockResolvedValue({ messages: [{ role: 'assistant', content: 'Who pays?' }] }),
      deleteBrainstorm: vi.fn().mockResolvedValue(undefined),
    } as unknown as Api
    render(<BrainStorm api={api} />)
    fireEvent.click(await screen.findByText('Clinics'))
    await waitFor(() => expect(screen.getByText('Who pays?')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Delete Vets' }))
    await waitFor(() => expect(api.deleteBrainstorm).toHaveBeenCalledWith('b'))
    expect(screen.getByText('Who pays?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete Clinics' }))
    await waitFor(() => expect(api.deleteBrainstorm).toHaveBeenCalledWith('a'))
    await waitFor(() => expect(screen.getByLabelText('Target company or industry')).toBeInTheDocument())
  })
})
