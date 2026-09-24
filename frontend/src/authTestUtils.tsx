/* eslint-disable react-refresh/only-export-components */
/**
 * Test-only helpers for the authenticated shell.
 *
 * These fixtures mirror the backend's default grants so a page test exercises
 * the same permission set a real role receives. They are a copy of
 * `app/security/rbac.py` for the same reason `permissions.ts` is: the server is
 * the authority, and a test that drifts from it would assert a screen rather
 * than a behaviour.
 */

import type { ReactNode } from 'react'
import { AuthProvider } from './auth'
import { createMemoryTokenStorage, installTokenStorage } from './authStorage'
import { PERMISSIONS, WILDCARD } from './permissions'
import type { Identity } from './types'

const CREATED_AT = '2026-09-24T08:00:00Z'

export function identityWith(roles: string[], permissions: string[]): Identity {
  return {
    user_id: `user-${roles.join('-').toLowerCase()}`,
    username: roles.join('-').toLowerCase(),
    email: null,
    status: 'ACTIVE',
    roles,
    permissions,
    created_at: CREATED_AT,
  }
}

/** ADMIN holds the wildcard, so every permission check succeeds. */
export const ADMIN_IDENTITY = identityWith(['ADMIN'], [WILDCARD])

/** OPERATOR runs the incident, workflow, and approval loop. */
export const OPERATOR_IDENTITY = identityWith(
  ['OPERATOR'],
  [
    PERMISSIONS.telemetryRead,
    PERMISSIONS.dashboardRead,
    PERMISSIONS.incidentRead,
    PERMISSIONS.incidentCreate,
    PERMISSIONS.incidentAck,
    PERMISSIONS.incidentInvestigate,
    PERMISSIONS.incidentResolve,
    PERMISSIONS.incidentClose,
    PERMISSIONS.incidentReopen,
    PERMISSIONS.workflowRead,
    PERMISSIONS.workflowStart,
    PERMISSIONS.workflowCancel,
    PERMISSIONS.approvalRead,
    PERMISSIONS.approvalReview,
    PERMISSIONS.workorderRead,
  ],
)

/** VIEWER reads telemetry and decisions, and acts on none of them. */
export const VIEWER_IDENTITY = identityWith(
  ['VIEWER'],
  [
    PERMISSIONS.telemetryRead,
    PERMISSIONS.dashboardRead,
    PERMISSIONS.incidentRead,
    PERMISSIONS.workflowRead,
    PERMISSIONS.approvalRead,
    PERMISSIONS.workorderRead,
  ],
)

/**
 * An operator *without* `approval.review`.
 *
 * Built by subtraction rather than by adding a role, because the interesting
 * case is an identity that may run the workflow but may not decide its output.
 */
export const OPERATOR_WITHOUT_REVIEW = identityWith(
  ['OPERATOR'],
  OPERATOR_IDENTITY.permissions.filter((permission) => permission !== PERMISSIONS.approvalReview),
)

/** Wrap a subtree in a settled session. Omit the identity for an anonymous one. */
export function withAuth(ui: ReactNode, identity: Identity | null = OPERATOR_IDENTITY) {
  return <AuthProvider initialIdentity={identity}>{ui}</AuthProvider>
}

/** Give each test a fresh token store so a token never leaks across cases. */
export function resetAuthStorage(): void {
  installTokenStorage(createMemoryTokenStorage())
}
