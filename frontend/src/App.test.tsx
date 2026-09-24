import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import App from './App'
import { resetAuthStorage } from './authTestUtils'

describe('App', () => {
  beforeEach(() => {
    resetAuthStorage()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('presents the sign-in page to an anonymous visitor', async () => {
    render(<App />)
    expect(screen.getByText('Industrial AI Control Tower')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    // The operational shell is not reachable without a session.
    expect(screen.queryByLabelText('Primary navigation')).not.toBeInTheDocument()
  })
})
