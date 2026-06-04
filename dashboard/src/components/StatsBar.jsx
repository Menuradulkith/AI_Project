/* src/components/StatsBar.jsx  –  counts per status for current tab */

// Colour map covers all known FIZ project status names
const COLORS = {
  // To Do category
  'New':                      '#4f8ef7',
  'Open':                     '#4f8ef7',
  'Reopened':                 '#4f8ef7',
  'Ready for Investigation':  '#4f8ef7',
  // In Progress category
  'Under Investigation':      '#f59e0b',
  'Fix In Progress':          '#f59e0b',
  'Awaiting Information':     '#f59e0b',
  // Done / Closed category
  'Resolved':                 '#22c55e',
  'Closed':                   '#6b7280',
  'Cancelled':                '#6b7280',
  'Approved':                 '#22c55e',
  'COMPLETED':                '#22c55e',
}

export default function StatsBar({ counts, activeStatus }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1])
  const total   = entries.reduce((s, [, c]) => s + c, 0)

  if (total === 0) return null   // nothing loaded yet – hide the bar

  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>

      {/* sub-status breakdown */}
      {entries.map(([status, count]) => (
        <div key={status} style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '8px 14px',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          minWidth: 80,
        }}>
          <span style={{
            fontSize: 22, fontWeight: 700,
            color: COLORS[status] ?? '#7b82a6',
          }}>{count}</span>
          <span style={{
            color: 'var(--text-muted)', fontSize: 10, marginTop: 2,
            textAlign: 'center', maxWidth: 100,
          }}>{status}</span>
        </div>
      ))}

      {/* total */}
      <div style={{
        background: 'var(--surface2)', border: '1px solid #3b82f640',
        borderRadius: 10, padding: '8px 14px',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        minWidth: 80,
      }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: '#e4e6f0' }}>{total}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 10, marginTop: 2 }}>Total</span>
      </div>
    </div>
  )
}

