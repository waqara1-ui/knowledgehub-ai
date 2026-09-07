type IncidentCardProps = {
  title: string
  description: string | null
  severity: string | null
  status: string
  onSelect: () => void
}

function IncidentCard({ title, description, severity, status, onSelect, }: IncidentCardProps) {
  return (
    <div className="incident-card" onClick={onSelect}>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {severity && <p>Severity: {severity}</p>}
      <p>Status: {status}</p>
    </div>
  )
}

export default IncidentCard