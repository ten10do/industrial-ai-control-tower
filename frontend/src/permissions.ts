/**
 * Permission names, mirrored from the backend vocabulary.
 *
 * The backend owns this vocabulary (`app/security/rbac.py`) and enforces it on
 * every protected route. This file exists so the interface can *hide* an action
 * the caller would only be refused for, and nothing more. It is a copy, not an
 * authority: if the two ever disagree, the server is right and the user sees a
 * 403 rather than a broken screen.
 *
 * `WILDCARD` mirrors the backend rule exactly. It is an exact-match grant, not
 * a prefix pattern, so a permission literally named `incident.*` could never be
 * created by accident and mistaken for "all incident permissions".
 */

export const WILDCARD = '*'

export const PERMISSIONS = {
  telemetryRead: 'telemetry.read',
  dashboardRead: 'dashboard.read',
  incidentRead: 'incident.read',
  incidentCreate: 'incident.create',
  incidentAck: 'incident.ack',
  incidentInvestigate: 'incident.investigate',
  incidentResolve: 'incident.resolve',
  incidentClose: 'incident.close',
  incidentReopen: 'incident.reopen',
  workflowRead: 'workflow.read',
  workflowStart: 'workflow.start',
  workflowCancel: 'workflow.cancel',
  approvalRead: 'approval.read',
  approvalReview: 'approval.review',
  workorderRead: 'workorder.read',
  userManage: 'user.manage',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]

/** Whether a permission set grants `permission`, wildcard included. */
export function permissionGranted(permissions: readonly string[], permission: string): boolean {
  return permissions.includes(WILDCARD) || permissions.includes(permission)
}
