import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

afterEach(() => { vi.unstubAllGlobals() })

describe('API client errors', () => {
  it('preserves 503 capability details without crashing the UI layer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'not_ready', dependencies: { knowledge: 'unavailable', diagnosis: 'loaded' } }), { status: 503, headers: { 'Content-Type': 'application/json' } })))
    await expect(api.ready()).rejects.toMatchObject({ status: 503, code: 'HTTP_503' } satisfies Partial<ApiError>)
  })

  it('preserves 409 conflict code and trace id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'STALE_APPROVAL', message: 'Approval does not match the current plan.', trace_id: 'trace-409' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })))
    await expect(api.decide('approval-1', 'approve', 'operator', 'reviewed')).rejects.toMatchObject({ status: 409, code: 'STALE_APPROVAL', traceId: 'trace-409' } satisfies Partial<ApiError>)
  })

  it('reports backend network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    await expect(api.devices()).rejects.toMatchObject({ status: 0, code: 'NETWORK_ERROR' } satisfies Partial<ApiError>)
  })
})
