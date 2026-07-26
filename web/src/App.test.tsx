import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

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

    // Click Ideate to go back to seed form
    screen.getByText('Ideate').click()

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

  // Regression guard: the polling effect that completes the *primary*
  // start -> chat -> finalise -> poll flow must move `view` to 'report' —
  // not just set the `report`/`session` state — or the report never renders
  // (the report section is gated on `view.kind === 'report'`).
  it('shows the report after finishing the primary chat flow, not a blank screen', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            reply: 'Tell me more',
            session_id: 's1',
            status: 'gathering',
            turn_count: 1,
            min_turns: 1,
            max_turns: 5,
            can_finalise: true,
          }),
          text: async () => '',
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/finalise') {
        return {
          ok: true,
          json: async () => ({ status: 'analysing', analysis_run_id: 'r1' }),
          text: async () => '',
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/report') {
        return {
          ok: true,
          json: async () => ({
            status: 'complete',
            report: {
              prd: {
                problem: 'P',
                target_users: [],
                workflows: [],
                data_entities: [],
                capabilities: [],
                out_of_scope: [],
              },
              scorecard: {
                viability: { score: 4, rationale: 'x' },
                complexity: { score: 3, rationale: 'x' },
                economic_moat: { score: 2, rationale: 'x' },
                market_fit: { score: 4, rationale: 'x' },
                build_vs_buy: 'Build',
                competitors: [],
                summary: 'Final summary',
              },
            },
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText('e.g. a scheduling assistant for independent coaches…'),
      ).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Your idea'), { target: { value: 'A great idea' } })
    screen.getByText('Start').click()

    await waitFor(() => {
      expect(screen.getByText('Generate review')).toBeInTheDocument()
    })

    screen.getByText('Generate review').click()

    await waitFor(() => {
      expect(
        screen.getByText('Analysing your idea — researching the landscape and scoring it…'),
      ).toBeInTheDocument()
    })

    await waitFor(
      () => {
        expect(screen.getByText('Final summary')).toBeInTheDocument()
      },
      { timeout: 6000 },
    )

    expect(
      screen.queryByText('Analysing your idea — researching the landscape and scoring it…'),
    ).not.toBeInTheDocument()
  }, 8000)

  // Regression guard: switching from a viewed report to a different live
  // (in-progress) session must clear the stale `report` state, or the chat
  // view (gated on `!report`) stays hidden behind the old report.
  it('clears a previously-viewed report when switching to a live session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'Completed', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'In progress', status: 'gathering' as const, created_at: '2026-07-24T15:30:00Z' },
    ]

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => sessionList, text: async () => '' } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/report') {
        return {
          ok: true,
          json: async () => ({
            status: 'complete',
            report: {
              prd: {
                problem: 'P',
                target_users: [],
                workflows: [],
                data_entities: [],
                capabilities: [],
                out_of_scope: [],
              },
              scorecard: {
                viability: { score: 4, rationale: 'x' },
                complexity: { score: 3, rationale: 'x' },
                economic_moat: { score: 2, rationale: 'x' },
                market_fit: { score: 4, rationale: 'x' },
                build_vs_buy: 'Build',
                competitors: [],
                summary: 'Old summary',
              },
            },
          }),
          text: async () => '',
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s2') {
        return {
          ok: true,
          json: async () => ({
            session_id: 's2',
            status: 'gathering',
            turn_count: 1,
            min_turns: 3,
            max_turns: 5,
            can_finalise: false,
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Completed')).toBeInTheDocument()
    })

    screen.getByText('Completed').click()

    await waitFor(() => {
      expect(screen.getByText('Old summary')).toBeInTheDocument()
    })

    screen.getByText('In progress').click()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Answer…')).toBeInTheDocument()
    })

    expect(screen.queryByText('Old summary')).not.toBeInTheDocument()
  })

  it('shows the "Use my original idea" button when submitted idea exists', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/submitted-idea') {
        return {
          ok: true,
          json: async () => ({ idea: 'A scheduling assistant for independent coaches' }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Use my original idea')).toBeInTheDocument()
    })
  })

  it('hides the "Use my original idea" button when submitted idea is null', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/submitted-idea') {
        return {
          ok: true,
          json: async () => ({ idea: null }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText('e.g. a scheduling assistant for independent coaches…')).toBeInTheDocument()
    })

    expect(screen.queryByText('Use my original idea')).not.toBeInTheDocument()
  })

  it('prefills the textarea when clicking "Use my original idea"', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/submitted-idea') {
        return {
          ok: true,
          json: async () => ({ idea: 'My submitted coaching app idea' }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Use my original idea')).toBeInTheDocument()
    })

    const textarea = screen.getByLabelText('Your idea') as HTMLTextAreaElement
    expect(textarea.value).toBe('')

    fireEvent.click(screen.getByText('Use my original idea'))

    await waitFor(() => {
      expect(textarea.value).toBe('My submitted coaching app idea')
    })
  })

  it('still allows starting with the seed form normally when no submitted idea', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/submitted-idea') {
        return {
          ok: true,
          json: async () => ({ idea: null }),
          text: async () => '',
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            reply: 'Tell me more',
            session_id: 's1',
            status: 'gathering',
            turn_count: 1,
            min_turns: 1,
            max_turns: 5,
            can_finalise: true,
          }),
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText('e.g. a scheduling assistant for independent coaches…')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Your idea'), { target: { value: 'My new idea' } })
    screen.getByText('Start').click()

    await waitFor(() => {
      expect(screen.getByText('Generate review')).toBeInTheDocument()
    })
  })
})
