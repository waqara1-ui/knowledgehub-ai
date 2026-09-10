export type Citation = {
  source_number: number
  document_id: number
  document_title: string
  chunk_id: number
  chunk_order: number
  similarity: number
}

export type InvestigationResponse = {
  incident_id: number
  question_log_id: number
  question: string
  answer: string
  citations: Citation[]
  grounded: boolean

  llm: {
    provider: string
    model: string
    degraded: boolean
    error: string | null
  }

  retrieval: {
    backend: string
    threshold: number
    chunks_used: number
    historical_log_patterns_used: number
  }

  historical_log_patterns: unknown[]
  message: string
}