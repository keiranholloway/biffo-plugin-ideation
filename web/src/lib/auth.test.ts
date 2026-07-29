import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CognitoUserSession } from 'amazon-cognito-identity-js'

// Stand-ins for the two things auth.ts talks to. The pool is mocked at the
// module boundary so these tests exercise auth.ts's own logic — which keys it
// asks for, and how often — rather than re-testing amazon-cognito-identity-js.
const getCurrentUser = vi.fn()
const resolveCoreIdentity = vi.fn()

vi.mock('amazon-cognito-identity-js', () => ({
  CognitoUserPool: class {
    constructor(public readonly data: { UserPoolId: string; ClientId: string }) {}
    getCurrentUser() {
      return getCurrentUser()
    }
  },
}))

vi.mock('./identity', () => ({
  resolveCoreIdentity: () => resolveCoreIdentity(),
}))

const { __resetUserPoolForTests, getCurrentSession, getFreshIdToken } = await import('./auth')

/**
 * What the real library hands back: an IMMUTABLE snapshot. `getIdToken()` on a
 * `CognitoUserSession` returns the same `CognitoIdToken` forever, so the JWT
 * inside one of these never changes — which is the whole reason a caller must
 * not hold on to it.
 */
function snapshot(jwt: string): CognitoUserSession {
  const idToken = { getJwtToken: () => jwt, payload: {} }
  return {
    isValid: () => true,
    getIdToken: () => idToken,
  } as unknown as CognitoUserSession
}

describe('getFreshIdToken', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    __resetUserPoolForTests()
    resolveCoreIdentity.mockResolvedValue({
      userPoolId: 'eu-west-1_live',
      clientId: 'live-client',
    })
  })

  it('re-resolves through the pool on every call, so a refreshed token replaces a lapsed one', async () => {
    // `stored` stands for what localStorage holds. The library rotates it when
    // the cached ID token expires and the refresh token buys a new one — the
    // caller sees that only if it asks again.
    let stored = snapshot('jwt-before-refresh')
    getCurrentUser.mockReturnValue({
      getSession: (cb: (e: Error | null, s: CognitoUserSession | null) => void) => cb(null, stored),
    })

    expect(await getFreshIdToken()).toBe('jwt-before-refresh')

    stored = snapshot('jwt-after-refresh')

    expect(await getFreshIdToken()).toBe('jwt-after-refresh')
    // Two resolutions, not one memoised answer.
    expect(getCurrentUser).toHaveBeenCalledTimes(2)
  })

  it('is null when there is no session, rather than throwing', async () => {
    getCurrentUser.mockReturnValue(null)
    expect(await getFreshIdToken()).toBeNull()
  })

  it('is null when the pool cannot be resolved (identity document unreachable)', async () => {
    resolveCoreIdentity.mockResolvedValue(null)
    expect(await getFreshIdToken()).toBeNull()
    expect(getCurrentUser).not.toHaveBeenCalled()
  })

  it('only ever asks the pool built from the runtime identity document', async () => {
    // The claim #70 rests on and #69 disputed: the pool is constructed from the
    // resolved identity and the library scopes every storage read by that
    // Client ID, so no other pool's credentials can be reached from here.
    getCurrentUser.mockReturnValue({
      getSession: (cb: (e: Error | null, s: CognitoUserSession | null) => void) =>
        cb(null, snapshot('jwt')),
    })
    await getCurrentSession()
    expect(resolveCoreIdentity).toHaveBeenCalled()
  })
})
