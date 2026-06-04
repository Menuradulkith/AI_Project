/* src/components/PerformancePage.jsx  –  Model Performance & Scheduler Control */
import { useEffect, useState, useCallback } from 'react'
import {
  fetchDashboardStats,
  getSyncStatus,
  startScheduler,
  stopScheduler,
} from '../api'

// ── tiny helpers ──────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, color = 'var(--accent)' }) {
  return (
    <div style={s.kpi}>
      <div style={{ ...s.kpiValue, color }}>{value ?? '—'}</div>
      <div style={s.kpiLabel}>{label}</div>
      {sub && <div style={s.kpiSub}>{sub}</div>}
    </div>
  )
}

function ConfBar({ label, count, total, color }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600 }}>{label}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{count} &nbsp;·&nbsp; {pct}%</span>
      </div>
      <div style={s.barTrack}>
        <div style={{ ...s.barFill, width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

function SyncRow({ run }) {
  const hasError  = !!run.errors
  const statusCol = hasError ? '#ef4444' : '#22c55e'
  return (
    <div style={s.syncRow}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
        <span style={{ ...s.syncDot, background: statusCol }} />
        <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600 }}>
          {run.trigger_type === 'manual' ? 'Manual' : 'Scheduled'}
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 'auto', whiteSpace: 'nowrap' }}>
          {run.run_at ? new Date(run.run_at).toLocaleString() : '—'}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 4, flexWrap: 'wrap' }}>
        {[
          ['Fetched',     run.tickets_fetched,     '#60a5fa'],
          ['Classified',  run.tickets_classified,  '#34d399'],
          ['Flagged',     run.tickets_flagged,     '#f59e0b'],
          ['Duration',    run.duration_sec ? `${run.duration_sec}s` : '—', '#9aa4bf'],
        ].map(([k, v, c]) => (
          <span key={k} style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            {k}: <span style={{ color: c, fontWeight: 600 }}>{v ?? '—'}</span>
          </span>
        ))}
        {hasError && (
          <span style={{ color: '#ef4444', fontSize: 11, wordBreak: 'break-all' }}>
            ⚠ {run.errors}
          </span>
        )}
      </div>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────
