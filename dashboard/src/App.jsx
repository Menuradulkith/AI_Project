/* src/App.jsx  – IFS Jira FIZ/GCLZ Localization Dashboard */
import { useState, useMemo, useEffect, useCallback } from 'react'
import './App.css'
import { useTickets } from './hooks/useTickets'
import { triggerManualSync, startScheduler, stopScheduler } from './api'
import TicketCard      from './components/TicketCard'
import TicketModal     from './components/TicketModal'
import ChatPanel       from './components/ChatPanel'
import PerformancePage from './components/PerformancePage'

const TABS = [
  { id: 'FIZ',         label: '📋 FIZ',         description: 'Active tickets pending review' },
  { id: 'GCLZ',       label: '🌍 GCLZ',       description: 'Moved to Localization' },
  { id: 'PERFORMANCE', label: '📊 Performance', description: 'Model stats, sync history & scheduler' },
]

export default function App() {
  const [activeTab,       setActiveTab]       = useState('FIZ')
  const [selectedTicket,  setSelectedTicket]  = useState(null)
  const [search,          setSearch]          = useState('')
  const [sortBy,          setSortBy]          = useState('updated')
  const [chatOpen,        setChatOpen]        = useState(false)
  const [syncing,         setSyncing]         = useState(false)
  const [syncError,       setSyncError]       = useState(null)
  const [syncMessage,     setSyncMessage]     = useState(null)
  const [schedulerOn,     setSchedulerOn]     = useState(true)
  const [darkMode,        setDarkMode]        = useState(() => {
    const saved = localStorage.getItem('theme')
    return saved ? saved === 'dark' : true
  })

  // Apply theme to <html> element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
    localStorage.setItem('theme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  const toggleScheduler = useCallback(async () => {
    try {
      if (schedulerOn) {
        await stopScheduler()
        setSchedulerOn(false)
      } else {
        await startScheduler()
        setSchedulerOn(true)
      }
    } catch (e) {
      setSyncError(`Scheduler toggle failed: ${e.message}`)
    }
  }, [schedulerOn])

  const { tickets, loading, error, lastFetch, refresh } = useTickets(
    activeTab === 'PERFORMANCE' ? null : activeTab
  )

  // Filter and sort tickets
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    let list = tickets
    if (q) {
      list = list.filter(t =>
        t.summary?.toLowerCase().includes(q) ||
        (t.cs_ref ?? '').toLowerCase().includes(q) ||
        t.ticket_id?.toLowerCase().includes(q) ||
        (t.description ?? '').toLowerCase().includes(q)
      )
    }
    return [...list].sort((a, b) => {
      if (sortBy === 'updated') return (b.updated ?? '').localeCompare(a.updated ?? '')
      if (sortBy === 'created') return (b.created ?? '').localeCompare(a.created ?? '')
      if (sortBy === 'priority') {
        const order = { highest:0, high:1, medium:2, low:3, lowest:4 }
        return (order[a.priority?.toLowerCase()] ?? 9) - (order[b.priority?.toLowerCase()] ?? 9)
      }
      return 0
    })
  }, [tickets, search, sortBy])

  // Separate tickets by classification status
  const { localisation, needsReview, unclassified } = useMemo(() => {
    const loc = [], review = [], unclass = []
    for (const t of filtered) {
      const cls = t._classification
      if (!cls) {
        unclass.push(t)
      } else if (cls.needs_review) {
        review.push(t)
      } else if (cls.board?.toLowerCase() === 'localisation') {
        loc.push(t)
      } else {
        unclass.push(t)  // classified as something else
      }
    }
    return { localisation: loc, needsReview: review, unclassified: unclass }
  }, [filtered])

  const onManualSync = async () => {
    setSyncing(true)
    setSyncError(null)
    setSyncMessage(null)
    try {
      const result = await triggerManualSync()
      await refresh()
      setSyncMessage(
        `Sync complete — ${result.classified || 0} classified, ` +
        `${result.moved || 0} moved, ${result.flagged || 0} flagged.`
      )
    } catch (e) {
      const msg = e?.response?.data?.error ?? e.message ?? 'Unknown error'
      setSyncError(`Sync failed: ${msg}`)
    } finally {
      setSyncing(false)
    }
  }

  const isGclz        = activeTab === 'GCLZ'
  const isPerformance = activeTab === 'PERFORMANCE'

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img src="/ifs-logo.png" alt="IFS" className="brand-logo" />
          <span className="brand-text">Localization Triage</span>
        </div>
        <nav className="nav">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`nav-btn${activeTab === tab.id ? ' active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
              title={tab.description}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="refresh-info">
            {lastFetch && (
              <>
                <span style={{ color: '#555b7e', fontSize: 11 }}>Last refresh</span>
                <span style={{ color: '#7b82a6', fontSize: 11 }}>
                  {lastFetch.toLocaleTimeString()}
                </span>
              </>
            )}
          </div>
          <button className="refresh-btn" onClick={refresh} disabled={loading}>
            {loading ? '⏳ Loading…' : '↺ Refresh'}
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="header">
          <div>
            <h1 className="page-title">
              {isPerformance ? '📊 Model Performance' : isGclz ? '🌍 GCLZ — Localization Tickets' : '📋 FIZ — Active Tickets'}
            </h1>
            <p className="page-sub">
              {isPerformance
                ? 'Classification stats, sync history & scheduler control'
                : <>Showing <strong>{isGclz ? filtered.length : localisation.length + needsReview.length}</strong> ticket{(isGclz ? filtered.length : localisation.length + needsReview.length) !== 1 ? 's' : ''}{isGclz && ' (read-only)'}</>
              }
            </p>
          </div>
          <div className="header-stats">
            {!isGclz && !isPerformance && (
              <>
                <span className="stat-badge loc">🌍 {localisation.length}</span>
                <span className="stat-badge review">⚠️ {needsReview.length}</span>
              </>
            )}
            <div className="toggle-wrap">
              <span>{schedulerOn ? 'Scheduler' : 'Scheduler'}</span>
              <button
                className={`toggle${schedulerOn ? ' on' : ''}`}
                onClick={toggleScheduler}
                title={schedulerOn ? 'Stop scheduler' : 'Start scheduler'}
              />
            </div>
            <div className="toggle-wrap">
              <span>{darkMode ? 'Dark' : 'Light'}</span>
              <button
                className={`toggle${darkMode ? ' on' : ''}`}
                onClick={() => setDarkMode(d => !d)}
                title={darkMode ? 'Switch to light theme' : 'Switch to dark theme'}
              />
            </div>
          </div>
        </header>

        {!isPerformance && (
          <div className="toolbar">
            <input
              className="search"
              placeholder="🔍  Search by ID, CS ref, summary…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <select className="sort-select" value={sortBy} onChange={e => setSortBy(e.target.value)}>
              <option value="updated">Sort: Last Updated</option>
              <option value="created">Sort: Created</option>
              <option value="priority">Sort: Priority</option>
            </select>
            {!isGclz && (
              <button
                className="classify-all-btn"
                onClick={onManualSync}
                disabled={syncing}
                title="Fetch new tickets from Jira, classify, and move HIGH confidence to GCLZ"
              >
                {syncing ? '⏳ Syncing…' : '🔁 Manual Sync'}
              </button>
            )}
          </div>
        )}

        {syncError && (
          <div className="error-banner">⚠ {syncError}</div>
        )}
        {syncMessage && (
          <div className="error-banner" style={{ background: '#e7f6ed', color: '#0f5132', borderColor: '#badbcc' }}>
            ✅ {syncMessage}
          </div>
        )}
        {error && (
          <div className="error-banner">
            ⚠ {error}
            <br />
            <small>Make sure the Flask backend (Railway) is reachable and VITE_API_URL is set in Vercel.</small>
          </div>
        )}

        {!isPerformance && loading && !tickets.length && (
          <div className="empty-state">⏳ Loading tickets…</div>
        )}

        {!isPerformance && !loading && !error && filtered.length === 0 && (
          <div className="empty-state">
            {search 
              ? `No tickets match "${search}"` 
              : isGclz 
                ? 'No tickets moved to GCLZ yet.'
                : 'No FIZ tickets in the database. Click "Manual Sync" to fetch from Jira.'
            }
          </div>
        )}

        {/* Performance tab */}
        {isPerformance && <PerformancePage />}

        {/* GCLZ Tab: Simple list of moved tickets */}
        {isGclz && filtered.length > 0 && (
          <div className="board-section">
            <div className="board-section-header gclz-header">
              🌍 Moved to Localization <span className="board-count">{filtered.length}</span>
            </div>
            <div className="grid">
              {filtered.map(t => (
                <TicketCard 
                  key={t.ticket_id} 
                  ticket={t} 
                  onClick={setSelectedTicket}
                  classification={t._classification}
                  readOnly
                />
              ))}
            </div>
          </div>
        )}

        {/* FIZ Tab: Grouped by classification status */}
        {!isGclz && (
          <>
            {/* Needs Review — highlighted warning */}
            {needsReview.length > 0 && (
              <div className="board-section">
                <div className="board-section-header review-header">
                  ⚠️ Needs Manual Review <span className="board-count">{needsReview.length}</span>
                </div>
                <p className="section-hint">
                  These tickets were classified as Localization with MEDIUM/LOW confidence.
                  Please review manually before taking action.
                </p>
                <div className="grid">
                  {needsReview.map(t => (
                    <TicketCard 
                      key={t.ticket_id} 
                      ticket={t} 
                      onClick={setSelectedTicket}
                      classification={t._classification}
                      highlight="review"
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Classified as Localization (HIGH confidence) */}
            {localisation.length > 0 && (
              <div className="board-section">
                <div className="board-section-header localisation-header">
                  🌍 Localisation <span className="board-count">{localisation.length}</span>
                </div>
                <div className="grid">
                  {localisation.map(t => (
                    <TicketCard 
                      key={t.ticket_id} 
                      ticket={t} 
                      onClick={setSelectedTicket}
                      classification={t._classification}
                    />
                  ))}
                </div>
              </div>
            )}


          </>
        )}
      </main>

      {selectedTicket && (
        <TicketModal
          ticketId={selectedTicket}
          onClose={() => setSelectedTicket(null)}
        />
      )}

      {/* Chat FAB */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          title="Ask AI assistant"
          style={{
            position: 'fixed', bottom: 24, right: 24,
            width: 48, height: 48, borderRadius: '50%',
            background: '#2563eb', border: 'none', color: '#fff',
            fontSize: 22, cursor: 'pointer',
            boxShadow: '0 4px 16px #2563eb66',
            zIndex: 999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          🤖
        </button>
      )}
      {chatOpen && <ChatPanel onClose={() => setChatOpen(false)} />}
    </div>
  )
}
