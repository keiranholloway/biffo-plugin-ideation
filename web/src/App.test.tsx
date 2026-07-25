import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import App from './App'
import * as auth from './lib/auth'
import type { CognitoUserSession } from 'amazon-cognito-identity-js'

vi.mock('./lib/auth')

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: status < 400,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  } as Response)
}

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

  it('renders the sidebar with mocked sessions', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'First idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'Second idea', status: 'gathering' as const, created_at: '2026-07-24T15:30:00Z' },
    ]
    mockFetch(200, sessionList)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First idea')).toBeInTheDocument()
      expect(screen.getByText('Second idea')).toBeInTheDocument()
    })
  })

  it('shows only the report card when clicking a complete session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'Completed', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
    ]

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return {
          ok: true,
          json: async () => sessionList,
          text: async () => JSON.stringify(sessionList),
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/report') {
        return {
          ok: true,
          json: async () => ({
            status: 'complete',
            report: {
              prd: {
                problem: 'Test problem',
                target_users: [],
                workflows: [],
                data_entities: [],
                capabilities: [],
                out_of_scope: [],
              },
              scorecard: {
                viability: { score: 4, rationale: 'good' },
                complexity: { score: 3, rationale: 'moderate' },
                economic_moat: { score: 2, rationale: 'weak' },
                market_fit: { score: 4, rationale: 'strong' },
                build_vs_buy: 'Build',
                competitors: [],
                summary: 'Summary text',
              },
            },
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${url}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Completed')).toBeInTheDocument()
    })

    screen.getByText('Completed').click()

    await waitFor(() => {
      expect(screen.getByText('Viability scorecard')).toBeInTheDocument()
      expect(screen.getByText('Summary text')).toBeInTheDocument()
    })

    // Ensure the chat UI is not visible
    expect(screen.queryByPlaceholderText('Answer…')).not.toBeInTheDocument()
    expect(screen.queryByText('Send')).not.toBeInTheDocument()
  })

  it('shows the live chat view when clicking a gathering session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'In progress', status: 'gathering' as const, created_at: '2026-07-25T10:00:00Z' },
    ]

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return {
          ok: true,
          json: async () => sessionList,
          text: async () => JSON.stringify(sessionList),
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1') {
        return {
          ok: true,
          json: async () => ({
            session_id: 's1',
            status: 'gathering',
            turn_count: 1,
            min_turns: 3,
            max_turns: 5,
            can_finalise: false,
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${url}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('In progress')).toBeInTheDocument()
    })

    screen.getByText('In progress').click()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Answer…')).toBeInTheDocument()
      expect(screen.getByText('Send')).toBeInTheDocument()
    })
  })

  it('shows the seed form when clicking + New idea', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'Old idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
    ]

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return {
          ok: true,
          json: async () => sessionList,
          text: async () => JSON.stringify(sessionList),
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/report') {
        return {
          ok: true,
          json: async () => ({
            status: 'complete',
            report: {
              prd: {
                problem: 'Test problem',
                target_users: [],
                workflows: [],
                data_entities: [],
                capabilities: [],
                out_of_scope: [],
              },
              scorecard: {
                viability: { score: 4, rationale: 'good' },
                complexity: { score: 3, rationale: 'moderate' },
                economic_moat: { score: 2, rationale: 'weak' },
                market_fit: { score: 4, rationale: 'strong' },
                build_vs_buy: 'Build',
                competitors: [],
                summary: 'Summary text',
              },
            },
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${url}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Old idea')).toBeInTheDocument()
    })

    // Click on the old idea to show the report
    screen.getByText('Old idea').click()

    await waitFor(() => {
      expect(screen.getByText('Viability scorecard')).toBeInTheDocument()
    })

    // Click + New idea to go back to seed form
    screen.getByText('+ New idea').click()

    await waitFor(() => {
      expect(screen.getByPlaceholderText("e.g. a scheduling assistant for independent coaches…")).toBeInTheDocument()
      expect(screen.queryByText('Viability scorecard')).not.toBeInTheDocument()
    })
  })

  it('initially shows the seed form', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    mockFetch(200, [])

    render(<App />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText("e.g. a scheduling assistant for independent coaches…")).toBeInTheDocument()
    })
  })
})
