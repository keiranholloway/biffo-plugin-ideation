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

// A real Cognito ID token carries group membership in `cognito:groups`; the
// default here is a founder, because that is what every other test in this file
// is about. Pass explicit groups to exercise the gate itself.
// `jwt` is fixed per session object on purpose: the real `CognitoUserSession` is
// an immutable snapshot, so a JWT read off one never changes no matter how long
// the page has been open (see lib/auth.ts).
function createMockSession(groups: unknown = ['founder'], jwt = 'test-token') {
  const idToken = { getJwtToken: () => jwt, payload: { 'cognito:groups': groups } }
  return { getIdToken: () => idToken } as unknown as CognitoUserSession
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('never says "No past runs yet" while the list request is still in flight', async () => {
    // The regression this guards is invisible to every other test here, because
    // they all await the resolved state. Between mount and the fetch resolving,
    // `sessions` is [] and `sessionsFailed` is false — which used to render the
    // same words as a completed empty load, telling a founder with runs that
    // they had none (#83).
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())
    vi.spyOn(auth, 'getFreshIdToken').mockResolvedValue('tok')

    let releaseSessions: (v: unknown) => void = () => {}
    const pending = new Promise((resolve) => {
      releaseSessions = resolve
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/sessions')) {
        await pending
        return { ok: true, status: 200, json: async () => [], text: async () => '[]' } as Response
      }
      return { ok: true, status: 200, json: async () => ({}), text: async () => '{}' } as Response
    })

    render(<App />)

    // The list has not answered yet, so the sidebar must not speak for it.
    await waitFor(() => expect(screen.getByText(/Loading your past runs/)).toBeInTheDocument())
    expect(screen.queryByText('No past runs yet')).not.toBeInTheDocument()

    // Once it answers with a genuinely empty list, the empty state is correct.
    releaseSessions(null)
    await waitFor(() => expect(screen.getByText('No past runs yet')).toBeInTheDocument())
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

  it('shows the challenger picker when multiple active agents exist, and sends the chosen key', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    let capturedBody: string | null = null

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/agents') {
        return {
          ok: true,
          json: async () => [
            { agent_key: 'skeptic', agent_name: 'The Skeptic' },
            { agent_key: 'ally', agent_name: 'The Ally' },
          ],
          text: async () => '',
        } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'POST') {
        capturedBody = init?.body as string
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
      expect(screen.getByLabelText('Challenger persona')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Your idea'), { target: { value: 'An idea' } })
    fireEvent.change(screen.getByLabelText('Challenger persona'), { target: { value: 'ally' } })
    screen.getByText('Start').click()

    await waitFor(() => {
      expect(capturedBody).not.toBeNull()
    })
    expect(JSON.parse(capturedBody!)).toEqual({
      seed_idea: 'An idea',
      challenger_agent_key: 'ally',
    })
  })

  it('does not show the challenger picker when zero or one active agent exists', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => [], text: async () => '[]' } as Response
      }
      if (url === '/api/v1/plugins/ideation/agents') {
        return {
          ok: true,
          json: async () => [{ agent_key: 'skeptic', agent_name: 'The Skeptic' }],
          text: async () => '',
        } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText('e.g. a scheduling assistant for independent coaches…')).toBeInTheDocument()
    })

    expect(screen.queryByLabelText('Challenger persona')).not.toBeInTheDocument()
  })

  it('deletes a session and refreshes the list when confirmed', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const initialSessions = [
      { session_id: 's1', title: 'First idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'Second idea', status: 'gathering' as const, created_at: '2026-07-24T15:30:00Z' },
    ]

    vi.spyOn(window, 'confirm').mockReturnValue(true)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => initialSessions, text: async () => '' } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions/s1/delete' && method === 'POST') {
        return { ok: true, json: async () => ({}), text: async () => '' } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First idea')).toBeInTheDocument()
      expect(screen.getByText('Second idea')).toBeInTheDocument()
    })

    const deleteButtons = screen.getAllByLabelText('Delete this idea')
    deleteButtons[0].click()

    expect(window.confirm).toHaveBeenCalled()
  })

  it('cancels delete when user declines the confirm', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'My idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
    ]

    vi.spyOn(window, 'confirm').mockReturnValue(false)

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/plugins/ideation/sessions') {
        return { ok: true, json: async () => sessionList, text: async () => '' } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('My idea')).toBeInTheDocument()
    })

    screen.getByLabelText('Delete this idea').click()

    expect(window.confirm).toHaveBeenCalled()
    // Verify delete endpoint was never called
    expect(fetchSpy).not.toHaveBeenCalledWith(expect.stringContaining('/delete'), expect.anything())
  })

  it('resets to seed view when deleting the currently open session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'My idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
    ]

    vi.spyOn(window, 'confirm').mockReturnValue(true)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => sessionList, text: async () => '' } as Response
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
      if (url === '/api/v1/plugins/ideation/sessions/s1/delete') {
        return { ok: true, json: async () => ({}), text: async () => '' } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('My idea')).toBeInTheDocument()
    })

    // Click on the session to open its report
    screen.getByText('My idea').click()

    await waitFor(() => {
      expect(screen.getByText('Viability scorecard')).toBeInTheDocument()
    })

    // Delete the open session
    screen.getByLabelText('Delete this idea').click()

    // Verify we're back at the seed form
    await waitFor(() => {
      expect(screen.getByPlaceholderText("e.g. a scheduling assistant for independent coaches…")).toBeInTheDocument()
      expect(screen.queryByText('Viability scorecard')).not.toBeInTheDocument()
    })
  })

  it('keeps the current view when deleting a different session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'Completed', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
      { session_id: 's2', title: 'In progress', status: 'gathering' as const, created_at: '2026-07-24T15:30:00Z' },
    ]

    vi.spyOn(window, 'confirm').mockReturnValue(true)

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => sessionList, text: async () => '' } as Response
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
      if (url === '/api/v1/plugins/ideation/sessions/s1/delete') {
        return { ok: true, json: async () => ({}), text: async () => '' } as Response
      }
      throw new Error(`Unexpected URL: ${String(url)}`)
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('In progress')).toBeInTheDocument()
      expect(screen.getByText('Completed')).toBeInTheDocument()
    })

    // Click on the in-progress session to open it
    screen.getByText('In progress').click()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Answer…')).toBeInTheDocument()
    })

    // Delete the completed session (different one)
    const deleteButtons = screen.getAllByLabelText('Delete this idea')
    deleteButtons[0].click() // First delete button is for 'Completed'

    // Verify the live chat view is still visible
    expect(screen.getByPlaceholderText('Answer…')).toBeInTheDocument()
  })
})

