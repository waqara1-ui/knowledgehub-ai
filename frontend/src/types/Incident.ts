export type Incident = {
  id: number
  title: string
  description: string | null
  status: string
  severity: string | null
  created_at: string
  creator_id: number
}
