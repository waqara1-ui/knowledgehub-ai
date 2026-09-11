type LoginFormProps = {
  onLogin: (username: string, password: string) => void
  error: string
  isLoggingIn: boolean
}

import { useState } from 'react'

function LoginForm({
  onLogin,
  error,
  isLoggingIn,
}: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    if (!username.trim() || !password) {
      return
    }

    onLogin(username, password)
  }

  return (
    <div className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand-top">
          <div className="login-logo-mark">
            <span></span>
            <span></span>
          </div>

          <p className="login-product-name">
            LogLens AI
          </p>
        </div>

        <div className="login-brand-copy">
          <p className="login-eyebrow">
            INCIDENT INTELLIGENCE
          </p>

          <h1>
            Find the signal
            <br />
            inside the noise.
          </h1>

          <p className="login-brand-description">
            Investigate incidents, trace supporting
            evidence, and reason across operational
            knowledge from one focused workspace.
          </p>
        </div>

        <div className="login-system-status">
          <span className="status-dot"></span>

          <div>
            <p>Investigation workspace</p>
            <span>Secure authenticated access</span>
          </div>
        </div>
      </section>

      <section className="login-form-panel">
        <div className="login-form-container">
          <div className="login-heading">
            <p className="login-small-label">
              WORKSPACE ACCESS
            </p>

            <h2>Welcome back</h2>

            <p>
              Sign in to investigate system incidents
              and review operational evidence.
            </p>
          </div>

          <form
            className="login-form"
            onSubmit={handleSubmit}
          >
            <div className="login-field">
              <label htmlFor="username">
                Username
              </label>

              <input
                id="username"
                type="text"
                value={username}
                onChange={(event) =>
                  setUsername(event.target.value)
                }
                placeholder="Enter your username"
                autoComplete="username"
              />
            </div>

            <div className="login-field">
              <label htmlFor="password">
                Password
              </label>

              <input
                id="password"
                type="password"
                value={password}
                onChange={(event) =>
                  setPassword(event.target.value)
                }
                placeholder="Enter your password"
                autoComplete="current-password"
              />
            </div>

            {error && (
              <p className="login-error">
                {error}
              </p>
            )}

            <button
              className="login-submit-button"
              type="submit"
              disabled={
                isLoggingIn ||
                !username.trim() ||
                !password
              }
            >
              <span>
                {isLoggingIn
                  ? 'Signing in...'
                  : 'Enter workspace'}
              </span>

              {!isLoggingIn && (
                <span
                  className="login-button-arrow"
                  aria-hidden="true"
                >
                  →
                </span>
              )}
            </button>
          </form>

          <div className="login-footer">
            <span className="login-footer-line"></span>
            <p>LogLens AI · Incident Response Console</p>
          </div>
        </div>
      </section>
    </div>
  )
}

export default LoginForm