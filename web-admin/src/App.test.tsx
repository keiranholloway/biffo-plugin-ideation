import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import App from './App'
import * as auth from './lib/auth'
import type { CognitoUserSession } from 'amazon-cognito-identity-js'

vi.mock('./lib/auth')

function createMockSession() {
  return {
    getIdToken: () => ({
      getJwtToken: () => 'test-token',
    }),
  } as unknown as CognitoUserSession
}

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as Response
}

/** Every request the panel makes, with an empty answer for each. Routes are
 * matched individually because /effective-config is a different shape from the
 * two list routes — the whole point of it is that it answers a question the
 * lists cannot (issue #58). */
function mockFetch(overrides: {
  effectiveConfig?: unknown
  chatAgents?: unknown
  modelCatalog?: unknown
} = {}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    const href = String(url)
    if (href.includes('/effective-config'))
      return jsonResponse(overrides.effectiveConfig ?? { agents: [], models: [] })
    if (href.includes('/chat-agents')) return jsonResponse(overrides.chatAgents ?? [])
    if (href.includes('/model-catalog')) return jsonResponse(overrides.modelCatalog ?? [])
    throw new Error(`Unexpected URL: ${href}`)
  })
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows sign-in prompt when no session', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(null)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/No session found/)).toBeInTheDocument()
    })
  })

  it('renders agent and catalog tabs when authenticated', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    mockFetch()

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Chat Agents' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Model Catalog' })).toBeInTheDocument()
    })
  })

  it('loads and displays agents', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const agents = [
      {
        agent_key: 'agent-1',
        agent_name: 'Test Agent',
        role: 'tester',
        system_prompt: 'test',
        model: 'claude-3-sonnet',
        required_group: 'admin',
        active: true,
        max_history_messages: 10,
        max_output_tokens: 2000,
        timeout_seconds: 30,
      },
    ]

    mockFetch({ chatAgents: agents })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Test Agent')).toBeInTheDocument()
      expect(screen.getByText('agent-1')).toBeInTheDocument()
    })
  })

  it('loads and displays model catalog entries', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const entries = [
      {
        id: 'entry-1',
        model_id: 'claude-3-sonnet',
        label: 'Claude 3 Sonnet',
        active: true,
        is_default: true,
      },
    ]

    mockFetch({ modelCatalog: entries })

    render(<App />)

    // Switch to catalog tab
    await waitFor(() => {
      screen.getByText('Model Catalog').click()
    })

    await waitFor(() => {
      expect(screen.getByText('Claude 3 Sonnet')).toBeInTheDocument()
      expect(screen.getByText('claude-3-sonnet')).toBeInTheDocument()
    })
  })

  it('switches between tabs', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    mockFetch()

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Chat Agents' })).toBeInTheDocument()
    })

    const catalogTab = screen.getByRole('button', { name: 'Model Catalog' })
    catalogTab.click()

    await waitFor(() => {
      expect(catalogTab).toHaveClass('admin-tab--active')
    })
  })

  // ── issue #58: the panel must answer "what is actually in use?" ────────────

  it('shows the built-in configuration in use when both tables are empty', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())

    mockFetch({
      effectiveConfig: {
        agents: [
          {
            agent_key: 'ideation-challenger',
            agent_name: 'ideation-challenger',
            role: 'challenger',
            system_prompt: 'Pressure-test the idea.',
            model: 'anthropic/claude-sonnet-4',
            required_group: 'founder',
            active: true,
          },
        ],
        models: [
          {
            purpose: 'chat',
            label: 'Challenger (requirement-gathering chat)',
            model_id: 'anthropic/claude-sonnet-4',
            source: 'built-in',
            env_var: 'IDEATION_CHAT_MODEL',
          },
        ],
      },
    })

    render(<App />)

    // Both reads return an empty table — the state that used to render as
    // "No agents defined yet" while the engine ran on this very default.
    await waitFor(() => {
      expect(screen.getAllByText('ideation-challenger').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Default — not stored')).toBeInTheDocument()
    expect(screen.queryByText('No agents defined yet.')).not.toBeInTheDocument()

    screen.getByRole('button', { name: 'Model Catalog' }).click()

    await waitFor(() => {
      expect(screen.getByText('Models in use')).toBeInTheDocument()
    })
    expect(screen.getByText(/anthropic\/claude-sonnet-4/)).toBeInTheDocument()
  })

  it('stores a built-in default verbatim when asked to make it editable', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())

    const builtin = {
      agent_key: 'ideation-analyst',
      agent_name: 'ideation-analyst',
      role: 'analyst',
      system_prompt: 'Assess the idea.',
      model: 'anthropic/claude-opus-4-8',
      required_group: 'founder',
      active: true,
    }
    const fetchMock = mockFetch({ effectiveConfig: { agents: [builtin], models: [] } })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Store a copy to edit')).toBeInTheDocument()
    })

    screen.getByText('Store a copy to edit').click()

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(posted).toBeDefined()
      // Verbatim: overriding a default must start as a copy of it, or the row
      // silently changes behaviour the moment it is created.
      expect(JSON.parse(String((posted?.[1] as RequestInit).body))).toEqual(builtin)
    })
  })
})
