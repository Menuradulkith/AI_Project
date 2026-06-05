import { useState, useRef, useEffect } from 'react'
import { sendChatMessage } from '../api'

const SUGGESTIONS = [
  'How many tickets are classified?',
  'Show Localisation tickets with low confidence',
  'List tickets needing manual review',
  'Show Localisation tickets',
]

export default function ChatPanel({ onClose }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        'Hi! I can help you query ticket classifications.\n\n' +
        'Try asking about Localisation tickets, manual review items, or a specific ticket ID.',
    },
  ])
  const [input, setInput]     = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef             = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text) => {
    const message = (text || input).trim()
    if (!message || loading) return

    const userMsg  = { role: 'user', content: message }
    const nextMsgs = [...messages, userMsg]
    setMessages(nextMsgs)
    setInput('')
    setLoading(true)

    try {
      const data = await sendChatMessage(message, nextMsgs.slice(-10))
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.ok ? data.reply : `Error: ${data.error}`,
        },
      ])
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Connection error: ${e.message}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.panel}>
      {/* Header */}
      <div style={styles.header}>
        <span style={{ color: 'var(--text)', fontWeight: 600, fontSize: 14 }}>
          🤖 Assistant
        </span>
        <button onClick={onClose} style={styles.closeBtn}>
          ✕
        </button>
      </div>

      {/* Messages */}
      <div style={styles.body}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              ...styles.bubble,
              alignSelf:  m.role === 'user' ? 'flex-end' : 'flex-start',
              background: m.role === 'user' ? 'var(--accent)' : 'var(--surface3)',
              borderRadius:
                m.role === 'user'
                  ? '12px 12px 2px 12px'
                  : '12px 12px 12px 2px',
            }}
          >
            {m.content}
          </div>
        ))}

        {loading && (
          <div
            style={{
              ...styles.bubble,
              alignSelf: 'flex-start',
              background: 'var(--surface3)',
              color: 'var(--text-muted)',
            }}
          >
            thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestion chips — only on fresh start */}
      {messages.length <= 1 && (
        <div style={styles.suggestions}>
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => send(s)} style={styles.chip}>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input bar */}
      <div style={styles.inputBar}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about tickets…"
          disabled={loading}
          style={styles.input}
        />
        <button
          onClick={() => send()}
          disabled={!input.trim() || loading}
          style={{
            ...styles.sendBtn,
            background: input.trim() && !loading ? 'var(--accent)' : 'var(--surface3)',
            cursor: input.trim() && !loading ? 'pointer' : 'default',
          }}
        >
          ↑
        </button>
      </div>
    </div>
  )
}

const styles = {
  panel: {
    position: 'fixed',
    bottom: 24,
    right: 24,
    width: 380,
    maxHeight: 560,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 12,
    display: 'flex',
    flexDirection: 'column',
    boxShadow: 'var(--shadow)',
    zIndex: 1000,
  },
  header: {
    padding: '12px 16px',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 16,
    padding: '2px 6px',
  },
  body: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  bubble: {
    maxWidth: '85%',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 13,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  suggestions: {
    padding: '0 12px 8px',
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
  },
  chip: {
    background: 'var(--surface3)',
    border: '1px solid var(--border)',
    borderRadius: 20,
    color: 'var(--text-muted)',
    fontSize: 11,
    padding: '4px 10px',
    cursor: 'pointer',
  },
  inputBar: {
    padding: '8px 12px 12px',
    display: 'flex',
    gap: 8,
  },
  input: {
    flex: 1,
    background: 'var(--surface3)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    color: 'var(--text)',
    fontSize: 13,
    padding: '8px 12px',
    outline: 'none',
  },
  sendBtn: {
    border: 'none',
    borderRadius: 8,
    color: '#fff',
    padding: '8px 14px',
    fontSize: 16,
  },
}
