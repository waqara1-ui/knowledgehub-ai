import { useEffect, useState } from 'react'
import './App.css'

import IncidentCard from './components/IncidentCard'
import LoginForm from './components/LoginForm'

import type { Incident, IncidentListResponse } from './types/Incident'
import type { Document, DocumentListResponse } from './types/Document'
import type { User } from './types/User'
import type { AnalyticsSummary } from './types/Analytics'
import type { InvestigationResponse } from './types/Investigation'

function App() {
  const [token, setToken] = useState<string | null>(
    localStorage.getItem('token')
  )

  const [user, setUser] = useState<User | null>(null)

  const [loginError, setLoginError] = useState('')
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  const [currentPage, setCurrentPage] = useState<
    'incidents' | 'documents' | 'analytics'
  >('incidents')

  const [incidents, setIncidents] = useState<Incident[]>([])
  const [isLoadingIncidents, setIsLoadingIncidents] = useState(false)
  const [incidentsError, setIncidentsError] = useState('')

  const [selectedIncident, setSelectedIncident] =
    useState<Incident | null>(null)

  const [
    isLoadingSelectedIncident,
    setIsLoadingSelectedIncident,
  ] = useState(false)

  const [selectedIncidentError, setSelectedIncidentError] =
    useState('')

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [isAsking, setIsAsking] = useState(false)
  const [askError, setAskError] = useState('')

  const [
    investigationResult,
    setInvestigationResult,
  ] = useState<InvestigationResponse | null>(null)

  const [isSubmittingFeedback, setIsSubmittingFeedback] =
    useState(false)

  const [feedbackError, setFeedbackError] = useState('')
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [selectedFeedback, setSelectedFeedback] =
    useState<boolean | null>(null)

  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoadingDocuments, setIsLoadingDocuments] =
    useState(false)
  const [documentsError, setDocumentsError] = useState('')

  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [uploadMessage, setUploadMessage] = useState('')

  const [analytics, setAnalytics] =
    useState<AnalyticsSummary | null>(null)

  const [isLoadingAnalytics, setIsLoadingAnalytics] =
    useState(false)

  const [analyticsError, setAnalyticsError] = useState('')

  function login(username: string, password: string) {
    setIsLoggingIn(true)
    setLoginError('')

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
        localStorage.setItem('token', data.access_token)
        setToken(data.access_token)
      })
      .catch((error) => {
        setLoginError(error.message)
      })
      .finally(() => {
        setIsLoggingIn(false)
      })
  }

  function logout() {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)

    setIncidents([])
    setDocuments([])
    setAnalytics(null)

    setSelectedIncident(null)
    setAnswer('')
    setQuestion('')
    setInvestigationResult(null)

    setFeedbackError('')
    setFeedbackMessage('')
    setSelectedFeedback(null)

    setCurrentPage('incidents')
  }

  function selectIncident(incidentId: number) {
    if (!token) {
      return
    }

    setIsLoadingSelectedIncident(true)
    setSelectedIncidentError('')

    setAnswer('')
    setQuestion('')
    setAskError('')
    setInvestigationResult(null)

    setFeedbackError('')
    setFeedbackMessage('')
    setSelectedFeedback(null)

    fetch(`http://localhost:8000/incidents/${incidentId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load incident')
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

  function backToIncidents() {
    setSelectedIncident(null)
    setSelectedIncidentError('')
    setAnswer('')
    setQuestion('')
    setAskError('')
    setInvestigationResult(null)

    setFeedbackError('')
    setFeedbackMessage('')
    setSelectedFeedback(null)
  }

  function askIncident(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!token || !selectedIncident || !question.trim()) {
      return
    }

    setIsAsking(true)
    setAskError('')
    setAnswer('')
    setInvestigationResult(null)

    setFeedbackError('')
    setFeedbackMessage('')
    setSelectedFeedback(null)

    const formData = new FormData()
    formData.append('question', question)

    fetch(
      `http://localhost:8000/incidents/${selectedIncident.id}/ask?top_k_chunks=5`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not generate investigation response')
        }

        return response.json()
      })
      .then((data: InvestigationResponse) => {
        setAnswer(data.answer)
        setInvestigationResult(data)
      })
      .catch((error) => {
        setAskError(error.message)
      })
      .finally(() => {
        setIsAsking(false)
      })
  }

  function submitFeedback(isHelpful: boolean) {
    if (!token || !investigationResult) {
      return
    }

    setIsSubmittingFeedback(true)
    setFeedbackError('')
    setFeedbackMessage('')

    fetch('http://localhost:8000/feedback', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question_log_id: investigationResult.question_log_id,
        is_helpful: isHelpful,
        feedback_text: '',
      }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not submit feedback')
        }

        return response.json()
      })
      .then(() => {
        setSelectedFeedback(isHelpful)

        setFeedbackMessage(
          isHelpful
            ? 'Thanks for the feedback!'
            : 'Thanks — your feedback was recorded.'
        )
      })
      .catch((error) => {
        setFeedbackError(error.message)
      })
      .finally(() => {
        setIsSubmittingFeedback(false)
      })
  }

  function goToPage(
    page: 'incidents' | 'documents' | 'analytics'
  ) {
    setCurrentPage(page)

    setSelectedIncident(null)
    setSelectedIncidentError('')

    setQuestion('')
    setAnswer('')
    setAskError('')
    setInvestigationResult(null)

    setFeedbackError('')
    setFeedbackMessage('')
    setSelectedFeedback(null)
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

  function uploadDocument(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    if (!token || !uploadFile || !uploadTitle.trim()) {
      return
    }

    setIsUploading(true)
    setUploadError('')
    setUploadMessage('')

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
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not upload document')
        }

        return response.json()
      })
      .then((data) => {
        setUploadMessage(
          `${data.title ?? uploadTitle} uploaded successfully`
        )

        setUploadTitle('')
        setUploadFile(null)

        const fileInput = document.getElementById(
          'document-file'
        ) as HTMLInputElement | null

        if (fileInput) {
          fileInput.value = ''
        }

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
      .catch(() => {
        localStorage.removeItem('token')
        setToken(null)
        setUser(null)
      })
  }, [token])

  useEffect(() => {
    if (!token || currentPage !== 'incidents') {
      return
    }

    setIsLoadingIncidents(true)
    setIncidentsError('')

    fetch('http://localhost:8000/incidents', {
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
      .catch((error) => {
        setIncidentsError(error.message)
      })
      .finally(() => {
        setIsLoadingIncidents(false)
      })
  }, [token, currentPage])

  useEffect(() => {
    if (!token || currentPage !== 'documents') {
      return
    }

    loadDocuments()
  }, [token, currentPage])

  useEffect(() => {
    if (!token || currentPage !== 'analytics') {
      return
    }

    setIsLoadingAnalytics(true)
    setAnalyticsError('')

    fetch('http://localhost:8000/analytics/summary', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Could not load analytics')
        }

        return response.json()
      })
      .then((data: AnalyticsSummary) => {
        setAnalytics(data)
      })
      .catch((error) => {
        setAnalyticsError(error.message)
      })
      .finally(() => {
        setIsLoadingAnalytics(false)
      })
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

        <nav>
          <button
            className={
              currentPage === 'incidents'
                ? 'nav-button active'
                : 'nav-button'
            }
            onClick={() => goToPage('incidents')}
          >
            Incidents
          </button>

          <button
            className={
              currentPage === 'documents'
                ? 'nav-button active'
                : 'nav-button'
            }
            onClick={() => goToPage('documents')}
          >
            Documents
          </button>

          <button
            className={
              currentPage === 'analytics'
                ? 'nav-button active'
                : 'nav-button'
            }
            onClick={() => goToPage('analytics')}
          >
            Analytics
          </button>
        </nav>

        <div className="sidebar-bottom">
          {user && (
            <p className="signed-in-user">
              Signed in as {user.username}
            </p>
          )}

          <button className="logout-button" onClick={logout}>
            Log Out
          </button>
        </div>
      </aside>

      <main className="main-content">
        {currentPage === 'incidents' && (
          <>
            {isLoadingSelectedIncident ? (
              <p>Loading incident...</p>
            ) : selectedIncidentError ? (
              <p className="error-message">
                {selectedIncidentError}
              </p>
            ) : selectedIncident ? (
              <>
                <button
                  className="back-button"
                  onClick={backToIncidents}
                >
                  ← Back to incidents
                </button>

                <h1>{selectedIncident.title}</h1>

                {selectedIncident.description && (
                  <p>{selectedIncident.description}</p>
                )}

                <div className="incident-details">
                  <p>
                    <strong>Status:</strong>{' '}
                    {selectedIncident.status}
                  </p>

                  {selectedIncident.severity && (
                    <p>
                      <strong>Severity:</strong>{' '}
                      {selectedIncident.severity}
                    </p>
                  )}

                  <p>
                    <strong>Created:</strong>{' '}
                    {new Date(
                      selectedIncident.created_at
                    ).toLocaleString()}
                  </p>
                </div>

                <section className="investigation-section">
                  <h2>AI Investigation</h2>

                  <form
                    className="investigation-form"
                    onSubmit={askIncident}
                  >
                    <label htmlFor="incident-question">
                      Ask a question about this incident
                    </label>

                    <textarea
                      id="incident-question"
                      value={question}
                      onChange={(event) =>
                        setQuestion(event.target.value)
                      }
                      placeholder="Example: What is the likely cause of this timeout?"
                      rows={4}
                    />

                    <button
                      type="submit"
                      disabled={isAsking || !question.trim()}
                    >
                      {isAsking
                        ? 'Investigating...'
                        : 'Ask AI'}
                    </button>
                  </form>

                  {askError && (
                    <p className="error-message">{askError}</p>
                  )}

                  {answer && (
                    <div className="answer-card">
                      <h3>Answer</h3>
                      <p>{answer}</p>

                      {investigationResult && (
                        <p className="grounding-status">
                          {investigationResult.grounded
                            ? 'Grounded in retrieved runbook context'
                            : 'Response was not grounded in retrieved context'}
                        </p>
                      )}

                      {investigationResult && (
                        <div className="feedback-section">
                          <p>Was this answer helpful?</p>

                          <div className="feedback-buttons">
                            <button
                              type="button"
                              className={
                                selectedFeedback === true
                                  ? 'feedback-button selected'
                                  : 'feedback-button'
                              }
                              disabled={isSubmittingFeedback}
                              onClick={() =>
                                submitFeedback(true)
                              }
                            >
                              Helpful
                            </button>

                            <button
                              type="button"
                              className={
                                selectedFeedback === false
                                  ? 'feedback-button selected'
                                  : 'feedback-button'
                              }
                              disabled={isSubmittingFeedback}
                              onClick={() =>
                                submitFeedback(false)
                              }
                            >
                              Not Helpful
                            </button>
                          </div>

                          {feedbackMessage && (
                            <p className="success-message">
                              {feedbackMessage}
                            </p>
                          )}

                          {feedbackError && (
                            <p className="error-message">
                              {feedbackError}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {investigationResult &&
                    investigationResult.citations.length > 0 && (
                      <div className="citations">
                        <h3>Sources</h3>

                        {investigationResult.citations
                          .filter((citation) =>
                            answer.includes(
                              `[${citation.source_number}]`
                            )
                          )
                          .map((citation) => (
                            <div
                              key={citation.chunk_id}
                              className="citation-card"
                            >
                              <p className="citation-title">
                                [{citation.source_number}]{' '}
                                {citation.document_title}
                              </p>

                              <p>
                                Chunk {citation.chunk_order}
                              </p>

                              <p>
                                Similarity:{' '}
                                {(
                                  citation.similarity * 100
                                ).toFixed(1)}
                                %
                              </p>
                            </div>
                          ))}
                      </div>
                    )}
                </section>
              </>
            ) : (
              <>
                <h1>Incident Investigation</h1>
                <p>
                  Select an incident to investigate logs,
                  runbooks, and likely causes.
                </p>

                {isLoadingIncidents ? (
                  <p>Loading incidents...</p>
                ) : incidentsError ? (
                  <p className="error-message">
                    {incidentsError}
                  </p>
                ) : incidents.length === 0 ? (
                  <p>No incidents found.</p>
                ) : (
                  <div className="incident-list">
                    {incidents.map((incident) => (
                      <IncidentCard
                        key={incident.id}
                        title={incident.title}
                        description={incident.description}
                        severity={incident.severity}
                        status={incident.status}
                        onSelect={() =>
                          selectIncident(incident.id)
                        }
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {currentPage === 'documents' && (
          <>
            <h1>Documents</h1>
            <p>
              Review the runbooks and logs available to
              LogLens AI.
            </p>

            {user?.is_admin ? (
              <form
                className="upload-form"
                onSubmit={uploadDocument}
              >
                <h2>Upload Document</h2>

                <label htmlFor="document-title">
                  Document title
                </label>

                <input
                  id="document-title"
                  type="text"
                  value={uploadTitle}
                  onChange={(event) =>
                    setUploadTitle(event.target.value)
                  }
                  placeholder="Example: API Timeout Runbook"
                />

                <label htmlFor="document-file">
                  Choose file
                </label>

                <input
                  id="document-file"
                  type="file"
                  onChange={(event) =>
                    setUploadFile(
                      event.target.files?.[0] ?? null
                    )
                  }
                />

                <button
                  type="submit"
                  disabled={
                    isUploading ||
                    !uploadTitle.trim() ||
                    !uploadFile
                  }
                >
                  {isUploading
                    ? 'Uploading...'
                    : 'Upload Document'}
                </button>

                {uploadError && (
                  <p className="error-message">
                    {uploadError}
                  </p>
                )}

                {uploadMessage && (
                  <p className="success-message">
                    {uploadMessage}
                  </p>
                )}
              </form>
            ) : (
              <p>
                You are signed in as a standard user.
                Document uploads require administrator
                access.
              </p>
            )}

            <h2>Knowledge Base</h2>

            {isLoadingDocuments ? (
              <p>Loading documents...</p>
            ) : documentsError ? (
              <p className="error-message">
                {documentsError}
              </p>
            ) : documents.length === 0 ? (
              <p>No documents found.</p>
            ) : (
              documents.map((document) => (
                <div
                  key={document.id}
                  className="document-card"
                >
                  <h3>{document.title}</h3>

                  <p>
                    <strong>Type:</strong> {document.type}
                  </p>

                  <p>
                    <strong>Status:</strong>{' '}
                    {document.status}
                  </p>

                  <p>
                    <strong>Uploaded:</strong>{' '}
                    {new Date(
                      document.uploaded_at
                    ).toLocaleString()}
                  </p>

                  <p>
                    <strong>Chunks:</strong>{' '}
                    {document.chunk_count ?? 'N/A'}
                  </p>
                </div>
              ))
            )}
          </>
        )}

        {currentPage === 'analytics' && (
          <>
            <h1>Analytics</h1>
            <p>
              Review incident and investigation analytics.
            </p>

            {isLoadingAnalytics ? (
              <p>Loading analytics...</p>
            ) : analyticsError ? (
              <p className="error-message">
                {analyticsError}
              </p>
            ) : analytics ? (
              <>
                <div className="analytics-grid">
                  <div className="analytics-card">
                    <h3>Total Questions</h3>
                    <p>{analytics.total_questions}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Helpful Rate</h3>
                    <p>
                      {(
                        analytics.helpful_rate * 100
                      ).toFixed(1)}
                      %
                    </p>
                  </div>

                  <div className="analytics-card">
                    <h3>Feedback Responses</h3>
                    <p>{analytics.total_feedback}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Log Entries</h3>
                    <p>{analytics.total_log_entries}</p>
                  </div>
                </div>

                <h2>Knowledge Base</h2>

                <div className="analytics-grid">
                  <div className="analytics-card">
                    <h3>Runbooks</h3>
                    <p>{analytics.documents.runbooks}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Logs</h3>
                    <p>{analytics.documents.logs}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Chunks</h3>
                    <p>{analytics.total_chunks}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Helpful</h3>
                    <p>{analytics.helpful_count}</p>
                  </div>

                  <div className="analytics-card">
                    <h3>Unhelpful</h3>
                    <p>{analytics.unhelpful_count}</p>
                  </div>
                </div>

                <h2>Recent Questions</h2>

                {analytics.recent_questions.length === 0 ? (
                  <p>No recent questions found.</p>
                ) : (
                  analytics.recent_questions.map((item) => (
                    <div
                      key={item.id}
                      className="recent-question"
                    >
                      <p>{item.question}</p>

                      <p>
                        Incident ID: {item.incident_id}
                      </p>

                      <p>
                        Answered:{' '}
                        {new Date(
                          item.answered_at
                        ).toLocaleString()}
                      </p>
                    </div>
                  ))
                )}
              </>
            ) : (
              <p>No analytics available.</p>
            )}
          </>
        )}
      </main>
    </div>
  )
}

export default App