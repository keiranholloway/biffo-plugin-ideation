import { describe, it, expect } from 'vitest'
import type { CognitoUserSession } from 'amazon-cognito-identity-js'

import { getUserGroups, isFounder, REQUIRED_GROUP } from './roles'

function sessionWithGroups(groups: unknown): CognitoUserSession {
  return {
    getIdToken: () => ({
      getJwtToken: () => 'test-token',
      payload: groups === undefined ? {} : { 'cognito:groups': groups },
    }),
  } as unknown as CognitoUserSession
}

describe('getUserGroups', () => {
  it('reads the cognito:groups claim off the ID token', () => {
    expect(getUserGroups(sessionWithGroups(['founder', 'admin']))).toEqual(['founder', 'admin'])
  })

  it('is empty when the claim is absent (a user in no group at all)', () => {
    expect(getUserGroups(sessionWithGroups(undefined))).toEqual([])
  })

  it('is empty when the claim is not an array', () => {
    expect(getUserGroups(sessionWithGroups('founder'))).toEqual([])
  })

  it('drops non-string entries rather than admitting them', () => {
    expect(getUserGroups(sessionWithGroups(['founder', 42, null]))).toEqual(['founder'])
  })
})

describe('isFounder', () => {
  it('matches the group the manifest declares', () => {
    expect(REQUIRED_GROUP).toBe('founder')
  })

  it('admits a founder', () => {
    expect(isFounder(sessionWithGroups(['founder']))).toBe(true)
  })

  it('refuses a user in no group', () => {
    expect(isFounder(sessionWithGroups([]))).toBe(false)
  })

  it('refuses an admin who is not also a founder', () => {
    // user_ingress.required_group is exactly "founder" — the server would 403
    // an admin-only token, so the client must not pretend otherwise.
    expect(isFounder(sessionWithGroups(['admin']))).toBe(false)
  })

  it('refuses a look-alike group name', () => {
    expect(isFounder(sessionWithGroups(['founders', 'co-founder']))).toBe(false)
  })
})
