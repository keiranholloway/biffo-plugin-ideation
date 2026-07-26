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

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => [],
      text: async () => '[]',
    } as Response)

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

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/chat-agents')) {
        return {
          ok: true,
          json: async () => agents,
          text: async () => JSON.stringify(agents),
        } as Response
      }
      if (String(url).includes('/model-catalog')) {
        return {
          ok: true,
          json: async () => [],
          text: async () => '[]',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

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

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/chat-agents')) {
        return {
          ok: true,
          json: async () => [],
          text: async () => '[]',
        } as Response
      }
      if (String(url).includes('/model-catalog')) {
        return {
          ok: true,
          json: async () => entries,
          text: async () => JSON.stringify(entries),
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

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

    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => [],
      text: async () => '[]',
    } as Response)

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
})
