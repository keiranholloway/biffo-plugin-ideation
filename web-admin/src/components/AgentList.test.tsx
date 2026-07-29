import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { AgentList } from './AgentList'
import type { BuiltinAgent, ChatAgent } from '../lib/api'

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

  const mockBuiltins: BuiltinAgent[] = [
    {
      agent_key: 'ideation-challenger',
      agent_name: 'ideation-challenger',
      role: 'challenger',
      system_prompt: 'You are Biffo’s Ideation partner',
      model: 'anthropic/claude-sonnet-4',
      required_group: 'founder',
      active: true,
    },
  ]

  function noopProps() {
    return {
      onUpdate: vi.fn(),
      onDelete: vi.fn(),
      onStoreBuiltin: vi.fn(),
      // Empty catalog: the model field degrades to free text, so these tests
      // keep exercising the list rather than the picker (ModelSelect has its
      // own).
      catalogEntries: [],
    }
  }

  it('renders a list of agents', () => {
    render(<AgentList agents={mockAgents} builtins={[]} {...noopProps()} />)

    expect(screen.getByText('Test Agent 1')).toBeInTheDocument()
    expect(screen.getByText('Test Agent 2')).toBeInTheDocument()
    expect(screen.getByText('agent-1')).toBeInTheDocument()
    expect(screen.getByText('agent-2')).toBeInTheDocument()
  })

  it('renders active and inactive badges', () => {
    render(<AgentList agents={mockAgents} builtins={[]} {...noopProps()} />)

    const badges = screen.getAllByText(/Active|Inactive/)
    expect(badges.length).toBeGreaterThan(0)
  })

  it('calls onDelete when delete button is clicked', () => {
    const props = noopProps()
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<AgentList agents={mockAgents} builtins={[]} {...props} />)

    const deleteButtons = screen.getAllByText('Delete')
    deleteButtons[0].click()

    expect(props.onDelete).toHaveBeenCalledWith('agent-1')
  })

  // ── issue #58: an empty table is not an unconfigured engine ────────────────

  it('shows the built-in defaults instead of claiming nothing is defined', () => {
    render(<AgentList agents={[]} builtins={mockBuiltins} {...noopProps()} />)

    // The old copy — "No agents defined yet." — described the table and
    // contradicted the engine, which runs on the default below.
    expect(screen.queryByText('No agents defined yet.')).not.toBeInTheDocument()
    // Name and key, so two matches.
    expect(screen.getAllByText('ideation-challenger').length).toBeGreaterThan(0)
    expect(screen.getByText('Default — not stored')).toBeInTheDocument()
    expect(screen.getByText(/running on the built-in defaults/)).toBeInTheDocument()
  })

  it('shows the prompt a built-in default is actually running', () => {
    render(<AgentList agents={[]} builtins={mockBuiltins} {...noopProps()} />)

    expect(screen.getByText('You are Biffo’s Ideation partner')).toBeInTheDocument()
    expect(screen.getByText('anthropic/claude-sonnet-4')).toBeInTheDocument()
  })

  it('offers to store a built-in default rather than only "Add New Agent"', () => {
    const props = noopProps()

    render(<AgentList agents={[]} builtins={mockBuiltins} {...props} />)

    screen.getByText('Store a copy to edit').click()

    expect(props.onStoreBuiltin).toHaveBeenCalledWith(mockBuiltins[0])
  })

  it('marks a stored row that overrides a built-in as an override', () => {
    const stored: ChatAgent = { ...mockAgents[0], agent_key: 'ideation-challenger' }

    render(<AgentList agents={[stored]} builtins={mockBuiltins} {...noopProps()} />)

    expect(screen.getByText('Stored — overrides the built-in default')).toBeInTheDocument()
    // Not listed twice: the stored row replaces the default, it does not sit
    // beside it.
    expect(screen.queryByText('Default — not stored')).not.toBeInTheDocument()
  })

  it('marks a stored row with no built-in behind it as merely stored', () => {
    render(<AgentList agents={[mockAgents[0]]} builtins={mockBuiltins} {...noopProps()} />)

    expect(screen.getByText('Stored')).toBeInTheDocument()
    expect(screen.getByText('Default — not stored')).toBeInTheDocument()
  })

  it('falls back to an empty state only when there is genuinely nothing', () => {
    render(<AgentList agents={[]} builtins={[]} {...noopProps()} />)

    expect(
      screen.getByText('No agents stored, and no built-in defaults reported.'),
    ).toBeInTheDocument()
  })

  // ── a stored prompt has to be reachable, or storing one freezes it ─────────

  it('shows the prompt a stored row is running, not only a built-in one', () => {
    render(<AgentList agents={mockAgents} builtins={[]} {...noopProps()} />)

    expect(screen.getByText('You are a test agent')).toBeInTheDocument()
  })

  it('lets the stored prompt be edited and saved', () => {
    const props = noopProps()
    render(<AgentList agents={mockAgents} builtins={[]} {...props} />)

    fireEvent.click(screen.getAllByText('Edit')[0])

    // Storing a copy overrides the built-in constant, so definitions.py no
    // longer reaches the runtime for this agent. If the form omits the prompt,
    // nothing anywhere can change it.
    const box = screen.getByLabelText(/System prompt/i) as HTMLTextAreaElement
    expect(box.value).toBe('You are a test agent')

    fireEvent.change(box, { target: { value: 'Rewritten by an admin' } })
    fireEvent.click(screen.getByText('Save'))

    expect(props.onUpdate).toHaveBeenCalledWith(
      'agent-1',
      expect.objectContaining({ system_prompt: 'Rewritten by an admin' }),
    )
  })
})
