import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
})

export interface HealthResponse {
  status: string
  version?: string
}

export interface ReadyResponse {
  ready: boolean
  checks: {
    ollama_health?: string
    tesseract_health?: string
  }
}

export interface IngestionResponse {
  ingestion_id: string
  filename: string
  detected_type: string
  size: number
  hash: string
  page_count: number
  page_dimensions: Array<{ width: number, height: number }>
}

export interface JobState {
  ingestion_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  stage: string
  progress: {
    pages_processed: number
    total_pages: number
  }
  errors: string[]
  receipt_available: boolean
}

// Receipt types
export interface BoundingBox {
  x: number
  y: number
  width: number
  height: number
}

export interface MatchedQuote {
  matched_text: string
  page_index: number
  character_start_index: number
  character_end_index: number
  bounding_boxes: BoundingBox[]
}

export interface EvidenceRecord {
  fact_type: string
  candidate_value: string
  status: 'SUPPORTED_TEXT' | 'UNVERIFIED' | 'REVIEW_REQUIRED' | 'VERIFICATION_FAILED'
  original_quotation: string | null
  matched_quotes: MatchedQuote[]
}

export interface ActionStep {
  step_order: number
  instruction: string
  is_model_suggestion: boolean
}

export interface EvidenceReceipt {
  schema_version: string
  metadata: {
    receipt_id: string
    ingestion_id: string
    source_sha256: string
    filename: string
    file_type: string
    page_count: number
  }
  processing: {
    model_tag: string
  }
  document_summary: string
  document_purpose: string
  extracted_facts: EvidenceRecord[]
  deterministic_checks: Array<{ check_name: string, status: string, message: string }>
  actionable_guidance: ActionStep[]
  resources: any[]
  global_status: string
}

export const ApiClient = {
  checkLive: async (): Promise<HealthResponse> => {
    const res = await api.get('/health/live')
    return res.data
  },
  
  checkReady: async (): Promise<ReadyResponse> => {
    const res = await api.get('/health/ready')
    return res.data
  },
  
  ingestFile: async (file: File): Promise<IngestionResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await api.post('/api/ingest', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return res.data
  },
  
  startInspectionJob: async (ingestionId: string, fetchResources = true): Promise<JobState> => {
    const res = await api.post(`/api/inspect/${ingestionId}/job?fetch_resources=${fetchResources}`)
    return res.data
  },
  
  getInspectionJob: async (ingestionId: string): Promise<JobState> => {
    const res = await api.get(`/api/inspect/${ingestionId}/job`)
    return res.data
  },
  
  getReceipt: async (ingestionId: string): Promise<EvidenceReceipt> => {
    const res = await api.get(`/api/inspect/${ingestionId}/receipt`)
    return res.data
  },
  
  verifyReceipt: async (receiptFile: File, sourceFile: File): Promise<{ verified: boolean, details: string }> => {
    const formData = new FormData()
    formData.append('receipt_file', receiptFile)
    formData.append('source_file', sourceFile)
    const res = await api.post('/api/verify', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return res.data
  }
}
