
const API_BASE = 'http://localhost:8000/api'

export type DocumentItem = {
  id: string
  name: string
  stored_name: string
  status: string
  uploaded_at: string
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
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options)

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
  documents: () => request<DocumentItem[]>('/documents'),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentItem>('/documents', {
      method: 'POST',
      body: form,
    })
  },


    deleteChat: (chatId: string) =>
    request<{ deleted: boolean; chat_id: string }>(
        `/chats/${chatId}`,
        { method: 'DELETE' },
    ),


  process: (documentId: string) =>
    request<{ status: string; characters: number }>(
      `/documents/${documentId}/process`,
      { method: 'POST' },
    ),

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

  send: (chatId: string, content: string) =>
    request<{ answer: string; chat_id: string }>(
      `/chats/${chatId}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      },
    ),
}
