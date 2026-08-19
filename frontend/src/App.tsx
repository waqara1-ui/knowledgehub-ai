import './App.css'
import IncidentCard from './components/IncidentCard'
import { useEffect, useState } from 'react'
import type { Incident, IncidentListResponse } from './types/Incident'

function App() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [token, setToken] = useState<string | null>(null)

  // Temporary login function
  function login() {
    fetch('http://localhost:8000/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        username: 'loglens_test',
        password: 'TestPassword123!',
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        setToken(data.access_token)
      })
  }

  // Fetch incidents after we have a token
  useEffect(() => {
    if (!token) {
      return
    }
    fetch('http://localhost:8000/incidents?limit=50', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => response.json())
      .then((data: IncidentListResponse) => {
        setIncidents(data.incidents)
      })
  }, [token])

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

        <button onClick={login}>Login</button>

        {incidents.map((incident) => (
          <IncidentCard
            key={incident.id}
            title={incident.title}
            description={incident.description}
            severity={incident.severity}
            status={incident.status}
          />
        ))}
      </main>
    </div>
  )
}

export default App