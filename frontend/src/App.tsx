import DocumentPreview, { type CitationTarget } from './DocumentPreview'
import {
  PanelLeft, SquarePen, Search, FileText, ChevronDown,
  Paperclip, ArrowUp, Plus, MessageSquare, MoreHorizontal,
  Sparkles, Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent, type KeyboardEvent, type CSSProperties } from 'react'
import { api, type ChatItem, type DocumentItem, type MessageItem } from './api'
import './App.css'

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function chatPath(documentId: string, chatId: string): string {
  return `/documents/${encodeURIComponent(documentId)}/chats/${encodeURIComponent(chatId)}`
}

function setChatUrl(documentId: string, chatId: string, replace = false) {
  const path = chatPath(documentId, chatId)
  if (window.location.pathname === path) return
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path)
}

type SplitHandleProps = {
  label: string
  axis: 'x' | 'y'
  unit: 'px' | 'percent'
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

function SplitHandle({ label, axis, unit, value, min, max, step, onChange }: SplitHandleProps) {
  const drag = useRef<{ position: number; value: number; size: number } | null>(null)
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const parent = event.currentTarget.parentElement
    if (!parent) return
    const bounds = parent.getBoundingClientRect()
    drag.current = { position: axis === 'x' ? event.clientX : event.clientY, value, size: axis === 'x' ? bounds.width : bounds.height }
    event.currentTarget.setPointerCapture(event.pointerId)
    document.body.classList.add('is-resizing')
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const position = axis === 'x' ? event.clientX : event.clientY
    const start = drag.current
    const delta = position - start.position
    const amount = unit === 'px' ? delta : delta / Math.max(1, start.size) * 100
    onChange(Math.max(min, Math.min(max, start.value + amount)))
  }
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = null
    document.body.classList.remove('is-resizing')
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const decrement = (axis === 'x' ? event.key === 'ArrowLeft' : event.key === 'ArrowUp')
    const increment = (axis === 'x' ? event.key === 'ArrowRight' : event.key === 'ArrowDown')
    if (!decrement && !increment) return
    event.preventDefault()
    onChange(Math.max(min, Math.min(max, value + (increment ? step : -step))))
  }
  return (
    <div
      className={`split-handle split-handle-${label}`}
      role="separator"
      aria-label={label}
      aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(value)}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    >
      <span />
    </div>
  )
}

