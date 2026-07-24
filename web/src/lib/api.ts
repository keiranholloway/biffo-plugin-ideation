// Calls this module's API only (never Core directly — ADR-0002), served by the
// shared plugin host at <base>/api/v1/plugins/ideation/* on the API Gateway
// (ADR-0021). The founder's Cognito id token is sent in the X-Biffo-Founder-Token
// header; the host's group gate verifies it (founder group) and the app re-checks
// it (require_group("founder")) before doing anything.

const API_BASE = '/api/v1/plugins/ideation'

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
        // The founder id token rides Authorization: Bearer (ADR-0021), exactly as
        // the portal calls Core. The API Gateway's Cognito authorizer validates it
        // (audience = the app client id, i.e. the id token), the shared plugin
        // host's group gate reads it to enforce the founder group, and this app's
        // require_group("founder") re-verifies it and forwards it to Core.
        ...(token != null ? { Authorization: `Bearer ${token}` } : {}),
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
