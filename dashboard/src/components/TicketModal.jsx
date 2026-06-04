/* src/components/TicketModal.jsx  – full detail side-panel */
import { useEffect, useState } from 'react'
import { fetchTicket } from '../api'
import StatusBadge   from './StatusBadge'
import PriorityDot   from './PriorityDot'
import ClassifyBadge from './ClassifyBadge'

const s = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(3,7,18,.65)',
    display: 'flex', justifyContent: 'flex-end', zIndex: 999,
  },
  panel: {
    background: 'var(--surface)', width: '520px', maxWidth: '95vw',
    height: '100vh', overflowY: 'auto',
    padding: '28px 28px 48px',
    boxShadow: '-8px 0 40px rgba(0,0,0,.5)',
    display: 'flex', flexDirection: 'column', gap: 20,
    animation: 'slideIn .2s ease',
  },
  closeBtn: {
    alignSelf: 'flex-end', background: 'transparent',
    border: '1px solid var(--border)', color: 'var(--text-muted)',
    borderRadius: 8, padding: '4px 12px', cursor: 'pointer',
    fontSize: 18, lineHeight: 1,
  },
  row:     { display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' },
  label:   { color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 4 },
  value:   { color: 'var(--text)', fontSize: 13 },
  section: { borderTop: '1px solid var(--border)', paddingTop: 16 },
  commentBox: {
    background: 'var(--surface2)', borderRadius: 10, padding: '10px 14px',
    marginBottom: 10, border: '1px solid var(--border)',
  },
  commentMeta: { color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 },
  commentBody: { color: '#c9cce0', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' },
  loading: { color: 'var(--text-muted)', padding: '40px 0', textAlign: 'center' },
  ticketId: {
    fontFamily: 'monospace', background: 'var(--surface3)',
    color: 'var(--accent)', padding: '2px 8px', borderRadius: 6, fontSize: 13,
  },
  classifyBtn: {
    background: '#1a2a4a', border: '1px solid #3b82f640',
    borderRadius: 8, color: '#8ab4ff',
    padding: '8px 16px', fontSize: 12, fontWeight: 600,
    cursor: 'pointer', transition: 'background .15s',
    alignSelf: 'flex-start',
  },
  aiBox: {
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: 12, padding: '14px 16px',
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  signal: {
    display: 'inline-block', background: 'var(--surface3)',
    border: '1px solid var(--border)', borderRadius: 6,
    padding: '2px 8px', fontSize: 11, color: '#c9cce0',
    margin: '2px 3px 2px 0',
  },
}

export default function TicketModal({ ticketId, onClose }) {
  const [ticket,  setTicket]  = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchTicket(ticketId)
      .then(setTicket)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [ticketId])

  useEffect(() => {
    const h = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // Get classification from ticket data (stored from SQLite)
  const aiResult = ticket?._classification || null

  return (
    <>
      <style>{`@keyframes slideIn{from{transform:translateX(40px);opacity:0}to{transform:none;opacity:1}}`}</style>
      <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
        <div style={s.panel}>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)">✕</button>

          {loading && <div style={s.loading}>Loading…</div>}

          {!loading && ticket && (
            <>
              {/* Header */}
              <div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
                  <span style={s.ticketId}>{ticket.ticket_id}</span>
                  {ticket.cs_ref && <span style={{ ...s.ticketId, color: '#a855f7' }}>{ticket.cs_ref}</span>}
                  <StatusBadge status={ticket.status} />
                </div>
                <h2 style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.4, color: 'var(--text)' }}>
                  {ticket.summary}
                </h2>
              </div>

              {/* AI Classification panel */}
              <div style={s.section}>
                <div style={{ ...s.label, marginBottom: 10 }}>🧠 AI Classification</div>
                <div style={s.aiBox}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <ClassifyBadge result={aiResult} />
                    {aiResult?.needs_review && (
                      <span style={{ 
                        background: '#f59e0b20', border: '1px solid #f59e0b',
                        borderRadius: 4, padding: '2px 8px', color: '#f59e0b', fontSize: 11 
                      }}>
                        ⚠️ Needs Manual Review
                      </span>
                    )}
                  </div>

                  {aiResult && aiResult.board && (
                    <>
                      {aiResult.reason && (
                        <div>
                          <div style={s.label}>Reason</div>
                          <div style={{ ...s.value, lineHeight: 1.6 }}>{aiResult.reason}</div>
                        </div>
                      )}
                      {aiResult.signals?.length > 0 && (
                        <div>
                          <div style={s.label}>Signals detected</div>
                          <div>{aiResult.signals.map((sig, i) => (
                            <span key={i} style={s.signal}>{sig}</span>
                          ))}</div>
                        </div>
                      )}
                      {aiResult.classified_at && (
                        <div style={{ color: '#555b7e', fontSize: 11 }}>
                          Classified at: {aiResult.classified_at}
                        </div>
                      )}
                    </>
                  )}

                  {!aiResult && (
                    <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                      Not classified yet. Run "Manual Sync" to classify tickets.
                    </div>
                  )}
                </div>
              </div>

              {/* Meta grid */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                {[
                  ['Type',     ticket.issue_type],
                  ['Priority', <span style={s.row}><PriorityDot priority={ticket.priority} />{ticket.priority}</span>],
                  ['Reporter', ticket.reporter],
                  ['Assignee', ticket.assignee],
                  ['Created',  ticket.created],
                  ['Updated',  ticket.updated],
                  ...(ticket.sprint       ? [['Sprint',  ticket.sprint]]               : []),
                  ...(ticket.labels?.length ? [['Labels', ticket.labels.join(', ')]] : []),
                ].map(([lbl, val]) => (
                  <div key={lbl}>
                    <div style={s.label}>{lbl}</div>
                    <div style={s.value}>{val}</div>
                  </div>
                ))}
              </div>

              {/* Description */}
              <div style={s.section}>
                <div style={s.label}>Description</div>
                <p style={{ ...s.value, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                  {ticket.description || <span style={{ color: 'var(--text-muted)' }}>(no description)</span>}
                </p>
              </div>

              {/* Comments */}
              {ticket.comments?.length > 0 && (
                <div style={s.section}>
                  <div style={{ ...s.label, marginBottom: 12 }}>
                    Comments ({ticket.comments.length})
                  </div>
                  {ticket.comments.map((c, i) => (
                    <div key={i} style={s.commentBox}>
                      <div style={s.commentMeta}>
                        <strong style={{ color: '#c9cce0' }}>{c.author}</strong>
                        &nbsp;·&nbsp;{c.created}
                      </div>
                      <div style={s.commentBody}>{c.body || '(empty)'}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}
