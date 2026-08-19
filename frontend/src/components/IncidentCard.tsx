type IncidentCardProps = {
  title: string
  description?: string
  severity?: string
  status: string
}

function IncidentCard({ title, description, severity, status }: IncidentCardProps) {
  return (
    <div className="incident-card">
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {severity && <p>Severity: {severity}</p>}
      <p>Status: {status}</p>
    </div>
  )
}

export default IncidentCard