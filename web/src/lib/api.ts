// Calls this module's API only (never Core directly — ADR-0002), served by the
// shared plugin host at <base>/api/v1/plugins/ideation/* on the API Gateway
// (ADR-0021). The caller's Cognito id token is sent in the X-Biffo-Founder-Token
// header; the host's group gate verifies it against user_ingress.required_group
// (currently "admin" — owner decision B on biffo-platform-app#70) and the app
// re-checks the same group (require_founder, src/ideation/app.py) before doing
// anything.

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
  title: string
  report: Report | null
}

export interface SessionSummary {
  session_id: string
  title: string
  status: 'gathering' | 'analysing' | 'complete'
  created_at: string
}

export interface TranscriptMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface Agent {
  agent_key: string
  agent_name: string
}

export interface BrainstormIntake {
  target?: string
  geography?: string
  problem?: string
}

export interface BrainstormState {
  session_id: string
  status: string
  title: string
  target: string | null
  geography: string | null
  problem: string | null
  turn_count: number
  max_turns: number
  early_research_turn?: number
  ready?: boolean
  at_ceiling?: boolean
  brief?: BrainstormBrief | null
  gaps?: string[]
  created_at: string
  failure_reason?: string | null
}

export interface BrainstormBrief {
  ready?: boolean
  summary?: string
  what_the_business_wants?: {
    goals?: string
    capabilities_and_assets?: string
    target_customer?: string
  }
  business_problem?: string
  size_and_shape?: {
    who_and_how_many?: string
    cost_and_frequency?: string
    current_workarounds?: string
    boundaries_and_constraints?: string
  }
  gaps?: string[]
}

export interface BrainstormTurn extends BrainstormState {
  reply: string
}

export interface BrainstormOpportunity {
  id: string
  rank: number
  title: string
  pitch: string
  rationale: string | null
  evidence: { url: string; note?: string }[]
}

export interface ResearchFinding {
  signal: string
  why_it_matters: string
  sources: { url: string; note?: string }[]
}

export interface ResearchAngle {
  angle: string
  status: 'succeeded' | 'failed' | 'malformed' | 'never_started' | 'running'
  findings: ResearchFinding[]
}

export type Api = ReturnType<typeof createApi>

// Async on purpose: the token is resolved per request, not snapshotted, so an
// expired one can be swapped for a refreshed one before the call goes out
// (see auth.getFreshIdToken). A synchronous getter is still accepted.
export function createApi(getIdToken: () => string | null | Promise<string | null>) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await getIdToken()
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        // The id token rides Authorization: Bearer (ADR-0021), exactly as
        // the portal calls Core. The API Gateway's Cognito authorizer validates it
        // (audience = the app client id, i.e. the id token), the shared plugin
        // host's group gate reads it to enforce user_ingress.required_group, and
        // this app's require_founder re-verifies it and forwards it to Core.
        ...(token != null ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText)
      throw new ApiError(res.status, detail)
    }
    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  }

  return {
    startSession: (seed_idea: string, challenger_agent_key?: string | null) =>
      request<TurnResponse>('POST', '/sessions', {
        seed_idea,
        ...(challenger_agent_key != null ? { challenger_agent_key } : {}),
      }),
    sendMessage: (id: string, message: string) =>
      request<TurnResponse>('POST', `/sessions/${id}/messages`, { message }),
    getSession: (id: string) => request<SessionState>('GET', `/sessions/${id}`),
    finalise: (id: string) =>
      request<{ status: string; analysis_run_id: string }>('POST', `/sessions/${id}/finalise`),
    deleteSession: (id: string) => request<void>('POST', `/sessions/${id}/delete`),
    getReport: (id: string) => request<ReportResponse>('GET', `/sessions/${id}/report`),
    listSessions: () => request<SessionSummary[]>('GET', '/sessions'),
    getSubmittedIdea: () => request<{ idea: string | null }>('GET', '/submitted-idea'),
    getAgents: () => request<Agent[]>('GET', '/agents'),
    getSessionMessages: (id: string) =>
      request<{ messages: TranscriptMessage[] }>('GET', `/sessions/${id}/messages`),
    listBrainstorms: () => request<BrainstormState[]>('GET', '/brainstorm/sessions'),
    getBrainstormMessages: (id: string) =>
      request<{ messages: TranscriptMessage[] }>('GET', `/brainstorm/sessions/${id}/messages`),
    deleteBrainstorm: (id: string) => request<void>('POST', `/brainstorm/sessions/${id}/delete`),
    startBrainstorm: (intake: BrainstormIntake) =>
      request<BrainstormTurn>('POST', '/brainstorm/sessions', intake),
    sendBrainstormMessage: (id: string, message: string) =>
      request<BrainstormTurn>('POST', `/brainstorm/sessions/${id}/messages`, { message }),
    finaliseBrainstorm: (id: string) =>
      request<BrainstormState>('POST', `/brainstorm/sessions/${id}/finalise`),
    getBrainstorm: (id: string) =>
      request<BrainstormState>('GET', `/brainstorm/sessions/${id}`),
    getBrainstormResearch: (id: string) =>
      request<{ research: ResearchAngle[] }>('GET', `/brainstorm/sessions/${id}/research`),
    getBrainstormOpportunities: (id: string) =>
      request<{ opportunities: BrainstormOpportunity[] }>(
        'GET',
        `/brainstorm/sessions/${id}/opportunities`,
      ),
  }
}