// The reporter's route in keiranholloway/biffo-platform-app#4: navigate straight
// to https://dev.biffo.io/ideation/ rather than going through the dashboard,
// which has its own (client-side) gate. The static shell is served publicly from
// S3/CloudFront and cannot check a group, so the SPA has to do the bounce that
// `user_frontend.required_group` declares (ADR-0018 §2). This is UX only — the
// server enforces the same group at API Gateway, at the shared plugin host's
// group_gate, and again in the plugin's own require_group("founder").
describe('App founder-group gate (direct navigation to /ideation/)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/ideation/')
  })

  it('refuses to render the engine for a signed-in user with no founder group', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession([]))
    const fetchSpy = mockFetch(200, [])

    render(<App />)

    expect(await screen.findByText(/available to members of the/i)).toBeInTheDocument()
    // The chat UI must not be there at all — not merely error out per action.
    expect(screen.queryByLabelText('Your idea')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
    // And it must not have called the API on their behalf.
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('refuses a user in some other group (the group is matched exactly)', async () => {
    // `user_ingress.required_group` is literally "founder". Admitting an admin
    // here would just move the server's 403 from the front door to every button.
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession(['admin', 'staff']))
    mockFetch(200, [])

    render(<App />)

    expect(await screen.findByText(/available to members of the/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Your idea')).not.toBeInTheDocument()
  })

  it('refuses a token whose cognito:groups claim is not a list of groups', async () => {
    // `undefined` would hit createMockSession's default, so use an explicit
    // malformed value; roles.test.ts covers the wholly-absent claim.
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession(null))
    mockFetch(200, [])

    render(<App />)

    expect(await screen.findByText(/available to members of the/i)).toBeInTheDocument()
  })

  it('still renders the engine for a founder', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession(['founder']))
    mockFetch(200, [])

    render(<App />)

    expect(await screen.findByLabelText('Your idea')).toBeInTheDocument()
    expect(screen.queryByText(/available to members of the/i)).not.toBeInTheDocument()
  })

  it('shows the report title when clicking a past complete session', async () => {
    const mockSession = createMockSession()
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(mockSession)

    const sessionList = [
      { session_id: 's1', title: 'My Completed Idea', status: 'complete' as const, created_at: '2026-07-25T10:00:00Z' },
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
            title: 'My Completed Idea',
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
      expect(screen.getByText('My Completed Idea')).toBeInTheDocument()
    })

    screen.getByText('My Completed Idea').click()

    await waitFor(() => {
      // The title should appear in the report
      expect(screen.getAllByText('My Completed Idea').length).toBeGreaterThanOrEqual(2) // Once in sidebar, once in report
      expect(screen.getByText('Viability scorecard')).toBeInTheDocument()
    })
  })

  it('shows the report title when a live run completes (analysing poll)', async () => {
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
            title: 'My Live Run Title',
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
      expect(screen.getByPlaceholderText('e.g. a scheduling assistant for independent coaches…')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Your idea'), { target: { value: 'A great idea' } })
    screen.getByText('Start').click()

    await waitFor(() => {
      expect(screen.getByText('Generate review')).toBeInTheDocument()
    })

    screen.getByText('Generate review').click()

    await waitFor(() => {
      expect(screen.getByText('Analysing your idea — researching the landscape and scoring it…')).toBeInTheDocument()
    })

    // Wait for the report to complete and the title to appear
    await waitFor(
      () => {
        expect(screen.getByText('My Live Run Title')).toBeInTheDocument()
        expect(screen.getByText('Final summary')).toBeInTheDocument()
      },
      { timeout: 6000 },
    )
  }, 8000)
})

