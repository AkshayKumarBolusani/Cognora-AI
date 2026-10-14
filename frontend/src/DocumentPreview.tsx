
import { useEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { FileText, Minus, Plus } from 'lucide-react'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from './api'

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc

const pdfAssetBase = `${import.meta.env.BASE_URL}pdfjs/`
const pdfOptions = {
  cMapUrl: `${pdfAssetBase}cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${pdfAssetBase}standard_fonts/`,
  wasmUrl: `${pdfAssetBase}wasm/`,
}

export type CitationTarget = {
  page: number | null
  quote?: string
  id?: string
  documentName?: string
}

type Props = {
  documentId: string
  documentName: string
  citation?: CitationTarget | null
}

export default function DocumentPreview({
  documentId,
  documentName,
  citation,
}: Props) {
  const extension = documentName.split('.').pop()?.toLowerCase() ?? ''
  const isPdf = extension === 'pdf'
  const isImage = ['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp'].includes(extension)
  const [pageCount, setPageCount] = useState(0)
  const [scale, setScale] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [loadProgress, setLoadProgress] = useState<number | null>(null)
  const [citationHighlighted, setCitationHighlighted] = useState(false)
  const [pdfSource, setPdfSource] = useState<string | { data: Uint8Array } | null>(null)
  const [previewText, setPreviewText] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})

  useEffect(() => {
    setPageCount(0)
    setError('')
    setLoading(true)
    setLoadProgress(null)
    setPdfSource(null)
    pageRefs.current = {}

    if (scrollRef.current) scrollRef.current.scrollTop = 0
    if (!isPdf) return
    let cancelled = false
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 20000)
    void (async () => {
      try {
        const url = api.documentFileUrl(documentId)
        const response = await fetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`PDF request failed (${response.status}).`)
        const contentLength = Number(response.headers.get('content-length'))
        // Small PDFs are passed to PDF.js as bytes to avoid a stalled cross-origin
        // range stream. Large PDFs keep PDF.js's streaming path to limit memory use.
        if (!contentLength || contentLength > 32 * 1024 * 1024) {
          setPdfSource(url)
          return
        }
        const data = new Uint8Array(await response.arrayBuffer())
        if (!controller.signal.aborted) setPdfSource({ data })
      } catch (cause) {
        if (cancelled) return
        if (controller.signal.aborted) {
          setError('The PDF request timed out. Check the API connection and retry.')
          setLoading(false)
        } else {
          setError(cause instanceof Error ? cause.message : 'Could not retrieve this PDF.')
          setLoading(false)
        }
      } finally {
        window.clearTimeout(timer)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [documentId, attempt, isPdf])

  useEffect(() => {
    if (isPdf) return
    let cancelled = false
    setError('')
    setPreviewText('')
    setLoading(true)
    setLoadProgress(null)
    if (isImage) {
      setLoading(false)
      return
    }
    void api.documentPreview(documentId).then(result => {
      if (cancelled) return
      setPreviewText(result.text)
      setLoading(false)
    }).catch(cause => {
      if (cancelled) return
      setError(cause instanceof Error ? cause.message : 'Could not create a document preview.')
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [documentId, isPdf, isImage, attempt])

  useEffect(() => {
    if (!loading || !isPdf) return
    const timeout = window.setTimeout(() => {
      setLoading(false)
      setError('The PDF did not finish loading. Check the API connection and retry.')
    }, 20000)
    return () => window.clearTimeout(timeout)
  }, [loading, attempt, isPdf])

  useEffect(() => {
    document.querySelectorAll('.citation-match-highlight').forEach(node => node.remove())
    if (!citation) {
      setCitationHighlighted(false)
      return
    }
    if (!citation.page || citation.page < 1) {
      setCitationHighlighted(false)
      return
    }

    const target = pageRefs.current[citation.page]
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    const normalize = (value: string) => value.toLowerCase().replace(/\s+/g, ' ').trim()
    const quote = normalize(citation.quote || '')
    if (!target || !quote) {
      setCitationHighlighted(false)
      return
    }

    setCitationHighlighted(false)
    const highlight = () => {
      const spans = Array.from(target.querySelectorAll<HTMLElement>('.react-pdf__Page__textContent span'))
      if (!spans.length) return false
      let pageText = ''
      const positions: Array<{ node: Text; offset: number }> = []
      const append = (character: string, node: Text, offset: number) => {
        if (/\s/.test(character)) {
          if (pageText && !pageText.endsWith(' ')) {
            pageText += ' '
            positions.push({ node, offset })
          }
          return
        }
        const lowered = character.toLowerCase()
        pageText += lowered
        for (let index = 0; index < lowered.length; index += 1) {
          positions.push({ node, offset })
        }
      }
      for (const span of spans) {
        const walker = document.createTreeWalker(span, NodeFilter.SHOW_TEXT)
        let textNode = walker.nextNode() as Text | null
        if (pageText && textNode) append(' ', textNode, 0)
        while (textNode) {
          const raw = textNode.data
          for (let offset = 0; offset < raw.length; offset += 1) {
            append(raw[offset], textNode, offset)
          }
          textNode = walker.nextNode() as Text | null
        }
      }
      const quoteWords = quote.split(' ').filter(Boolean)
      const candidates = [quote]
      for (const sentence of (citation.quote || '').split(/(?<=[.!?])\s+|\n+/)) {
        const normalized = normalize(sentence)
        if (normalized && !candidates.includes(normalized)) candidates.push(normalized)
      }
      for (let windowSize = Math.min(24, quoteWords.length); windowSize >= 6; windowSize -= 1) {
        for (let offset = 0; offset + windowSize <= quoteWords.length; offset += Math.max(1, Math.floor(windowSize / 2))) {
          candidates.push(quoteWords.slice(offset, offset + windowSize).join(' '))
        }
      }
      let start = -1
      let matchLength = 0
      for (const candidate of candidates) {
        const candidateStart = pageText.indexOf(candidate)
        if (candidateStart >= 0) {
          start = candidateStart
          matchLength = candidate.length
          break
        }
      }
      if (start < 0) return false
      const last = start + matchLength - 1
      const startPosition = positions[start]
      const endPosition = positions[last]
      if (!startPosition || !endPosition) return false
      const range = document.createRange()
      range.setStart(startPosition.node, startPosition.offset)
      range.setEnd(endPosition.node, endPosition.offset + 1)
      const pageBounds = target.getBoundingClientRect()
      target.style.position = 'relative'
      let markerCount = 0
      for (const rect of Array.from(range.getClientRects())) {
        if (!rect.width || !rect.height) continue
        const marker = document.createElement('span')
        marker.className = 'citation-match-highlight'
        marker.setAttribute('aria-hidden', 'true')
        marker.style.left = String(rect.left - pageBounds.left) + 'px'
        marker.style.top = String(rect.top - pageBounds.top) + 'px'
        marker.style.width = String(rect.width) + 'px'
        marker.style.height = String(rect.height) + 'px'
        target.appendChild(marker)
        markerCount += 1
      }
      if (!markerCount) return false
      setCitationHighlighted(true)
      return true
    }

    if (highlight()) return
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      if (highlight() || tries >= 20) {
        window.clearInterval(timer)
        if (tries >= 20) setCitationHighlighted(false)
      }
    }, 100)
    return () => window.clearInterval(timer)
  }, [citation, pageCount, scale])

  return (
    <section className="document-preview" aria-label="Document preview">
      <header className="preview-toolbar">
        <div className="preview-file-name" title={documentName}>
          <FileText size={17} />
          <span>{documentName}</span>
        </div>

        <div className="preview-controls">
          <span className="preview-page-count">
            {loading ? 'Loading…' : isPdf ? (error ? 'PDF unavailable' : String(pageCount) + ' pages') : isImage ? 'Image preview' : 'Extracted content'}
          </span>

          {isPdf && <>
            <span className="preview-divider" />
            <button
              type="button"
              aria-label="Zoom out"
              title="Zoom out"
              disabled={scale <= 0.6}
              onClick={() => setScale(value => Math.max(0.6, value - 0.1))}
            >
              <Minus size={16} />
            </button>
            <span className="preview-zoom">{Math.round(scale * 100)}%</span>
            <button
              type="button"
              aria-label="Zoom in"
              title="Zoom in"
              disabled={scale >= 1.8}
              onClick={() => setScale(value => Math.min(1.8, value + 0.1))}
            >
              <Plus size={16} />
            </button>
          </>}
        </div>
      </header>

      {citation && (
        <div className="preview-citation-notice">
          <strong>{citation.documentName ?? 'Source'}{citation.page ? ` · Page ${citation.page}` : ' · Page location unavailable'}</strong>
          {citationHighlighted && <span>Matching text highlighted on this page.</span>}
          {!citation.page && <span>Page number unavailable for this extracted passage.</span>}
        </div>
      )}

      <div className="preview-canvas" ref={scrollRef}>
        {!isPdf ? (
          loading ? <p className="preview-status">Loading preview…</p> : error ? (
            <div className="preview-status" role="status">
              <FileText size={30} />
              <p>{error}</p>
              <p>Process this document first if its extracted content is not available yet.</p>
              <button type="button" onClick={() => setAttempt(value => value + 1)}>Retry preview</button>
            </div>
          ) : isImage ? (
            <div className="image-preview">
              <img src={api.documentPreviewImageUrl(documentId)} alt={documentName} />
            </div>
          ) : (
            <article className="text-preview">
              <div className="text-preview-label">{documentName} · extracted text</div>
              <pre>{previewText || 'No text was extracted from this document.'}</pre>
            </article>
          )
        ) : pdfSource ? (
          <Document
            key={`${documentId}-${attempt}`}
            file={pdfSource}
            options={pdfOptions}
            // Keep PDF.js loading inside this client component's explicit loading/error UI.
            // React-PDF's default Suspense mode can leak a pending promise to the app root
            // during rapid document navigation and trigger React's async-client error.
            suspense={false}
            onLoadSuccess={({ numPages }) => {
              setPageCount(numPages)
              setLoading(false)
              setError('')
              setLoadProgress(100)
            }}
            onLoadProgress={({ loaded, total }) => {
              setLoadProgress(total ? Math.round((loaded / total) * 100) : null)
            }}
            onLoadError={err => {
              setLoading(false)
              setError(err.message || 'Could not load this PDF.')
            }}
            onSourceError={err => {
              setLoading(false)
              setError(err.message || 'Could not retrieve this PDF.')
            }}
            loading={<p className="preview-status">{loadProgress === null ? 'Loading document…' : `Loading document… ${loadProgress}%`}</p>}
            error={<p className="preview-status">Could not load this PDF.</p>}
          >
          {Array.from({ length: pageCount }, (_, index) => {
            const pageNumber = index + 1

            return (
              <div
                className="pdf-page-wrapper"
                key={`${documentId}-${pageNumber}`}
                ref={element => {
                  pageRefs.current[pageNumber] = element
                }}
                data-page-number={pageNumber}
              >
                <div className="pdf-page-label">Page {pageNumber}</div>
                <Page
                  pageNumber={pageNumber}
                  scale={scale}
                  renderTextLayer
                  renderAnnotationLayer
                />
              </div>
            )
          })}
          </Document>
        ) : !error ? <p className="preview-status">Loading PDF…</p> : null}

        {error && (
          <div className="preview-status" role="alert">
            <p>{error}</p>
            <button type="button" onClick={() => {
              setError('')
              setLoading(true)
              setLoadProgress(null)
              setPdfSource(null)
              setAttempt(value => value + 1)
            }}>Retry PDF</button>
          </div>
        )}
      </div>
    </section>
  )
}
