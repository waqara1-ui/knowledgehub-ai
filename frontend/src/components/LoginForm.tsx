import { useState } from 'react'

type LoginFormProps = {
  onLogin: (username: string, password: string) => void
  error: string
}

function LoginForm({ onLogin, error }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onLogin(username, password)
  }

  return (
    <div className="login-form">
      <h1>Welcome to LogLens AI</h1>
      <p>Sign in to investigate system incidents.</p>

      <form onSubmit={handleSubmit}>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          type="text"
          placeholder="Enter your username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          placeholder="Enter your password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <button type="submit">Sign In</button>

        {error && <p className="login-error">{error}</p>}
      </form>
    </div>
  )
}

export default LoginForm