export default function PerformancePage() {
  const [stats,        setStats]        = useState(null)
  const [syncStatus,   setSyncStatus]   = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [toggling,     setToggling]     = useState(false)
  const [error,        setError]        = useState(null)

  const load = useCallback(async () => {
    try {
      const [st, sy] = await Promise.all([fetchDashboardStats(), getSyncStatus()])
      setStats(st)
      setSyncStatus(sy)
    } catch (e) {
      setError('Failed to load performance data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSchedulerToggle = async () => {
    setToggling(true)
    try {
      if (syncStatus?.scheduler?.running) {
        await stopScheduler()
      } else {
        await startScheduler()
      }
      // Re-fetch scheduler state
      const sy = await getSyncStatus()
      setSyncStatus(sy)
    } catch (e) {
      setError(`Scheduler toggle failed: ${e.message}`)
    } finally {
      setToggling(false)
    }
  }

  const isRunning = syncStatus?.scheduler?.running
  const cls       = stats?.fiz_classified ?? 0
  const total     = stats?.fiz_total      ?? 0
  const conf      = stats?.confidence_breakdown ?? {}
  const board     = stats?.board_split ?? {}
  const runs      = syncStatus?.recent_runs ?? []
  const jobs      = syncStatus?.scheduler?.jobs ?? []

  return (
    <div style={s.page}>
      {/* ── header ── */}
      <div style={s.pageHeader}>
        <div>
          <h2 style={s.pageTitle}>Model Performance</h2>
          <p style={s.pageSub}>Classification accuracy, sync history, and scheduler control</p>
        </div>
        <button style={s.refreshBtn} onClick={load} disabled={loading}>
          {loading ? '⏳' : '↺'} Refresh
        </button>
      </div>

      {error && <div style={s.errorBanner}>{error}</div>}

      {/* ── KPI row ── */}
      <div style={s.kpiRow}>
        <Kpi
          label="Total FIZ Tickets"
          value={total}
          sub="in database"
          color="var(--text)"
        />
        <Kpi
          label="Classified"
          value={cls}
          sub={`${total > 0 ? Math.round(cls / total * 100) : 0}% of total`}
          color="#34d399"
        />
        <Kpi
          label="Localisation"
          value={board.localisation ?? 0}
          sub="identified"
          color="#60a5fa"
        />
        <Kpi
          label="Needs Review"
          value={stats?.fiz_needs_review ?? 0}
          sub="medium / low confidence"
          color="#f59e0b"
        />
        <Kpi
          label="Auto-Route Rate"
          value={`${stats?.automation_rate ?? 0}%`}
          sub="high confidence"
          color="#a78bfa"
        />
        <Kpi
          label="Est. LLM Cost"
          value={`$${stats?.estimated_llm_cost_usd ?? '0.0000'}`}
          sub={`across ${stats?.total_sync_runs ?? 0} sync runs`}
          color="#f472b6"
        />
      </div>

      <div style={s.twoCol}>
        {/* ── left: confidence + board breakdown ── */}
        <div style={s.card}>
          <div style={s.cardHeader}>Confidence Breakdown</div>
          <ConfBar label="High"   count={conf.high   ?? 0} total={cls} color="#22c55e" />
          <ConfBar label="Medium" count={conf.medium ?? 0} total={cls} color="#f59e0b" />
          <ConfBar label="Low"    count={conf.low    ?? 0} total={cls} color="#ef4444" />

          <div style={{ ...s.cardHeader, marginTop: 20 }}>Board Split</div>
          <ConfBar label="Localisation"     count={board.localisation     ?? 0} total={cls} color="#60a5fa" />
          <ConfBar label="Not Localisation" count={board.not_localisation ?? 0} total={cls} color="#9ca3af" />
        </div>

        {/* ── right: scheduler control ── */}
        <div style={s.card}>
          <div style={s.cardHeader}>APScheduler</div>

          {/* status indicator */}
          <div style={s.schedulerStatus}>
            <span style={{ ...s.statusDot, background: isRunning ? '#22c55e' : '#6b7280' }} />
            <span style={{ color: 'var(--text)', fontWeight: 600, fontSize: 14 }}>
              {isRunning ? 'Running' : 'Stopped'}
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 'auto' }}>
              {isRunning ? 'Syncs automatically at scheduled times' : 'No automatic syncs — manual only'}
            </span>
          </div>

          {/* scheduled jobs */}
          {jobs.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              {jobs.map(j => (
                <div key={j.id} style={s.jobRow}>
                  <span style={{ color: '#60a5fa', fontWeight: 600, fontSize: 12 }}>⏰ {j.name}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                    Next: {j.next_run ? new Date(j.next_run).toLocaleString() : 'pending'}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* toggle button */}
          <button
            style={{
              ...s.toggleBtn,
              background: isRunning ? '#2e0d0d' : '#0d2e1a',
              border: isRunning ? '1px solid #ef444460' : '1px solid #22c55e60',
              color: isRunning ? '#f87171' : '#34d399',
              opacity: toggling ? 0.6 : 1,
            }}
            onClick={handleSchedulerToggle}
            disabled={toggling}
          >
            {toggling
              ? '⏳ Please wait…'
              : isRunning
                ? '⏹ Stop Scheduler'
                : '▶ Start Scheduler'}
          </button>

          <p style={s.toggleHint}>
            {isRunning
              ? 'Stopping the scheduler will not interrupt a sync currently in progress.'
              : 'Starting the scheduler will register daily sync jobs (08:00 & 13:00).'}
          </p>
        </div>
      </div>

      {/* ── sync run history ── */}
      <div style={s.card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div style={s.cardHeader}>Sync Run History</div>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>Last {runs.length} runs</span>
        </div>
        {runs.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
            No sync runs recorded yet. Click "Manual Sync" to start.
          </div>
        ) : (
          runs.map((r, i) => <SyncRow key={i} run={r} />)
        )}
      </div>
    </div>
  )
}

// ── styles ────────────────────────────────────────────────────────────────────
const s = {
  page: {
    display: 'flex', flexDirection: 'column', gap: 20,
    animation: 'fadeIn .2s ease',
  },
  pageHeader: {
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
  },
  pageTitle: { fontSize: 20, fontWeight: 700, color: 'var(--text)' },
  pageSub:   { color: 'var(--text-muted)', fontSize: 13, marginTop: 2 },
  refreshBtn: {
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: 8, color: 'var(--text-muted)', fontSize: 12,
    padding: '7px 14px', cursor: 'pointer',
  },
  errorBanner: {
    background: '#2e0d0d', border: '1px solid #ef444460',
    borderRadius: 8, padding: '12px 16px', color: '#fca5a5', fontSize: 13,
  },
  kpiRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 12,
  },
  kpi: {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 12, padding: '14px 16px',
  },
  kpiValue: { fontSize: 24, fontWeight: 700, lineHeight: 1.1 },
  kpiLabel: { color: 'var(--text-muted)', fontSize: 11, fontWeight: 600, marginTop: 4, textTransform: 'uppercase', letterSpacing: '.5px' },
  kpiSub:   { color: '#555b7e', fontSize: 10, marginTop: 2 },
  twoCol: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16,
  },
  card: {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 12, padding: '18px 20px',
  },
  cardHeader: {
    fontSize: 12, fontWeight: 700, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '.6px', marginBottom: 14,
  },
  barTrack: {
    height: 6, background: 'var(--surface3)',
    borderRadius: 99, overflow: 'hidden',
  },
  barFill: {
    height: '100%', borderRadius: 99,
    transition: 'width .4s ease',
  },
  schedulerStatus: {
    display: 'flex', alignItems: 'center', gap: 10,
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '10px 14px', marginBottom: 14,
    flexWrap: 'wrap',
  },
  statusDot: {
    width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
    boxShadow: '0 0 6px currentColor',
  },
  jobRow: {
    display: 'flex', flexDirection: 'column', gap: 2,
    background: 'var(--surface2)', borderRadius: 8,
    padding: '8px 12px', marginBottom: 8,
    border: '1px solid var(--border)',
  },
  toggleBtn: {
    width: '100%', padding: '10px', borderRadius: 8,
    fontWeight: 700, fontSize: 13, cursor: 'pointer',
    transition: 'opacity .15s',
  },
  toggleHint: {
    color: '#555b7e', fontSize: 11, marginTop: 8, lineHeight: 1.5,
  },
  syncRow: {
    background: 'var(--surface2)', borderRadius: 8,
    padding: '10px 14px', marginBottom: 8,
    border: '1px solid var(--border)',
  },
  syncDot: {
    width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
    display: 'inline-block',
  },
}
