/* src/components/TicketCard.jsx */
import StatusBadge   from './StatusBadge'
import PriorityDot   from './PriorityDot'
import ClassifyBadge from './ClassifyBadge'

const s = {
  card: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 12,
    padding: '16px 18px',
    cursor: 'pointer',
    transition: 'border-color var(--transition), box-shadow var(--transition)',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  cardReview: {
    border: '1px solid #f59e0b',
    background: 'var(--surface)',
  },
  cardReadOnly: {
    opacity: 0.85,
    cursor: 'default',
  },
  topRow:   { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  ticketId: { fontFamily: 'monospace', color: 'var(--accent)', fontSize: 12, fontWeight: 700 },
  csRef:    { fontFamily: 'monospace', color: 'var(--purple)', fontSize: 12 },
  summary:  { color: 'var(--text)', fontSize: 14, fontWeight: 600, lineHeight: 1.45 },
  meta:     { display: 'flex', gap: 16, flexWrap: 'wrap', color: 'var(--text-muted)', fontSize: 11.5 },
  metaItem: { display: 'flex', alignItems: 'center', gap: 4 },
  updated:  { marginLeft: 'auto', color: '#6d7898', fontSize: 11 },
  footer:   { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  reviewBadge: {
    background: '#f59e0b1f',
    border: '1px solid #f59e0b80',
    borderRadius: 4,
    color: '#f59e0b',
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
  },
  movedBadge: {
    background: '#22c55e1f',
    border: '1px solid #22c55e80',
    borderRadius: 4,
    color: '#22c55e',
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
  },
}

export default function TicketCard({ ticket, onClick, classification, highlight, readOnly }) {
  const isReview = highlight === 'review' || classification?.needs_review

  const cardStyle = {
    ...s.card,
    ...(isReview ? s.cardReview : {}),
    ...(readOnly ? s.cardReadOnly : {}),
  }

  return (
    <div
      style={cardStyle}
      onClick={() => onClick(ticket.ticket_id)}
      onMouseEnter={e => {
        if (!readOnly) {
          e.currentTarget.style.borderColor = isReview ? '#f59e0b' : 'var(--accent)'
          e.currentTarget.style.boxShadow   = '0 0 0 1px rgba(79,142,247,.2), 0 8px 20px rgba(17,24,39,.35)'
        }
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = isReview ? '#f59e0b' : 'var(--border)'
        e.currentTarget.style.boxShadow   = 'none'
      }}
    >
      {/* top row: id + cs ref + status + updated */}
      <div style={s.topRow}>
        <span style={s.ticketId}>{ticket.ticket_id}</span>
        {ticket.cs_ref && <span style={s.csRef}>{ticket.cs_ref}</span>}
        <StatusBadge status={ticket.status} />
        <span style={s.updated}>{ticket.updated}</span>
      </div>

      {/* summary */}
      <div style={s.summary}>{ticket.summary}</div>

      {/* meta row */}
      <div style={s.meta}>
        <div style={s.metaItem}><PriorityDot priority={ticket.priority} />{ticket.priority}</div>
        <div style={s.metaItem}><span>🏷</span>{ticket.issue_type}</div>
        <div style={s.metaItem}><span>👤</span>{ticket.reporter}</div>
        <div style={s.metaItem}><span>👷</span>{ticket.assignee}</div>

      </div>

      {/* footer: classification badge + status indicators */}
      <div style={s.footer}>
        {classification ? (
          <ClassifyBadge result={classification} />
        ) : (
          <span style={{ color: '#6d7898', fontSize: 11 }}>Not classified</span>
        )}
        
        {isReview && (
          <span style={s.reviewBadge}>⚠️ REVIEW</span>
        )}
        
        {readOnly && ticket._moved_at && (
          <span style={s.movedBadge}>✓ MOVED</span>
        )}
      </div>
    </div>
  )
}
