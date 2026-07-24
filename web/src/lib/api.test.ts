import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, createApi } from './api'

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: status < 400,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  } as Response)
}

describe('createApi', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('starts a session at /api/v1/plugins/ideation/sessions with the Bearer token', async () => {
    const f = mockFetch(201, {
      session_id: 's1',
      reply: 'why now?',
      status: 'gathering',
      turn_count: 1,
      min_turns: 3,
      max_turns: 5,
      can_finalise: false,
    })
    const api = createApi(() => 'tok-123')

    const r = await api.startSession('an idea')

    expect(r.session_id).toBe('s1')
    const [url, opts] = f.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/plugins/ideation/sessions')
    expect(opts.method).toBe('POST')
    // The founder JWT rides Authorization: Bearer (ADR-0021), as the portal calls
    // Core — the gateway's Cognito authorizer validates it and the host gates on it.
    const headers = opts.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer tok-123')
    expect(headers['X-Biffo-Founder-Token']).toBeUndefined()
    expect(JSON.parse(opts.body as string)).toEqual({ seed_idea: 'an idea' })
  })

  it('routes each call to its path', async () => {
    const f = mockFetch(200, { status: 'analysing', report: null })
    const api = createApi(() => 't')

    await api.getReport('s1')
    expect((f.mock.calls[0] as [string])[0]).toBe('/api/v1/plugins/ideation/sessions/s1/report')

    await api.finalise('s1')
    expect((f.mock.calls[1] as [string])[0]).toBe('/api/v1/plugins/ideation/sessions/s1/finalise')
  })

  it('maps a non-2xx response to ApiError with the status', async () => {
    mockFetch(409, 'not gathering')
    const api = createApi(() => 't')

    await expect(api.sendMessage('s1', 'x')).rejects.toMatchObject({ status: 409 })
    await expect(api.sendMessage('s1', 'x')).rejects.toBeInstanceOf(ApiError)
  })

  it('omits Authorization when there is no token', async () => {
    const f = mockFetch(200, { session_id: 's1' })
    const api = createApi(() => null)

    await api.getSession('s1')
    const opts = (f.mock.calls[0] as [string, RequestInit])[1]
    expect((opts.headers as Record<string, string>)['Authorization']).toBeUndefined()
  })
})
