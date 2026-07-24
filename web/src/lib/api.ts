// Calls THIS module's own Lambda ingress only (never Core directly — ADR-0002).
// Same-origin, path-routed at <base>/ideation/api/* on the shared CloudFront; the
// founder's Cognito id token is sent in the X-Biffo-Founder-Token header (behind
// CloudFront OAC, Authorization carries the SigV4 origin signature — ADR-0018),
// which the Lambda verifies (require_group("founder")) before doing anything.

const API_BASE = '/ideation/api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface SessionState {
  session_id: string
  status: 'gathering' | 'analysing' | 'complete'
  turn_count: number
  min_turns: number
  max_turns: number
  can_finalise: boolean
}

export interface TurnResponse extends SessionState {
  reply: string
}

export interface ScoreAxis {
  score: number
  rationale: string
}

export interface Competitor {
  name: string
  url?: string | null
  note: string
}

export interface Scorecard {
  viability: ScoreAxis
  complexity: ScoreAxis
  economic_moat: ScoreAxis
  market_fit: ScoreAxis
  build_vs_buy: string
  competitors: Competitor[]
  summary: string
}

export interface PRD {
  problem: string
  target_users: string[]
  workflows: string[]
  data_entities: string[]
  capabilities: string[]
  out_of_scope: string[]
}

export interface Report {
  prd: PRD
  scorecard: Scorecard
  model?: string | null
}

export interface ReportResponse {
  status: string
  report: Report | null
}

export type Api = ReturnType<typeof createApi>

export function createApi(getIdToken: () => string | null) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = getIdToken()
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        // The founder id token rides X-Biffo-Founder-Token, NOT Authorization:
        // behind CloudFront OAC (ADR-0018) the Authorization header is consumed by
        // the SigV4 origin signature, so the app reads the JWT from this header.
        ...(token != null ? { 'X-Biffo-Founder-Token': token } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText)
      throw new ApiError(res.status, detail)
    }
    return res.json() as Promise<T>
  }

  return {
    startSession: (seed_idea: string) =>
      request<TurnResponse>('POST', '/sessions', { seed_idea }),
    sendMessage: (id: string, message: string) =>
      request<TurnResponse>('POST', `/sessions/${id}/messages`, { message }),
    getSession: (id: string) => request<SessionState>('GET', `/sessions/${id}`),
    finalise: (id: string) =>
      request<{ status: string; analysis_run_id: string }>('POST', `/sessions/${id}/finalise`),
    getReport: (id: string) => request<ReportResponse>('GET', `/sessions/${id}/report`),
  }
}