describe('App ?seed= deep-link', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/ideation/')
  })

  async function renderWithUrl(search: string) {
    window.history.replaceState({}, '', `/ideation/${search}`)
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())
    mockFetch(200, [])
    render(<App />)
    return await screen.findByLabelText('Your idea')
  }

  it('prefills the seed box from ?seed=', async () => {
    const box = await renderWithUrl('?seed=A%20scheduling%20assistant%20for%20coaches')

    expect(box).toHaveValue('A scheduling assistant for coaches')
  })

  it('leaves the seed box empty when there is no ?seed=', async () => {
    const box = await renderWithUrl('')

    expect(box).toHaveValue('')
  })

  it('truncates an over-long ?seed= to the server-side limit', async () => {
    const box = await renderWithUrl(`?seed=${'x'.repeat(16_050)}`)

    expect((box as HTMLTextAreaElement).value).toHaveLength(16_000)
  })

  it('does not auto-start a session from ?seed=', async () => {
    const fetchSpy = mockFetch(200, [])
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())
    window.history.replaceState({}, '', '/ideation/?seed=an%20idea')

    render(<App />)
    await screen.findByLabelText('Your idea')

    // startSession is the only POST this view can make.
    expect(
      fetchSpy.mock.calls.some(([, init]) => init?.method === 'POST'),
    ).toBe(false)
    // The founder still has to click Start.
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
  })

  it('strips ?seed= from the URL once read, so a refresh does not re-prefill', async () => {
    await renderWithUrl('?seed=an%20idea')

    await waitFor(() => {
      expect(window.location.search).toBe('')
    })
  })

  it('does not overwrite the founder editing the prefilled idea', async () => {
    const box = await renderWithUrl('?seed=an%20idea')

    fireEvent.change(box, { target: { value: 'my own idea' } })

    expect(box).toHaveValue('my own idea')
  })
})

