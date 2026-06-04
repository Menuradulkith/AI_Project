// src/components/ClassifyBadge.jsx  –  show LLM classification result
const BOARD_STYLE = {
  'Localisation':     { bg: '#1a2e1f', color: '#34d399', border: '#10b98140', icon: '🌍' },
  'Not Localisation': { bg: '#1a1d2e', color: '#9ca3af', border: '#6b72804a', icon: '🚫' },
  Error:              { bg: '#2e0d0d', color: '#f87171', border: '#ef444440', icon: '⚠' },
}

const CONF_COLOR = { high: '#22c55e', medium: '#f59e0b', low: '#ef4444' }

export default function ClassifyBadge({ result, loading, compact = false }) {
  if (loading) return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: '#22263a', border: '1px solid #2e3250',
      borderRadius: 6, padding: compact ? '2px 8px' : '4px 10px',
      color: '#7b82a6', fontSize: 11, fontWeight: 500,
    }}>
      ⏳ Classifying…
    </span>
  )

  if (!result) return null

  const s = BOARD_STYLE[result.board] ?? BOARD_STYLE.Error

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: s.bg, border: `1px solid ${s.border}`,
      borderRadius: 6, padding: compact ? '2px 8px' : '4px 10px',
      fontSize: 11, fontWeight: 600,
    }}>
      <span>{s.icon}</span>
      <span style={{ color: s.color }}>{result.board}</span>
      {result.confidence && (
        <span style={{
          background: (CONF_COLOR[result.confidence] ?? '#7b82a6') + '22',
          color: CONF_COLOR[result.confidence] ?? '#7b82a6',
          fontSize: 10, fontWeight: 700, marginLeft: 2,
          padding: '1px 5px', borderRadius: 4,
        }}>
          {result.confidence}
        </span>
      )}
      {/* cached indicator */}
      {result.from_cache && (
        <span title="From cache — ticket hasn't changed" style={{
          color: '#555b7e', fontSize: 9, marginLeft: 2,
        }}>⚡cached</span>
      )}
      {result.investigated && (
        <span title={result.evidence || 'Gray zone — investigated with past patterns'} style={{
          color: '#a78bfa', fontSize: 9, marginLeft: 2,
        }}>🔍investigated</span>
      )}
    </span>
  )
}
