import {
  PanelLeft, SquarePen, Search, FileText, ChevronDown,
  Paperclip, ArrowUp, Plus, MessageSquare, MoreHorizontal,
  Sparkles, Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, type ChatItem, type DocumentItem, type MessageItem } from './api'
import './App.css'

export default function App() {
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(
  new Set(),
)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [activeDoc, setActiveDoc] = useState('')
  const [chats, setChats] = useState<ChatItem[]>([])
  const [activeChat, setActiveChat] = useState('')
  const [messages, setMessages] = useState<MessageItem[]>([])
  const [message, setMessage] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const selectedDoc = docs.find(d => d.id === activeDoc)
  const selectedChat = chats.find(c => c.id === activeChat)

  const refreshDocuments = useCallback(async () => {
    const items = await api.documents()
    setDocs(items)
    return items
  }, [])

  useEffect(() => {
    refreshDocuments().catch(e => setError(e.message))
  }, [refreshDocuments])

  const refreshChats = useCallback(async (docId: string) => {
    const items = await api.chats(docId)
    setChats(items)
    return items
  }, [])

  const openDocument = async (doc: DocumentItem) => {
    setError('')
    setActiveDoc(doc.id)
    setActiveChat('')
    setMessages([])
    try {
      const items = await refreshChats(doc.id)
      if (items.length) {
        setActiveChat(items[0].id)
        setMessages(await api.messages(items[0].id))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load chats')
    }
  }

  const openChat = async (chat: ChatItem) => {
    setError('')
    setActiveDoc(chat.document_id)
    setActiveChat(chat.id)
    setMessages([])
    try {
      setMessages(await api.messages(chat.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load messages')
    }
  }

  const newChat = async (docId = activeDoc) => {
    if (!docId) {
      setError('Upload or select a document before creating a chat.')
      return
    }
    setError('')
    try {
      const chat = await api.createChat(docId)
      setActiveDoc(docId)
      setActiveChat(chat.id)
      setMessages([])
      await refreshChats(docId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create chat')
    }
  }

  const addDocument = async (file?: File) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const doc = await api.upload(file)
      const items = await refreshDocuments()
      setActiveDoc(doc.id)
      setChats([])
      setMessages([])
      const chat = await api.createChat(doc.id)
      setActiveChat(chat.id)
      await refreshChats(doc.id)
      setError('')
      // New uploads must be extracted before asking questions.
      void items
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const processDocument = async () => {
    if (!selectedDoc) return
    setBusy(true)
    setError('')
    try {
      await api.process(selectedDoc.id)
      await refreshDocuments()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Processing failed')
    } finally {
      setBusy(false)
    }
  }

  const sendMessage = async () => {
    const content = message.trim()
    if (!content || !activeChat || busy) return

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
      await api.send(activeChat, content)
      const history = await api.messages(activeChat)
      setMessages(history)
      if (activeDoc) await refreshChats(activeDoc)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send message')
      try {
        setMessages(await api.messages(activeChat))
      } catch {
        // Keep the optimistic message visible if history cannot load.
      }
    } finally {
      setBusy(false)
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

  setError('')
  try {
    await api.deleteChat(chat.id)

    const remaining = await api.chats(chat.document_id)
    setChats(remaining)

    if (activeChat === chat.id) {
      setActiveChat('')
      setMessages([])
    }
  } catch (e) {
    setError(e instanceof Error ? e.message : 'Could not delete chat')
  }
}

  return (
    <div className="app-shell">
      {sidebarOpen && (
        <aside className="sidebar">
          <div className="sidebar-top">
            <button className="icon-button" onClick={() => setSidebarOpen(false)} title="Close sidebar">
              <PanelLeft size={19} />
            </button>
            <div className="brand-mark">D</div>
            <span className="brand-name">Document AI</span>
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
              accept=".pdf,.txt,.md,.docx"
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
              : selectedDoc?.name ?? 'Document AI'}
          </div>
          <div className="topbar-actions">
            <span className="local-pill"><span /> Local AI</span>
            <button className="icon-button" onClick={() => void refreshDocuments()} title="Refresh documents">
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
                    <div className="message-author">{item.role === 'user' ? 'You' : 'Document AI'}</div>
                    <p>{item.content}</p>
                  </div>
                </div>
              ))}
              {busy && (
                <div className="assistant-message">
                  <div className="assistant-avatar"><Sparkles size={17} /></div>
                  <div><div className="message-author">Document AI</div><p>Thinking…</p></div>
                </div>
              )}
            </div>
          )}
        </section>

        {error && <div className="error-banner">{error}</div>}

        {selectedDoc && selectedDoc.status !== 'text_extracted' && (
          <div className="process-banner">
            <span>This document needs text extraction before you can ask questions.</span>
            <button disabled={busy} onClick={() => void processDocument()}>
              {busy ? 'Processing…' : 'Process document'}
            </button>
          </div>
        )}

        <footer className="composer-area">
          <div className="composer">
            <label className="composer-attach" title="Attach a document">
              <Paperclip size={19} />
              <input
                type="file"
                accept=".pdf,.txt,.md,.docx"
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
            Document AI can make mistakes. Verify important information against the source document.
          </p>
        </footer>
      </main>
    </div>
  )
  }

