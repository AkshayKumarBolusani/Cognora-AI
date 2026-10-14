
const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '')

function documentFileUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`
}

export type DocumentItem = {
  id: string
  name: string
  stored_name: string
  status: string
  uploaded_at: string
}

function documentPreviewImageUrl(documentId: string): string {
  return API_BASE + '/documents/' + encodeURIComponent(documentId) + '/preview-image'
}

function documentFigureUrl(documentId: string, figureId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/figures/${encodeURIComponent(figureId)}`
}

export type ChatItem = {
  id: string
  document_id: string
  title: string
  created_at: string
}

export type MessageItem = {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  citations?: CitationItem[]
}

export type CitationItem = {
  id: string
  label: string
  document_id: string
  document_name: string
  page: number | null
  text: string
  type: string
  figure_id?: string | null
}

export type ProcessingJob = {
  id: string
  document_id: string
  status: 'queued' | 'running' | 'ready' | 'failed'
  stage: string
  completed_stages: number
  total_stages: number
  error?: string | null
  created_at: string
  updated_at: string
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs = 30000,
): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The request timed out. Please try again.')
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // Keep the fallback message.
    }
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

export const api = {
  documentFileUrl,
  documentPreviewImageUrl,
  documentFigureUrl,
  documents: () => request<DocumentItem[]>('/documents'),
  documentPreview: (documentId: string) =>
    request<{ text: string; kind: 'text'; processed: boolean }>(
      '/documents/' + encodeURIComponent(documentId) + '/preview',
    ),

  deleteDocument: (documentId: string) =>
    request<{ deleted: boolean; document_id: string; deleted_indexes: string[] }>(
      `/documents/${encodeURIComponent(documentId)}`,
      { method: 'DELETE' },
    ),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentItem>('/documents', {
      method: 'POST',
      body: form,
    }, 180000)
  },


    deleteChat: (chatId: string) =>
    request<{ deleted: boolean; chat_id: string }>(
        `/chats/${chatId}`,
        { method: 'DELETE' },
    ),


  process: (documentId: string, force = false) =>
    request<ProcessingJob>(
      `/documents/${encodeURIComponent(documentId)}/process${force ? '?force=true' : ''}`,
      { method: 'POST' },
    ),

  processingJob: (jobId: string) =>
    request<ProcessingJob>(`/processing-jobs/${encodeURIComponent(jobId)}`),

  latestProcessingJob: (documentId: string) =>
    request<ProcessingJob>(`/documents/${encodeURIComponent(documentId)}/processing-job`),

  chats: (documentId: string) =>
    request<ChatItem[]>(`/documents/${documentId}/chats`),

  createChat: (documentId: string) =>
    request<ChatItem>('/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: documentId }),
    }),

  messages: (chatId: string) =>
    request<MessageItem[]>(`/chats/${chatId}/messages`),

  send: (chatId: string, content: string, documentIds?: string[]) =>
    request<{ answer: string; chat_id: string; citations: CitationItem[] }>(
      `/chats/${chatId}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, document_ids: documentIds }),
      },
    ),
}
