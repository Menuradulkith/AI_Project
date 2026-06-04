/* src/components/PriorityDot.jsx */
const COLOR = {
  highest: '#ef4444',
  high:    '#f97316',
  medium:  '#f59e0b',
  low:     '#22c55e',
  lowest:  '#14b8a6',
}

export default function PriorityDot({ priority = '' }) {
  const color = COLOR[priority.toLowerCase()] ?? '#7b82a6'
  return (
    <span title={priority} style={{
      display:       'inline-block',
      width:         8,
      height:        8,
      borderRadius:  '50%',
      background:    color,
      marginRight:   6,
      flexShrink:    0,
    }} />
  )
}
