import type { CognitoUserSession } from 'amazon-cognito-identity-js'

// ---------------------------------------------------------------------------
// The client-side half of `user_frontend.required_group` (ADR-0018 §2).
//
// This is a UX gate, NOT a security boundary — a static SPA on S3/CloudFront
// cannot check a Cognito group at all, and anything here is editable in
// devtools. The real enforcement is server-side and unchanged by this file:
//
//   1. API Gateway rejects an unauthenticated call to /api/v1/plugins/* (401);
//   2. the shared plugin host's `group_gate` verifies the Cognito JWT against
//      the pool's JWKS and requires `user_ingress.required_group` (403);
//   3. this plugin's own app re-runs `require_group("founder")` per route, and
//      Core owner-scopes every read/write off the forwarded token.
//
// What this file buys is the bounce ADR-0018 §2 says `required_group` provides:
// without it a signed-in non-founder who navigates straight to /ideation/ gets
// the entire chat UI rendered and only discovers they are not allowed when each
// individual request comes back "403: This surface requires the 'founder'
// group." (keiranholloway/biffo-platform-app#4).
//
// GROUP MUST MATCH THE MANIFEST. `biffo.plugin.json` declares
// `user_ingress.required_group: "founder"` — literally that group, not "founder
// or admin". Admitting more here than the server admits just moves the 403 from
// the front door to every button.
// ---------------------------------------------------------------------------

/** The group `biffo.plugin.json` declares for this surface. */
export const REQUIRED_GROUP = 'founder'

const GROUPS_CLAIM = 'cognito:groups'

/** The `cognito:groups` claim off the ID token, or `[]` if absent/malformed. */
export function getUserGroups(session: CognitoUserSession): string[] {
  const payload = session.getIdToken().payload as Record<string, unknown> | undefined
  const groups = payload?.[GROUPS_CLAIM]
  return Array.isArray(groups) ? groups.filter((g): g is string => typeof g === 'string') : []
}

/** Whether this session may use the founder-facing Ideation Engine. */
export function isFounder(session: CognitoUserSession): boolean {
  return getUserGroups(session).includes(REQUIRED_GROUP)
}
