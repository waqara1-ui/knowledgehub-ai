import './App.css'
import IncidentCard from './components/IncidentCard'
import LoginForm from './components/LoginForm'
import { useEffect, useState } from 'react'
import type { Incident, IncidentListResponse } from './types/Incident'

function App() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [token, setToken] = useState<string | null>(null)
  const [loginError, setLoginError] = useState('')
  const [isLoggingIn, setIsLoggingIn] = useState(false)
  const [isLoadingIncidents, setIsLoadingIncidents] = useState(false)
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [isLoadingSelectedIncident, setIsLoadingSelectedIncident] = useState(false)
  const [selectedIncidentError, setSelectedIncidentError] = useState('')

  function login(username: string, password: string) {
    setLoginError('')
    setIsLoggingIn(true)

    fetch('http://localhost:8000/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        username,
        password,
      }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Invalid username or password')
        }

        return response.json()
      })
      .then((data) => {
        setToken(data.access_token)
      })
      .catch((error) => {
        setLoginError(error.message)
      })
      .finally(() => {
        setIsLoggingIn(false)
      })
  }

  function selectIncident(incidentId: number) {
    if (!token) {
      return
    }

    setSelectedIncidentError('')
    setIsLoadingSelectedIncident(true)

    fetch(`http://localhost:8000/incidents/${incidentId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load incident details')
        }

        return response.json()
      })
      .then((data: Incident) => {
        setSelectedIncident(data)
      })
      .catch((error) => {
        setSelectedIncidentError(error.message)
      })
      .finally(() => {
        setIsLoadingSelectedIncident(false)
      })
  }

  useEffect(() => {
    if (!token) {
      return
    }

    setIsLoadingIncidents(true)

    fetch('http://localhost:8000/incidents?limit=50', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => response.json())
      .then((data: IncidentListResponse) => {
        setIncidents(data.incidents)
      })
      .finally(() => {
        setIsLoadingIncidents(false)
      })
  }, [token])

  if (!token) {
    return (
      <LoginForm
        onLogin={login}
        error={loginError}
        isLoggingIn={isLoggingIn}
      />
    )
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <h2>LogLens AI</h2>

        <nav aria-label="Main navigation">
          <a href="#">Incidents</a>
          <a href="#">Documents</a>
          <a href="#">Analytics</a>
        </nav>
      </aside>

      <main className="main-content">
        <h1>Incident Investigation</h1>
        <p>Investigate and analyze system incidents with AI.</p>

        {isLoadingSelectedIncident ? (
          <p>Loading incident...</p>
        ) : selectedIncidentError ? (
          <p>{selectedIncidentError}</p>
        ) : selectedIncident ? (
          <div className="selected-incident">
            <button onClick={() => setSelectedIncident(null)}>
              Back to incidents
            </button>

            <h2>{selectedIncident.title}</h2>

            {selectedIncident.description && (
              <p>{selectedIncident.description}</p>
            )}

            {selectedIncident.severity && (
              <p>Severity: {selectedIncident.severity}</p>
            )}

            <p>Status: {selectedIncident.status}</p>
          </div>
        ) : isLoadingIncidents ? (
          <p>Loading incidents...</p>
        ) : (
          incidents.map((incident) => (
            <IncidentCard
              key={incident.id}
              title={incident.title}
              description={incident.description}
              severity={incident.severity}
              status={incident.status}
              onSelect={() => selectIncident(incident.id)}
            />
          ))
        )}
      </main>
    </div>
  )
}

export default App