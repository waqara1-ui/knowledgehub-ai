export type RecentQuestion = {
  id: number
  incident_id: number
  question: string
  answered_at: string
}

export type AnalyticsSummary = {
  total_questions: number
  total_feedback: number
  helpful_count: number
  unhelpful_count: number
  helpful_rate: number
  documents: {
    runbooks: number
    logs: number
  }
  total_chunks: number
  total_log_entries: number
  recent_questions: RecentQuestion[]
}