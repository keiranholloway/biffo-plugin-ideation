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
    // Regression for #163: this drifted from the manifest once already — the
    // manifest's user_ingress.required_group moved to "admin" (owner decision B
    // on biffo-platform-app#70) while this constant stayed "founder".
    expect(REQUIRED_GROUP).toBe('admin')
  })

  it('admits an admin who is not also a founder', () => {
    // The exact symptom #70/#163 were filed to fix: groups deliberately
    // excludes "founder".
    expect(isFounder(sessionWithGroups(['admin']))).toBe(true)
  })

  it('refuses a user in no group', () => {
    expect(isFounder(sessionWithGroups([]))).toBe(false)
  })

  it('refuses a founder who is not also an admin', () => {
    // user_ingress.required_group is exactly "admin" — the server would 403 a
    // founder-only token, so the client must not pretend otherwise. This is
    // the case that stayed broken after #162: the manifest already said
    // "admin", but this constant still hardcoded "founder", so a founder-only
    // token kept being admitted here while every real request 403'd.
    expect(isFounder(sessionWithGroups(['founder']))).toBe(false)
  })

  it('refuses a look-alike group name', () => {
    expect(isFounder(sessionWithGroups(['admins', 'super-admin']))).toBe(false)
  })
})
