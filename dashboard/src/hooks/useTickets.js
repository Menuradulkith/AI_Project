// src/hooks/useTickets.js  –  fetch FIZ or GCLZ tickets from SQLite
import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchFizTickets, fetchGclzTickets } from '../api'

// Poll every 5 minutes (reads from SQLite cache, not live Jira)
const POLL_INTERVAL_MS = 5 * 60 * 1000

export function useTickets(dashboardGroup = 'FIZ') {
  const [tickets,   setTickets]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [lastFetch, setLastFetch] = useState(null)
  const pollRef = useRef(null)

  const load = useCallback(async () => {
    // null means the tab doesn't need ticket data (e.g. Performance tab)
    if (!dashboardGroup) { setLoading(false); return }
    setLoading(true)
    setError(null)
    try {
      const fetchFn = dashboardGroup === 'GCLZ' ? fetchGclzTickets : fetchFizTickets
      const data = await fetchFn()
      setTickets(Array.isArray(data) ? data : [])
      setLastFetch(new Date())
    } catch (e) {
      const msg = e?.response?.data?.error ?? e.message ?? 'Unknown error'
      const is503 = e?.response?.status === 503
      setError(is503
        ? '⚠ Cannot reach backend — check if the Flask API is running.'
        : `API error: ${msg}`
      )
    } finally {
      setLoading(false)
    }
  }, [dashboardGroup])

  // initial load + on dashboard group change
  useEffect(() => {
    load()
    if (!dashboardGroup) return
    // Set up gentle polling (reads from SQLite, not Jira)
    pollRef.current = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [load, dashboardGroup])

  return { tickets, loading, error, lastFetch, refresh: load }
}
