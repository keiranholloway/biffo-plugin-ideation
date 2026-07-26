import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { AgentList } from './AgentList'
import type { ChatAgent } from '../lib/api'

describe('AgentList', () => {
  const mockAgents: ChatAgent[] = [
    {
      agent_key: 'agent-1',
      agent_name: 'Test Agent 1',
      role: 'tester',
      system_prompt: 'You are a test agent',
      model: 'claude-3-sonnet',
      required_group: 'admin',
      active: true,
      max_history_messages: 10,
      max_output_tokens: 2000,
      timeout_seconds: 30,
    },
    {
      agent_key: 'agent-2',
      agent_name: 'Test Agent 2',
      role: 'reviewer',
      system_prompt: 'You review things',
      model: 'claude-3-opus',
      required_group: 'admin',
      active: false,
      max_history_messages: 20,
      max_output_tokens: 4000,
      timeout_seconds: 60,
    },
  ]

  it('renders a list of agents', () => {
    const onUpdate = vi.fn()
    const onDelete = vi.fn()

    render(<AgentList agents={mockAgents} onUpdate={onUpdate} onDelete={onDelete} />)

    expect(screen.getByText('Test Agent 1')).toBeInTheDocument()
    expect(screen.getByText('Test Agent 2')).toBeInTheDocument()
    expect(screen.getByText('agent-1')).toBeInTheDocument()
    expect(screen.getByText('agent-2')).toBeInTheDocument()
  })

  it('shows empty state when no agents', () => {
    const onUpdate = vi.fn()
    const onDelete = vi.fn()

    render(<AgentList agents={[]} onUpdate={onUpdate} onDelete={onDelete} />)

    expect(screen.getByText('No agents defined yet.')).toBeInTheDocument()
  })

  it('renders active and inactive badges', () => {
    const onUpdate = vi.fn()
    const onDelete = vi.fn()

    render(<AgentList agents={mockAgents} onUpdate={onUpdate} onDelete={onDelete} />)

    const badges = screen.getAllByText(/Active|Inactive/)
    expect(badges.length).toBeGreaterThan(0)
  })

  it('calls onDelete when delete button is clicked', () => {
    const onUpdate = vi.fn()
    const onDelete = vi.fn()

    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<AgentList agents={mockAgents} onUpdate={onUpdate} onDelete={onDelete} />)

    const deleteButtons = screen.getAllByText('Delete')
    deleteButtons[0].click()

    expect(onDelete).toHaveBeenCalledWith('agent-1')
  })
})
