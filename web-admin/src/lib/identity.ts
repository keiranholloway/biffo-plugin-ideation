// Runtime admin identity — pool/client resolved from the admin_app's /identity endpoint.
//
// Unlike the founder UI (served same-origin from the portal's CloudFront and
// can fetch /.well-known/biffo-identity.json), the admin UI is served from the
// plugin host's Lambda (/api/v1/plugins/ideation/admin/*), a different origin.
// So we fetch /identity (same origin as the admin UI itself) instead, which the
// admin_app serves with the same pool/client/region data sourced from env vars.

export interface CoreIdentity {
  userPoolId: string
  clientId: string
  region?: string
}

const IDENTITY_DOCUMENT_PATH = '/identity'

let cached: Promise<CoreIdentity | null> | null = null

function identityFromDocument(data: unknown): CoreIdentity | null {
  if (typeof data !== 'object' || data === null) return null
  const doc = data as Record<string, unknown>
  const userPoolId = typeof doc['userPoolId'] === 'string' ? doc['userPoolId'] : ''
  const clientId = typeof doc['clientId'] === 'string' ? doc['clientId'] : ''
  if (!userPoolId || !clientId) return null
  const identity: CoreIdentity = { userPoolId, clientId }
  if (typeof doc['region'] === 'string') identity.region = doc['region']
  return identity
}

async function fetchCoreIdentity(): Promise<CoreIdentity | null> {
  try {
    const res = await fetch(IDENTITY_DOCUMENT_PATH, { cache: 'no-store' })
    if (res.ok) {
      const identity = identityFromDocument(await res.json())
      if (identity) return identity
    }
  } catch {
    // Network error or fetch unavailable — fall through to null.
  }
  console.warn(
    `[biffo] could not resolve the admin identity document at ${IDENTITY_DOCUMENT_PATH}; ` +
      'treating the visitor as signed out.',
  )
  return null
}

/** Resolve admin's Cognito identity at runtime. Memoised; null when unreachable. */
export function resolveCoreIdentity(): Promise<CoreIdentity | null> {
  cached ??= fetchCoreIdentity()
  return cached
}

/** Test-only: clear the memoised resolution. */
export function __resetCoreIdentityForTests(): void {
  cached = null
}