// ---------------------------------------------------------------------------
// #69 — "my finished run is not in my list, and it came back the next day with
// no deploy". The API and the database were right the whole time; the founder
// SPA showed a list that was true only at mount, on a token that was true only
// at mount. Three guards, one per way the nav could lie.
// ---------------------------------------------------------------------------
describe('session list freshness', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function authHeaders(f: ReturnType<typeof mockFetch>): (string | undefined)[] {
    return f.mock.calls.map(
      ([, init]) => (init?.headers as Record<string, string> | undefined)?.['Authorization'],
    )
  }

  it('authorises every call with a re-resolved token, never the snapshot taken at mount', async () => {
    // The mount-time session exists only to read `cognito:groups` off. Its JWT
    // is whatever was cached when the page loaded — possibly seconds from
    // expiry — and it never changes again, so nothing may send it.
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(
      createMockSession(['founder'], 'snapshot-jwt'),
    )
    vi.spyOn(auth, 'getFreshIdToken').mockResolvedValue('refreshed-jwt')
    const f = mockFetch(200, [])

    render(<App />)

    await waitFor(() => expect(f).toHaveBeenCalled())
    const sent = authHeaders(f)
    expect(sent.length).toBeGreaterThan(0)
    expect(sent).not.toContain('Bearer snapshot-jwt')
    for (const header of sent) expect(header).toBe('Bearer refreshed-jwt')
  })

  it('refetches the list once a run is created, so it does not stay as it was at mount', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())
    vi.spyOn(auth, 'getFreshIdToken').mockResolvedValue('tok')

    // The list is genuinely empty when the page loads, and gains a row the
    // moment the founder starts a run. Nothing else in the app changes.
    let listed: unknown[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'GET') {
        return { ok: true, json: async () => listed, text: async () => '' } as Response
      }
      if (url === '/api/v1/plugins/ideation/sessions' && method === 'POST') {
        listed = [
          {
            session_id: 's1',
            title: 'A marketplace for farm shops',
            status: 'gathering',
            created_at: '2026-07-28T18:57:00Z',
          },
        ]
        return {
          ok: true,
          json: async () => ({
            reply: 'why now?',
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
      return { ok: true, json: async () => ({ idea: null }), text: async () => '' } as Response
    })

    render(<App />)
    await screen.findByLabelText('Your idea')
    expect(screen.getByText('No past runs yet')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Your idea'), { target: { value: 'farm shops' } })
    screen.getByText('Start').click()

    // Before this fix the nav only refetched when a *report* materialised, so a
    // run that was never finalised — or whose report poll errored — stayed
    // invisible for the life of the page while sitting in the database.
    await waitFor(() => {
      expect(screen.getByText('A marketplace for farm shops')).toBeInTheDocument()
    })
  })

  it('does not claim "No past runs yet" when the list failed to load', async () => {
    vi.spyOn(auth, 'getCurrentSession').mockResolvedValue(createMockSession())
    vi.spyOn(auth, 'getFreshIdToken').mockResolvedValue('expired-tok')
    mockFetch(401, 'Unauthorized')

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/Couldn.t load your past runs/)).toBeInTheDocument()
    })
    // The empty state is a claim about the founder's data. It must not be made
    // on the strength of a request that never succeeded.
    expect(screen.queryByText('No past runs yet')).not.toBeInTheDocument()
  })
})
