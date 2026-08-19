import './App.css'
import IncidentCard from './components/IncidentCard'

function App() {
  const incidents = [
  {
    id: 1,
    title: 'Select an Incident',
    severity: 'High',
    status: 'Open',
  },
  {
    id: 2,
    title: 'Another Incident',
    severity: 'Medium',
    status: 'Investigating',
  },
]
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

        {incidents.map((incident) => (
          <IncidentCard
            key={incident.id}
            title={incident.title}
            severity={incident.severity}
            status={incident.status}
          />
        ))}
      </main>
    </div>
  )
}

export default App