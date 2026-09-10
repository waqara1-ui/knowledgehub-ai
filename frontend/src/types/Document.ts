export type Document = {
  id: number
  title: string
  type: string
  status: string
  uploaded_at: string
  chunk_count: number | null
}

export type DocumentListResponse = {
  count: number
  documents: Document[]
}