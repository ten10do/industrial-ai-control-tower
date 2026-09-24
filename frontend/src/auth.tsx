/* eslint-disable react-refresh/only-export-components */
/**
 * The session the operator interface is acting under.
 *
 * The backend is the authority. This provider holds the *result* of asking it
 * who the caller is, and nothing here is trusted by the server: a hidden button
 * is a courtesy, and every route re-checks the same permission.
 *
 * Three states, and the distinction matters.
 *
 * ``anonymous``  no usable credential is held, so the guard sends the operator
 *                to the login page.
 * ``restoring``  a token survived a reload and ``/auth/me`` is in flight. The
 *                interface must not render a shell yet, because a shell that
 *                paints before the identity is known would flash actions the
 *                operator may not have.
 * ``authenticated`` the backend confirmed the identity, and `permissions` is
 *                what it reported *now*. Permissions are re-read on every page
 *                load rather than decoded from the token, so revoking a grant
 *                takes effect on the next request.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { api } from './api'
import { clearToken, getToken, setToken, subscribeToToken } from './authStorage'
import { permissionGranted } from './permissions'
import type { Identity } from './types'

export type AuthStatus = 'anonymous' | 'restoring' | 'authenticated'

export interface AuthValue {
  status: AuthStatus
  identity: Identity | null
  hasPermission(permission: string): boolean
  hasAnyPermission(permissions: readonly string[]): boolean
  login(username: string, password: string): Promise<void>
  logout(): void
}

const AuthContext = createContext<AuthValue | null>(null)

/**
 * Read the current session.
 *
 * Throws when no provider is present. A silent anonymous default would let a
 * permission-gated page render as if it were ungated, which is exactly the
 * failure this phase exists to prevent.
 */
export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth requires an <AuthProvider>.')
  }
  return value
}

export function AuthProvider({
  children,
  initialIdentity,
}: {
  children: ReactNode
  /**
   * Pre-resolved identity. Omitted by the application, which always asks the
   * backend; supplied by tests that need a settled session without a round trip.
   */
  initialIdentity?: Identity | null
}) {
  const [identity, setIdentity] = useState<Identity | null>(initialIdentity ?? null)
  const [status, setStatus] = useState<AuthStatus>(() => {
    if (initialIdentity) return 'authenticated'
    return getToken() ? 'restoring' : 'anonymous'
  })

  useEffect(() => {
    if (initialIdentity !== undefined) return undefined
    let cancelled = false
    if (!getToken()) {
      setIdentity(null)
      setStatus('anonymous')
      return undefined
    }
    setStatus('restoring')
    api
      .me()
      .then((restored) => {
        if (cancelled) return
        setIdentity(restored)
        setStatus('authenticated')
      })
      .catch(() => {
        if (cancelled) return
        clearToken()
        setIdentity(null)
        setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [initialIdentity])

  useEffect(
    () =>
      subscribeToToken(() => {
        if (getToken() === null) {
          setIdentity(null)
          setStatus('anonymous')
        }
      }),
    [],
  )

  const login = useCallback(async (username: string, password: string) => {
    const issued = await api.login(username, password)
    setToken(issued.access_token)
    try {
      const restored = await api.me()
      setIdentity(restored)
      setStatus('authenticated')
    } catch (error) {
      clearToken()
      setIdentity(null)
      setStatus('anonymous')
      throw error
    }
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setIdentity(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo<AuthValue>(() => {
    const hasPermission = (permission: string) =>
      identity !== null && permissionGranted(identity.permissions, permission)
    return {
      status,
      identity,
      hasPermission,
      hasAnyPermission: (permissions: readonly string[]) => permissions.some(hasPermission),
      login,
      logout,
    }
  }, [identity, status, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/**
 * Route guard for the authenticated shell.
 *
 * Used as a layout route, so it renders ``<Outlet />`` when the session is real
 * and redirects otherwise. The attempted location is carried in router state so
 * a sign-in returns the operator to where they were, rather than to a default
 * page they did not ask for.
 */
export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'restoring') {
    return (
      <main className="main-content">
        <div className="panel-state" aria-live="polite">
          Restoring session…
        </div>
      </main>
    )
  }
  if (status !== 'authenticated') {
    return (
      <Navigate to="/login" state={{ from: `${location.pathname}${location.search}` }} replace />
    )
  }
  return <Outlet />
}