export default function App() {
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(() => new Set())
  const [activeCitation, setActiveCitation] = useState<CitationTarget | null>(null)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [activeDoc, setActiveDoc] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [chats, setChats] = useState<ChatItem[]>([])
  const [activeChat, setActiveChat] = useState('')
  const [messages, setMessages] = useState<MessageItem[]>([])
  const [message, setMessage] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia('(max-width: 900px)').matches)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = Number(localStorage.getItem('cognora.sidebarWidth'))
    return saved >= 190 && saved <= 420 ? saved : 280
  })
  const [previewSize, setPreviewSize] = useState(() => {
    const saved = Number(localStorage.getItem('cognora.previewSize'))
    return saved >= 28 && saved <= 72 ? saved : 48
  })
  const [mobilePane, setMobilePane] = useState<'chat' | 'document'>('chat')
  const [busy, setBusy] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [processingStage, setProcessingStage] = useState('queued')
  const [completedStages, setCompletedStages] = useState(0)
  const [totalProcessingStages, setTotalProcessingStages] = useState(3)
  const [processingStartedAt, setProcessingStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const selectionSequence = useRef(0)

  useEffect(() => { localStorage.setItem('cognora.sidebarWidth', String(sidebarWidth)) }, [sidebarWidth])
  useEffect(() => { localStorage.setItem('cognora.previewSize', String(previewSize)) }, [previewSize])
  useEffect(() => {
    const media = window.matchMedia('(max-width: 900px)')
    const closeNavigationOnPhone = (event: MediaQueryListEvent) => {
      if (event.matches) setSidebarOpen(false)
    }
    media.addEventListener('change', closeNavigationOnPhone)
    return () => media.removeEventListener('change', closeNavigationOnPhone)
  }, [])

  const selectedDoc = docs.find(d => d.id === activeDoc)
  const selectedChat = chats.find(c => c.id === activeChat)

  useEffect(() => {
    setSelectedDocumentIds(activeDoc ? [activeDoc] : [])
  }, [activeDoc])

  const refreshDocuments = useCallback(async () => {
    const items = await api.documents()
    setDocs(items)
    return items
  }, [])

  const monitorProcessingJob = useCallback(async (
    initialJob: Awaited<ReturnType<typeof api.process>>,
    isCancelled: () => boolean = () => false,
  ) => {
    if (isCancelled()) return null
    let job = initialJob
    setProcessing(true)
    setProcessingStage(job.stage)
    setCompletedStages(job.completed_stages)
    setTotalProcessingStages(job.total_stages)
    while (job.status === 'queued' || job.status === 'running') {
      await new Promise(resolve => window.setTimeout(resolve, 1200))
      if (isCancelled()) return null
      job = await api.processingJob(job.id)
      if (isCancelled()) return null
      setProcessingStage(job.stage)
      setCompletedStages(job.completed_stages)
      setTotalProcessingStages(job.total_stages)
    }
    if (job.status === 'failed') {
      throw new Error(job.error || 'Document processing failed. Retry the job.')
    }
    return job
  }, [])

  useEffect(() => {
  let cancelled = false
  let navigationVersion = 0

  const restoreFromUrl = async () => {
    const interaction = ++selectionSequence.current
    const version = ++navigationVersion
    setActiveCitation(null)
    const isCurrent = () => !cancelled && version === navigationVersion
    const match = window.location.pathname.match(
      /^\/documents\/([^/]+)\/chats\/([^/]+)\/?$/
    )

    if (!match) {
      if (window.location.pathname === '/') {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setError('')
      } else {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setError('This conversation URL is not valid. Choose a document or chat.')
      }
      try {
        await refreshDocuments()
      } catch (e) {
        if (isCurrent()) setError(getErrorMessage(e, 'Could not load documents'))
      }
      if (isCurrent() && interaction === selectionSequence.current) setBusy(false)
      return
    }

    try {
      const documentId = decodeURIComponent(match[1])
      const chatId = decodeURIComponent(match[2])

      const documents = await refreshDocuments()
      if (!isCurrent()) return

      const document = documents.find(item => item.id === documentId)

      if (!document) {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setError('This document does not exist or is no longer available.')
        if (interaction === selectionSequence.current) setBusy(false)
        return
      }

      const availableChats = await api.chats(documentId)
      if (!isCurrent()) return

      const chat = availableChats.find(item => item.id === chatId)

      if (!chat) {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setError('This conversation was not found. Choose another chat.')
        if (interaction === selectionSequence.current) setBusy(false)
        return
      }

      const history = await api.messages(chatId)
      if (!isCurrent()) return

      setActiveDoc(documentId)
      setActiveChat(chatId)
      setChats(availableChats)
      setMessages(history)
      setExpandedDocs(previous => new Set(previous).add(documentId))
      setError('')
      if (interaction === selectionSequence.current) setBusy(false)
    } catch (e) {
      if (isCurrent()) {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setError(
          e instanceof Error
            ? e.message
            : 'Could not restore this conversation.'
        )
        if (interaction === selectionSequence.current) setBusy(false)
      }
    }
  }

  void restoreFromUrl()

  window.addEventListener('popstate', restoreFromUrl)

  return () => {
    cancelled = true
    window.removeEventListener('popstate', restoreFromUrl)
  }
}, [refreshDocuments])

  useEffect(() => {
    if (!processingStartedAt) return
    const updateElapsed = () => setElapsedSeconds(Math.floor((Date.now() - processingStartedAt) / 1000))
    updateElapsed()
    const timer = window.setInterval(updateElapsed, 1000)
    return () => window.clearInterval(timer)
  }, [processingStartedAt])

  useEffect(() => {
    if (!selectedDoc || !['processing', 'processing_failed'].includes(selectedDoc.status)) return
    let cancelled = false
    void (async () => {
      try {
        const initialJob = await api.latestProcessingJob(selectedDoc.id)
        if (cancelled) return
        if (initialJob.status === 'failed') {
          setError(initialJob.error || 'Document processing failed. Retry the job.')
          return
        }
        const started = Date.parse(initialJob.created_at)
        setProcessingStartedAt(Number.isFinite(started) ? started : Date.now())
        const finalJob = await monitorProcessingJob(initialJob, () => cancelled)
        if (finalJob && !cancelled) await refreshDocuments()
      } catch (e) {
        if (!cancelled) setError(getErrorMessage(e, 'Could not reconnect to document processing'))
      } finally {
        if (!cancelled) {
          setProcessing(false)
          setProcessingStartedAt(null)
        }
      }
    })()
    return () => { cancelled = true }
  }, [selectedDoc?.id, selectedDoc?.status, monitorProcessingJob, refreshDocuments])

  const refreshChats = useCallback(async (docId: string) => {
    const items = await api.chats(docId)
    setChats(items)
    return items
  }, [])

  const openDocument = async (doc: DocumentItem) => {
    const selection = ++selectionSequence.current
    setActiveCitation(null)
    setError('')
    setBusy(true)
    try {
      const items = await api.chats(doc.id)
      const chat = items[0] ?? await api.createChat(doc.id)
      const availableChats = items.length ? items : [chat]
      const history = await api.messages(chat.id)
      if (selection !== selectionSequence.current) return
      setChats(availableChats)
      setActiveDoc(doc.id)
      setActiveChat(chat.id)
      setMessages(history)
      setExpandedDocs(previous => new Set(previous).add(doc.id))
      setChatUrl(doc.id, chat.id)
      if (window.matchMedia('(max-width: 900px)').matches) setSidebarOpen(false)
    } catch (e) {
      if (selection === selectionSequence.current) {
        setError(getErrorMessage(e, 'Could not open this document'))
      }
    } finally {
      if (selection === selectionSequence.current) setBusy(false)
    }
  }


const openChat = async (chat: ChatItem) => {
  const selection = ++selectionSequence.current
  setActiveCitation(null)
  setError('')
  setBusy(true)

  try {
    // Load the chat list and messages before changing the visible selection.
    const [availableChats, history] = await Promise.all([
      api.chats(chat.document_id),
      api.messages(chat.id),
    ])

    const exists = availableChats.some(item => item.id === chat.id)
    if (selection !== selectionSequence.current) return

    if (!exists) {
      throw new Error('This conversation no longer exists. Refresh your chat list.')
    }

    setChats(availableChats)
    setActiveDoc(chat.document_id)
    setActiveChat(chat.id)
    setMessages(history)
    setExpandedDocs(previous => new Set(previous).add(chat.document_id))

    setChatUrl(chat.document_id, chat.id)
    if (window.matchMedia('(max-width: 900px)').matches) setSidebarOpen(false)
  } catch (e) {
    if (selection === selectionSequence.current) setError(
      e instanceof Error
        ? e.message
        : 'Could not load this conversation. Check the backend connection.'
    )
  } finally {
    if (selection === selectionSequence.current) setBusy(false)
  }
}


  const newChat = async (docId = activeDoc) => {
    const selection = ++selectionSequence.current
    setActiveCitation(null)
    if (!docId) {
      setError('Upload or select a document before creating a chat.')
      setBusy(false)
      return
    }
    setBusy(true)
    setError('')
    try {
      const existing = await api.chats(docId)
      const chat = await api.createChat(docId)
      if (selection !== selectionSequence.current) return
      setChats([chat, ...existing])
      setActiveDoc(docId)
      setActiveChat(chat.id)
      setMessages([])
      setExpandedDocs(previous => new Set(previous).add(docId))
      setChatUrl(docId, chat.id)
      if (window.matchMedia('(max-width: 900px)').matches) setSidebarOpen(false)
    } catch (e) {
      if (selection === selectionSequence.current) {
        setError(e instanceof Error ? e.message : 'Could not create chat')
      }
    } finally {
      if (selection === selectionSequence.current) setBusy(false)
    }
  }

  const addDocument = async (file?: File) => {
    if (!file) return
    ++selectionSequence.current
    setActiveCitation(null)
    setBusy(true)
    setError('')
    try {
      const doc = await api.upload(file)
      const chat = await api.createChat(doc.id)
      const [documents, availableChats] = await Promise.all([
        api.documents(), api.chats(doc.id),
      ])
      setDocs(documents)
      setChats(availableChats.length ? availableChats : [chat])
      setActiveDoc(doc.id)
      setActiveChat(chat.id)
      setMessages(await api.messages(chat.id))
      setExpandedDocs(previous => new Set(previous).add(doc.id))
      setChatUrl(doc.id, chat.id)
      if (window.matchMedia('(max-width: 900px)').matches) setSidebarOpen(false)
      setError('')
      // New uploads must be processed before asking questions.
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const processDocument = async (force = false) => {
    if (!selectedDoc || processing) return
    const documentId = selectedDoc.id
    setProcessing(true)
    setProcessingStage('queued')
    setCompletedStages(0)
    setTotalProcessingStages(3)
    setProcessingStartedAt(Date.now())
    setElapsedSeconds(0)
    setBusy(true)
    setError('')
    try {
      const initialJob = await api.process(documentId, force)
      const started = Date.parse(initialJob.created_at)
      setProcessingStartedAt(Number.isFinite(started) ? started : Date.now())
      const finalJob = await monitorProcessingJob(initialJob)
      if (!finalJob) return
      setProcessingStage(finalJob.stage)
      setCompletedStages(finalJob.completed_stages)
      setTotalProcessingStages(finalJob.total_stages)
      await refreshDocuments()
    } catch (e) {
      setError(getErrorMessage(e, 'Processing failed'))
    } finally {
      setProcessing(false)
      setProcessingStartedAt(null)
      setBusy(false)
    }
  }

  const sendMessage = async () => {
    const content = message.trim()
    if (!content || !activeChat || busy) return
    const selection = selectionSequence.current
    const chatId = activeChat
    const documentId = activeDoc

    const optimistic: MessageItem = {
      id: Date.now(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, optimistic])
    setMessage('')
    setBusy(true)
    setError('')

    try {
      await api.send(chatId, content, selectedDocumentIds.length ? selectedDocumentIds : [documentId])
      const history = await api.messages(chatId)
      if (selection !== selectionSequence.current) return
      setMessages(history)
      if (documentId) await refreshChats(documentId)
    } catch (e) {
      if (selection === selectionSequence.current) {
        setError(e instanceof Error ? e.message : 'Could not send message')
        try {
          setMessages(await api.messages(chatId))
        } catch {
          // Keep the optimistic message visible if history cannot load.
        }
      }
    } finally {
      if (selection === selectionSequence.current) setBusy(false)
    }
  }
  const toggleDocument = (docId: string) => {
  setExpandedDocs(prev => {
    const next = new Set(prev)
    if (next.has(docId)) next.delete(docId)
    else next.add(docId)
    return next
  })
  }

  const deleteChat = async (chat: ChatItem) => {
    if (!window.confirm(`Delete "${chat.title}" and its messages?`)) return
    const wasActive = activeChat === chat.id
    const selection = wasActive ? ++selectionSequence.current : selectionSequence.current
    if (wasActive) setBusy(true)
    setError('')
    try {
      await api.deleteChat(chat.id)
      const remaining = await api.chats(chat.document_id)
      if (selection !== selectionSequence.current) return

      if (activeDoc === chat.document_id) setChats(remaining)
      if (wasActive) {
        const next = remaining[0]
        if (next) {
          const history = await api.messages(next.id)
          if (selection !== selectionSequence.current) return
          setActiveDoc(next.document_id)
          setActiveChat(next.id)
          setMessages(history)
          setChatUrl(next.document_id, next.id, true)
        } else {
          setActiveChat('')
          setMessages([])
          window.history.replaceState({}, '', '/')
        }
      }
    } catch (e) {
      if (selection === selectionSequence.current) {
        setError(e instanceof Error ? e.message : 'Could not delete chat')
      }
    } finally {
      if (wasActive && selection === selectionSequence.current) setBusy(false)
    }
  }

  const deleteDocument = async (doc: DocumentItem) => {
    if (!window.confirm(`Permanently delete "${doc.name}" and all its chats, messages, files, and indexed content?`)) return
    const wasActive = activeDoc === doc.id
    const selection = ++selectionSequence.current
    setBusy(true)
    setError('')
    try {
      await api.deleteDocument(doc.id)
      setDocs(previous => previous.filter(item => item.id !== doc.id))
      setExpandedDocs(previous => {
        const next = new Set(previous)
        next.delete(doc.id)
        return next
      })
      if (wasActive && selection === selectionSequence.current) {
        setActiveDoc('')
        setActiveChat('')
        setChats([])
        setMessages([])
        setActiveCitation(null)
        window.history.replaceState({}, '', '/')
      }
    } catch (e) {
      if (selection === selectionSequence.current) {
        setError(getErrorMessage(e, 'Could not delete document'))
      }
    } finally {
      if (selection === selectionSequence.current) setBusy(false)
    }
  }

  return (
    <div className={`app-shell ${mobilePane === 'document' ? 'mobile-show-document' : ''}`} style={{ '--sidebar-width': `${sidebarWidth}px`, '--preview-size': `${previewSize}%` } as CSSProperties}>
      <div className="mobile-pane-switch" role="group" aria-label="Choose workspace view">
        <button className={mobilePane === 'chat' ? 'active' : ''} onClick={() => setMobilePane('chat')}>Chat</button>
        <button className={mobilePane === 'document' ? 'active' : ''} onClick={() => setMobilePane('document')} disabled={!selectedDoc}>Document</button>
      </div>
      {sidebarOpen && <button className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
      {sidebarOpen && (
        <aside className="sidebar">
          <div className="sidebar-top">
            <button className="icon-button" onClick={() => setSidebarOpen(false)} title="Close sidebar">
              <PanelLeft size={19} />
            </button>
            <div className="brand-mark">C</div>
            <span className="brand-name">Cognora</span>
            <button className="icon-button push-right" onClick={() => newChat()} title="New chat">
              <SquarePen size={19} />
            </button>
          </div>

          <button className="nav-action" onClick={() => newChat()}>
            <SquarePen size={17} /><span>New chat</span>
          </button>

          <label className="nav-action upload-action">
            <Plus size={18} /><span>{busy ? 'Working…' : 'Add document'}</span>
            <input
              type="file"
              accept=".pdf,.docx,.doc,.rtf,.pptx,.ppt,.xlsx,.xls,.csv,.txt,.md,.html,.htm,.mhtml,.odt,.ods,.odp,.epub,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"
              hidden
              disabled={busy}
              onChange={e => {
                void addDocument(e.target.files?.[0])
                e.currentTarget.value = ''
              }}
            />
          </label>

          <div className="nav-action muted-action">
            <Search size={17} />
            <input
              className="sidebar-search-input"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search documents and chats"
            />
          </div>

          <div className="sidebar-section-label">YOUR DOCUMENTS</div>
          <div className="document-list">
            {docs.filter(d => d.name.toLowerCase().includes(search.toLowerCase())).map(doc => {
              const isActive = activeDoc === doc.id
              const docChats = isActive ? chats : []

              return (
                <div className="document-group" key={doc.id}>
                  <div className="document-heading">
                    <button
                      className={`document-row ${isActive ? 'selected' : ''}`}
                      onClick={() => {
                        toggleDocument(doc.id)
                        if (activeDoc !== doc.id) void openDocument(doc)
                      }}
                    >
                      <FileText size={17} />
                      <span>{doc.name}</span>
                      <ChevronDown size={14} className="doc-chevron" />
                    </button>
                    <button
                      className="icon-button document-delete"
                      onClick={() => void deleteDocument(doc)}
                      title={`Permanently delete ${doc.name} and its chats`}
                      aria-label={`Delete ${doc.name} and all its chats`}
                      disabled={busy}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  {expandedDocs.has(doc.id) && isActive && (
                    <div className="chat-list">
                      {docChats.filter(c => c.title.toLowerCase().includes(search.toLowerCase())).map(chat => (
                        <div className="history-item" key={chat.id}>
                          <button
                            className={`history-row ${activeChat === chat.id ? 'history-selected' : ''}`}
                            onClick={() => void openChat(chat)}
                            title={chat.title}
                          >
                            <MessageSquare size={15} />
                            <span>{chat.title}</span>
                          </button>
                          <button
                            className="icon-button history-delete"
                            onClick={() => void deleteChat(chat)}
                            title={`Delete ${chat.title}`}
                            aria-label={`Delete ${chat.title}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}
                      <button className="history-new" onClick={() => void newChat(doc.id)}>
                        <Plus size={15} /> New chat
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
            {!docs.length && <p className="sidebar-empty">No documents yet. Add one to begin.</p>}
          </div>

          <div className="sidebar-footer">
            <div className="avatar">D</div>
            <div className="profile-copy">
              <strong>Local workspace</strong>
              <span>Private document assistant</span>
            </div>
            <MoreHorizontal size={18} />
          </div>
        </aside>
      )}
      {sidebarOpen && <SplitHandle label="Resize navigation" axis="x" unit="px" value={sidebarWidth} min={190} max={420} step={12} onChange={setSidebarWidth} />}
    <div className="workspace">
      {selectedDoc && (
        <DocumentPreview
          key={selectedDoc.id}
          documentId={selectedDoc.id}
          documentName={selectedDoc.name}
          citation={activeCitation}
        />
      )}
      {selectedDoc && <SplitHandle label="Resize document preview" axis="x" unit="percent" value={previewSize} min={28} max={72} step={3} onChange={setPreviewSize} />}
      <main className="main-panel">
        <header className="topbar">
          {!sidebarOpen && (
            <button className="icon-button" onClick={() => setSidebarOpen(true)} title="Open sidebar">
              <PanelLeft size={19} />
            </button>
          )}
          <div className="topbar-title">
            {selectedChat?.title && selectedChat.title !== 'New chat'
              ? selectedChat.title
              : selectedDoc?.name ?? 'Cognora'}
          </div>
          <div className="topbar-actions">
            {selectedDoc?.status === 'text_extracted' && !processing && (
              <button className="reprocess-button" onClick={() => void processDocument(true)} disabled={busy} title="Reprocess this document and refresh extracted figure images">
                Refresh document analysis
              </button>
            )}
            <span className="local-pill"><span /> Local AI</span>
            <button className="icon-button" onClick={() => { void refreshDocuments().catch(error => setError(getErrorMessage(error, 'Could not refresh documents'))) }} title="Refresh documents">
              <MoreHorizontal size={20} />
            </button>
          </div>
        </header>

        <section className={`conversation ${messages.length ? 'has-chat' : 'empty-chat'}`}>
          {!selectedDoc ? (
            <div className="welcome">
              <div className="welcome-icon"><Sparkles size={25} /></div>
              <h1>What can I help you understand?</h1>
              <p>Upload a document to ask questions about its contents.</p>
            </div>
          ) : !selectedChat ? (
            <div className="welcome">
              <div className="welcome-icon"><FileText size={25} /></div>
              <h1>{selectedDoc.name}</h1>
              <p>Choose a conversation or start a new chat.</p>
              <button className="history-new" onClick={() => void newChat(selectedDoc.id)}>
                <Plus size={15} /> Start a conversation
              </button>
            </div>
          ) : messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon"><Sparkles size={25} /></div>
              <h1>What would you like to know?</h1>
              <p>Ask a question about <strong>{selectedDoc.name}</strong>.</p>
            </div>
          ) : (
            <div className="messages">
              {messages.map(item => (
                <div className={item.role === 'user' ? 'user-message' : 'assistant-message'} key={item.id}>
                  {item.role === 'user'
                    ? <div className="user-avatar">You</div>
                    : <div className="assistant-avatar"><Sparkles size={17} /></div>}
                  <div>
                    <div className="message-author">{item.role === 'user' ? 'You' : 'Cognora'}</div>
                    <p>{item.content.split(/(\[E\d+\])/g).map((part, index) => {
                      const source = item.citations?.find(citation => `[${citation.label}]` === part)
                      return source ? (
                        <button
                          className="inline-citation"
                          key={`${item.id}-citation-${index}`}
                          onClick={() => {
                            setActiveCitation({
                              id: source.id,
                              page: source.page,
                              quote: source.text,
                              documentName: source.document_name,
                            })
                            if (window.matchMedia('(max-width: 900px)').matches) setMobilePane('document')
                          }}
                          title={source.page ? `View Page ${source.page}` : 'View source excerpt'}
                        >{source.page ? `Page ${source.page}` : 'Source'}</button>
                      ) : <span key={`${item.id}-text-${index}`}>{part}</span>
                    })}</p>
                    {item.role === 'assistant' && item.citations?.some(source => source.type === 'figure' && source.figure_id) && (
                      <div className="answer-figures" aria-label="Images used as answer evidence">
                        {item.citations
                          .filter(source => source.type === 'figure' && source.figure_id)
                          .filter((source, index, all) => all.findIndex(candidate => candidate.figure_id === source.figure_id) === index)
                          .map(source => (
                            <figure className="answer-figure" key={`${item.id}-${source.figure_id}`}>
                              <img
                                src={api.documentFigureUrl(source.document_id, source.figure_id!)}
                                alt={`Figure${source.page ? ` from Page ${source.page}` : ''} in ${source.document_name}`}
                                loading="lazy"
                              />
                              <figcaption>{source.page ? `Page ${source.page}` : 'Page unavailable'} · {source.document_name}</figcaption>
                            </figure>
                          ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {busy && (
                <div className="assistant-message">
                  <div className="assistant-avatar"><Sparkles size={17} /></div>
                  <div><div className="message-author">Cognora</div><p>Thinking…</p></div>
                </div>
              )}
            </div>
          )}
        </section>

        {error && <div className="error-banner">{error}</div>}

        {selectedDoc && (selectedDoc.status !== 'text_extracted' || processing) && (
          <div className={`process-banner ${processing ? 'is-processing' : ''}`}>
            <div className="process-copy">
              <div className="process-heading">
                <strong>{processing ? 'Processing document' : selectedDoc.status === 'processing_failed' ? 'Processing failed' : 'Ready to process this document'}</strong>
                <span className="process-stage">{processing ? ({
                  queued: 'Waiting for the processing worker',
                  parsing: 'Parsing the document and extracting text',
                  element_extraction: 'Preserving page, table, and element sources',
                  embedding_and_indexing: 'Embedding and indexing extracted chunks',
                  ready: 'Document is ready for chat',
                  failed: 'Processing failed',
                }[processingStage] ?? processingStage) : 'Text extraction and indexing are required before asking questions'}</span>
              </div>
              {processing && (
                <>
                  <div className="progress-track" role="progressbar" aria-label="Document processing" aria-valuemin={0} aria-valuemax={totalProcessingStages} {...(processingStage === 'parsing' || processingStage === 'queued' ? { 'aria-valuetext': processingStage === 'parsing' ? 'Parsing and extracting text' : 'Waiting for processing worker' } : { 'aria-valuenow': completedStages })}>
                    {processingStage === 'parsing' || processingStage === 'queued'
                      ? <div className="progress-indeterminate" />
                      : <div className="progress-completed" style={{ width: `${Math.min(100, completedStages / Math.max(1, totalProcessingStages) * 100)}%` }} />}
                  </div>
                  <div className="process-meta">
                    <span>Elapsed {Math.floor(elapsedSeconds / 60)}:{String(elapsedSeconds % 60).padStart(2, '0')}</span>
                    <span>{processingStage === 'parsing' ? 'Reading pages and extracting document content…' : processingStage === 'queued' ? 'Starting document processor…' : `${completedStages} of ${totalProcessingStages} stages complete`}</span>
                  </div>
                </>
              )}
            </div>
            {!processing && <button disabled={busy} onClick={() => void processDocument()}>Process document</button>}
          </div>
        )}

        <footer className="composer-area">
          {docs.filter(item => item.status === 'text_extracted').length > 1 && (
            <details className="compare-documents">
              <summary>Compare across documents</summary>
              <div className="compare-document-list">
                {docs.filter(item => item.status === 'text_extracted').map(item => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      checked={selectedDocumentIds.includes(item.id)}
                      disabled={item.id === activeDoc || (!selectedDocumentIds.includes(item.id) && selectedDocumentIds.length >= 10)}
                      onChange={event => setSelectedDocumentIds(current => event.target.checked
                        ? [...new Set([...current, item.id])]
                        : current.filter(id => id !== item.id))}
                    />
                    {item.name}
                  </label>
                ))}
              </div>
            </details>
          )}
          <div className="composer">
            <label className="composer-attach" title="Attach a document">
              <Paperclip size={19} />
              <input
                type="file"
                accept=".pdf,.docx,.doc,.rtf,.pptx,.ppt,.xlsx,.xls,.csv,.txt,.md,.html,.htm,.mhtml,.odt,.ods,.odp,.epub,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"
                hidden
                disabled={busy}
                onChange={e => {
                  void addDocument(e.target.files?.[0])
                  e.currentTarget.value = ''
                }}
              />
            </label>
            <textarea
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void sendMessage()
                }
              }}
              placeholder={
                !selectedDoc ? 'Upload a document to begin…'
                  : selectedDoc.status !== 'text_extracted'
                    ? 'Process this document before asking questions…'
                    : `Message about ${selectedDoc.name}…`
              }
              disabled={!selectedDoc || selectedDoc.status !== 'text_extracted' || busy}
              rows={1}
            />
            <button
              className={`send-button ${message.trim() ? 'send-active' : ''}`}
              onClick={() => void sendMessage()}
              disabled={!message.trim() || !activeChat || busy || selectedDoc?.status !== 'text_extracted'}
              title="Send message"
            >
              <ArrowUp size={19} />
            </button>
          </div>
          <p className="composer-disclaimer">
            Cognora can make mistakes. Verify important information against the source document.
          </p>
        </footer>
      </main>
    </div>
    </div>
  )
  }
