/* src/components/StatusBadge.jsx */
const PALETTE = {
  // Board column names (sidebar)
  'to do':                    { bg: '#1e2a4a', color: '#4f8ef7', label: 'To Do'                   },
  'in progress':              { bg: '#2a2000', color: '#f59e0b', label: 'In Progress'              },
  'resolved':                 { bg: '#0d2e1f', color: '#22c55e', label: 'Resolved'                 },
  'done':                     { bg: '#0d2e1f', color: '#22c55e', label: 'Done'                     },
  // Real Jira statuses in the FIZ project
  'new':                      { bg: '#1e2a4a', color: '#4f8ef7', label: 'New'                      },
  'open':                     { bg: '#1e2a4a', color: '#4f8ef7', label: 'Open'                     },
  'reopened':                 { bg: '#2a1a00', color: '#fb923c', label: 'Reopened'                  },
  'on hold':                  { bg: '#1f1a2e', color: '#a855f7', label: 'On Hold'                  },
  'rework required':          { bg: '#2a1a00', color: '#fb923c', label: 'Rework Required'           },
  'ready for investigation':  { bg: '#1e2a4a', color: '#60a5fa', label: 'Ready for Investigation'  },
  'under analysis':           { bg: '#2a2000', color: '#f59e0b', label: 'Under Analysis'           },
  'under investigation':      { bg: '#2a2000', color: '#f59e0b', label: 'Under Investigation'      },
  'awaiting information':     { bg: '#2a2000', color: '#fbbf24', label: 'Awaiting Information'     },
  'fix in progress':          { bg: '#2a2000', color: '#f59e0b', label: 'Fix In Progress'          },
  'ready for development':    { bg: '#2a2000', color: '#34d399', label: 'Ready for Development'    },
  'in review':                { bg: '#1a1f2e', color: '#818cf8', label: 'In Review'                },
  'pr review':                { bg: '#1a1f2e', color: '#818cf8', label: 'PR Review'                },
  'ready for pr review':      { bg: '#1a1f2e', color: '#818cf8', label: 'Ready For PR Review'      },
  'in test':                  { bg: '#1a1f2e', color: '#c084fc', label: 'In Test'                  },
  'ready for verification':   { bg: '#1a1f2e', color: '#c084fc', label: 'Ready For Verification'   },
  'verification in progress': { bg: '#1a1f2e', color: '#c084fc', label: 'Verification In Progress' },
  'ready for review':         { bg: '#1a1f2e', color: '#818cf8', label: 'Ready For Review'         },
  'requirements gathering':   { bg: '#2a2000', color: '#f59e0b', label: 'Requirements Gathering'   },
  'ready to use':             { bg: '#0d2e1f', color: '#22c55e', label: 'Ready to Use'             },
  'closed':                   { bg: '#1a1f2e', color: '#6b7280', label: 'Closed'                   },
  'cancelled':                { bg: '#2e0d0d', color: '#ef4444', label: 'Cancelled'                },
  'approved':                 { bg: '#0d2e1f', color: '#22c55e', label: 'Approved'                 },
  'completed':                { bg: '#0d2e1f', color: '#22c55e', label: 'COMPLETED'                },
  'obsolete':                 { bg: '#1a1f2e', color: '#6b7280', label: 'Obsolete'                 },
  'not applicable':           { bg: '#1a1f2e', color: '#6b7280', label: 'Not Applicable'           },
  'exempted':                 { bg: '#1a1f2e', color: '#6b7280', label: 'Exempted'                 },
  'blocked':                  { bg: '#2e0d0d', color: '#ef4444', label: 'Blocked'                  },
}

export default function StatusBadge({ status = '' }) {
  const key   = status.toLowerCase()
  const style = PALETTE[key] ?? { bg: '#22263a', color: '#7b82a6', label: status }

  return (
    <span style={{
      background:    style.bg,
      color:         style.color,
      border:        `1px solid ${style.color}33`,
      borderRadius:  '6px',
      padding:       '2px 8px',
      fontSize:      '11px',
      fontWeight:    600,
      letterSpacing: '.4px',
      textTransform: 'uppercase',
      whiteSpace:    'nowrap',
    }}>
      {style.label}
    </span>
  )
}
