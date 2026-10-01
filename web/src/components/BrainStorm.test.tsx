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
      startBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'qualifying', reply: 'Q?' }),
      finaliseBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'researching' }),
      getBrainstorm: vi.fn().mockResolvedValue({ ...state, status: 'complete' }),
      getBrainstormOpportunities: vi.fn().mockResolvedValue({ opportunities: [opp] }),
    } as unknown as Api
    const onPressureTest = vi.fn()
    render(<BrainStorm api={api} onPressureTest={onPressureTest} />)
    fireEvent.change(screen.getByLabelText('Target company or industry'), { target: { value: 'clinics' } })
    fireEvent.click(screen.getByRole('button', { name: /Start brain-storm/ }))
    await waitFor(() => expect(screen.getByText('Q?')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Generate opportunities' }))
    await waitFor(() => expect(screen.getByText(/Researching/)).toBeInTheDocument())
    expect(api.finaliseBrainstorm).toHaveBeenCalledWith('s1')

    await waitFor(() => expect(screen.getByText('Slot filler')).toBeInTheDocument(), { timeout: 6000 })
    fireEvent.click(screen.getByRole('button', { name: 'Pressure-test this' }))
    expect(onPressureTest).toHaveBeenCalledWith('Slot filler: Fill no-shows')
  }, 10000)
})
