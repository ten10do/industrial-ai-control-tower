/**
 * Where the access token lives in the browser.
 *
 * Three decisions are recorded here rather than scattered through the app.
 *
 * 1. **`sessionStorage`, not `localStorage`.** An operator token that survives a
 *    browser restart survives on a shared plant terminal too. The session scope
 *    bounds the exposure of a token that is, by design, a bearer credential with
 *    no revocation list.
 * 2. **Storage is behind an interface.** Every read and write goes through
 *    `TokenStorage`, so the app never touches a Web Storage object directly and
 *    tests can substitute a deterministic store instead of asserting on jsdom
 *    internals.
 * 3. **Failures degrade to memory.** Private-mode and blocked-storage browsers
 *    throw on access. Falling back to an in-memory store means the session still
 *    works for the current tab, which is strictly better than a login page that
 *    cannot complete a sign-in.
 *
 * The token is never logged, never placed in a URL, and never rendered.
 */

export const AUTH_TOKEN_KEY = 'control-tower.access-token'

export interface TokenStorage {
  read(): string | null
  write(token: string): void
  clear(): void
}

/** Build a storage over any Web Storage implementation, or memory if absent. */
export function createTokenStorage(backing: Storage | null): TokenStorage {
  if (backing === null) return createMemoryTokenStorage()
  return {
    read: () => {
      try {
        const value = backing.getItem(AUTH_TOKEN_KEY)
        return value && value.length > 0 ? value : null
      } catch {
        return null
      }
    },
    write: (token: string) => {
      try {
        backing.setItem(AUTH_TOKEN_KEY, token)
      } catch {
        /* Blocked or full storage: the session still lives in memory. */
      }
    },
    clear: () => {
      try {
        backing.removeItem(AUTH_TOKEN_KEY)
      } catch {
        /* Nothing to remove if storage is unavailable. */
      }
    },
  }
}

/** A store that forgets on reload, used when Web Storage is unusable. */
export function createMemoryTokenStorage(): TokenStorage {
  let token: string | null = null
  return {
    read: () => token,
    write: (next: string) => {
      token = next
    },
    clear: () => {
      token = null
    },
  }
}

function browserSessionStorage(): Storage | null {
  try {
    const probe = '__control_tower_probe__'
    window.sessionStorage.setItem(probe, '1')
    window.sessionStorage.removeItem(probe)
    return window.sessionStorage
  } catch {
    return null
  }
}

/** The storage the application uses. Replaceable by tests via `installTokenStorage`. */
let active: TokenStorage = createTokenStorage(
  typeof window === 'undefined' ? null : browserSessionStorage(),
)

/**
 * Point the module at a different store.
 *
 * Named `install*` rather than `use*` on purpose: this is a plain function with
 * a side effect, not a React hook, and a `use` prefix would both mislead readers
 * and trip the rules-of-hooks lint rule.
 */
export function installTokenStorage(storage: TokenStorage): void {
  active = storage
  notify()
}

export function getToken(): string | null {
  return active.read()
}

export function setToken(token: string): void {
  active.write(token)
  notify()
}

export function clearToken(): void {
  active.clear()
  notify()
}

type Listener = () => void

const listeners = new Set<Listener>()

/**
 * Observe token changes.
 *
 * This is what lets a rejected request anywhere in the app collapse the session
 * in one place: the API layer clears the token on a 401, and the provider
 * subscribed here returns to the anonymous state, so the route guard sends the
 * operator to the login page instead of leaving a shell that silently fails
 * every panel.
 */
export function subscribeToToken(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function notify(): void {
  for (const listener of [...listeners]) listener()
}
