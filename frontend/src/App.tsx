import './App.css'
import IncidentCard from './components/IncidentCard'
import LoginForm from './components/LoginForm'
import { useEffect, useState } from 'react'
import type { Incident, IncidentListResponse } from './types/Incident'
import type { Document, DocumentListResponse } from './types/Document'
import type { User } from './types/User'

type AskResponse = {
  incident_id: number
  question: string
  answer: string
  message?: string
}

function App() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [token, setToken] = useState<string | null>(null)

  const [loginError, setLoginError] = useState('')
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  const [user, setUser] = useState<User | null>(null)

  const [isLoadingIncidents, setIsLoadingIncidents] = useState(false)

  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [isLoadingSelectedIncident, setIsLoadingSelectedIncident] =
    useState(false)
  const [selectedIncidentError, setSelectedIncidentError] = useState('')

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [askError, setAskError] = useState('')
  const [isAsking, setIsAsking] = useState(false)

  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(false)
  const [documentsError, setDocumentsError] = useState('')

  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [uploadMessage, setUploadMessage] = useState('')

  const [currentPage, setCurrentPage] = useState<
    'incidents' | 'documents' | 'analytics'
  >('incidents')

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

    setQuestion('')
    setAnswer('')
    setAskError('')

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

  function askIncident() {
    if (!token || !selectedIncident) {
      return
    }

    if (!question.trim()) {
      setAskError('Please enter a question')
      return
    }

    setAskError('')
    setAnswer('')
    setIsAsking(true)

    const formData = new FormData()
    formData.append('question', question)

    fetch(
      `http://localhost:8000/incidents/${selectedIncident.id}/ask`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      },
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not get an AI response')
        }

        return response.json()
      })
      .then((data: AskResponse) => {
        setAnswer(data.answer)
      })
      .catch((error) => {
        setAskError(error.message)
      })
      .finally(() => {
        setIsAsking(false)
      })
  }

  function backToIncidents() {
    setSelectedIncident(null)
    setQuestion('')
    setAnswer('')
    setAskError('')
  }

  function goToPage(page: 'incidents' | 'documents' | 'analytics') {
    setCurrentPage(page)

    if (page !== 'incidents') {
      setSelectedIncident(null)
      setQuestion('')
      setAnswer('')
      setAskError('')
    }
  }

  function loadDocuments() {
    if (!token) {
      return
    }

    setIsLoadingDocuments(true)
    setDocumentsError('')

    fetch('http://localhost:8000/documents', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load documents')
        }

        return response.json()
      })
      .then((data: DocumentListResponse) => {
        setDocuments(data.documents)
      })
      .catch((error) => {
        setDocumentsError(error.message)
      })
      .finally(() => {
        setIsLoadingDocuments(false)
      })
  }

  function uploadDocument() {
    if (!token) {
      return
    }

    if (!uploadTitle.trim()) {
      setUploadError('Please enter a document title')
      return
    }

    if (!uploadFile) {
      setUploadError('Please choose a file')
      return
    }

    setUploadError('')
    setUploadMessage('')
    setIsUploading(true)

    const formData = new FormData()
    formData.append('title', uploadTitle)
    formData.append('file', uploadFile)

    fetch('http://localhost:8000/admin/upload', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    })
      .then(async (response) => {
        const data = await response.json()

        if (!response.ok) {
          throw new Error(data.detail || 'Could not upload document')
        }

        return data
      })
      .then((data) => {
        setUploadMessage(`${data.title} uploaded successfully`)
        setUploadTitle('')
        setUploadFile(null)

        loadDocuments()
      })
      .catch((error) => {
        setUploadError(error.message)
      })
      .finally(() => {
        setIsUploading(false)
      })
  }

  useEffect(() => {
    if (!token) {
      return
    }

    fetch('http://localhost:8000/me', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load user')
        }

        return response.json()
      })
      .then((data: User) => {
        setUser(data)
      })
      .catch((error) => {
        console.error(error)
      })
  }, [token])

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
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load incidents')
        }

        return response.json()
      })
      .then((data: IncidentListResponse) => {
        setIncidents(data.incidents)
      })
      .finally(() => {
        setIsLoadingIncidents(false)
      })
  }, [token])

  useEffect(() => {
    if (!token || currentPage !== 'documents') {
      return
    }

    loadDocuments()
  }, [token, currentPage])

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
          <button
            type="button"
            onClick={() => goToPage('incidents')}
          >
            Incidents
          </button>

          <button
            type="button"
            onClick={() => goToPage('documents')}
          >
            Documents
          </button>

          <button
            type="button"
            onClick={() => goToPage('analytics')}
          >
            Analytics
          </button>
        </nav>
      </aside>

      <main className="main-content">
        {currentPage === 'incidents' && (
          <>
            <h1>Incident Investigation</h1>
            <p>Investigate and analyze system incidents with AI.</p>

            {isLoadingSelectedIncident ? (
              <p>Loading incident...</p>
            ) : selectedIncidentError ? (
              <p>{selectedIncidentError}</p>
            ) : selectedIncident ? (
              <div className="selected-incident">
                <button
                  type="button"
                  onClick={backToIncidents}
                >
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

                <label htmlFor="incident-question">
                  Ask about this incident
                </label>

                <input
                  id="incident-question"
                  type="text"
                  placeholder="What caused this incident?"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                />

                <button
                  type="button"
                  onClick={askIncident}
                  disabled={isAsking}
                >
                  {isAsking ? 'Investigating...' : 'Ask AI'}
                </button>

                {askError && (
                  <p className="ask-error">{askError}</p>
                )}

                {answer && (
                  <div className="ai-answer">
                    <h3>AI Investigation</h3>
                    <p>{answer}</p>
                  </div>
                )}
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
          </>
        )}

        {currentPage === 'documents' && (
          <>
            <h1>Documents</h1>
            <p>View and manage documents used by LogLens AI.</p>

            {user?.is_admin && (
              <div className="upload-section">
                <h2>Upload Document</h2>

                <label htmlFor="document-title">
                  Document title
                </label>

                <input
                  id="document-title"
                  type="text"
                  placeholder="Platform Incident Runbook"
                  value={uploadTitle}
                  onChange={(event) => setUploadTitle(event.target.value)}
                />

                <label htmlFor="document-file">
                  Choose file
                </label>

                <input
                  id="document-file"
                  type="file"
                  accept=".pdf,.txt,.md,.log,.jsonl,.ndjson"
                  onChange={(event) => {
                    const file = event.target.files?.[0] || null
                    setUploadFile(file)
                  }}
                />

                <button
                  type="button"
                  onClick={uploadDocument}
                  disabled={isUploading}
                >
                  {isUploading ? 'Uploading...' : 'Upload Document'}
                </button>

                {uploadError && (
                  <p className="upload-error">
                    {uploadError}
                  </p>
                )}

                {uploadMessage && (
                  <p className="upload-success">
                    {uploadMessage}
                  </p>
                )}
              </div>
            )}

            {user && !user.is_admin && (
              <p>
                You are signed in as a standard user. Document uploads
                require administrator access.
              </p>
            )}

            {isLoadingDocuments ? (
              <p>Loading documents...</p>
            ) : documentsError ? (
              <p>{documentsError}</p>
            ) : documents.length === 0 ? (
              <p>No documents found.</p>
            ) : (
              documents.map((document) => (
                <div
                  key={document.id}
                  className="document-card"
                >
                  <h3>{document.title}</h3>
                  <p>Type: {document.type}</p>
                  <p>Status: {document.status}</p>

                  <p>
                    Uploaded:{' '}
                    {new Date(document.uploaded_at).toLocaleString()}
                  </p>

                  {document.chunk_count !== null && (
                    <p>
                      Chunks: {document.chunk_count}
                    </p>
                  )}
                </div>
              ))
            )}
          </>
        )}

        {currentPage === 'analytics' && (
          <>
            <h1>Analytics</h1>
            <p>Review incident and investigation analytics.</p>
          </>
        )}
      </main>
    </div>
  )
}

export default App