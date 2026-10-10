import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

import type { FullConfig } from '@playwright/test'

// Signs the dev test persona in once and writes a Playwright storageState holding
// the shared Cognito session, so the spec runs as a real founder against dev.
//
//   E2E_BASE_URL        origin of the deployed portal (dev URL, from config)
//   E2E_TEST_USERNAME   dev test persona username
//   E2E_TEST_PASSWORD   dev test persona password
//
// The Cognito pool / client come from the portal's own identity document, the same
// source the UI reads at runtime, so nothing about the pool is baked in here. The
// App Client must allow USER_PASSWORD_AUTH. A manually supplied E2E_STORAGE_STATE
// takes precedence and skips this entirely.

export const AUTH_STATE_PATH = 'test-results/.auth/state.json'

interface Identity {
  userPoolId: string
  clientId: string
  region?: string
}

function decodeClaims(jwt: string): Record<string, unknown> {
  const payload = jwt.split('.')[1] ?? ''
  return JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as Record<string, unknown>
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  void config
  if (process.env.E2E_STORAGE_STATE) return
  const base = process.env.E2E_BASE_URL
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD
  if (!base || !username || !password) return

  const idRes = await fetch(new URL('/.well-known/biffo-identity.json', base), {
    cache: 'no-store',
  })
  if (!idRes.ok) throw new Error(`identity document: HTTP ${idRes.status}`)
  const identity = (await idRes.json()) as Identity
  if (!identity.userPoolId || !identity.clientId) throw new Error('identity document incomplete')
  const region = identity.region ?? identity.userPoolId.split('_')[0]

  const authRes = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
    },
    body: JSON.stringify({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: identity.clientId,
      AuthParameters: { USERNAME: username, PASSWORD: password },
    }),
  })
  if (!authRes.ok) throw new Error(`Cognito sign-in as test persona failed: HTTP ${authRes.status}`)
  const result = (await authRes.json()) as {
    AuthenticationResult?: { IdToken: string; AccessToken: string; RefreshToken: string }
  }
  const tokens = result.AuthenticationResult
  if (!tokens) throw new Error('Cognito sign-in returned no tokens (challenge required?)')

  const user = String(decodeClaims(tokens.IdToken)['cognito:username'] ?? username)
  const prefix = `CognitoIdentityServiceProvider.${identity.clientId}`
  const entries: Record<string, string> = {
    [`${prefix}.LastAuthUser`]: user,
    [`${prefix}.${user}.idToken`]: tokens.IdToken,
    [`${prefix}.${user}.accessToken`]: tokens.AccessToken,
    [`${prefix}.${user}.refreshToken`]: tokens.RefreshToken,
    [`${prefix}.${user}.clockDrift`]: '0',
  }
  const state = {
    cookies: [],
    origins: [
      {
        origin: new URL(base).origin,
        localStorage: Object.entries(entries).map(([name, value]) => ({ name, value })),
      },
    ],
  }
  mkdirSync(dirname(AUTH_STATE_PATH), { recursive: true })
  writeFileSync(AUTH_STATE_PATH, JSON.stringify(state))
}
