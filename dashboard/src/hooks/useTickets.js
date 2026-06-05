// src/hooks/useTickets.js  –  fetch FIZ or GCLZ tickets from SQLite
import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchFizTickets, fetchGclzTickets } from '../api'

// Poll every 5 minutes (reads from SQLite cache, not live Jira)
const POLL_INTERVAL_MS = 5 * 60 * 1000

// Per-tab cache so switching tabs shows last known data instead of blank+flash
const _cache = { FIZ: [], GCLZ: [] }

export function useTickets(dashboardGroup = 'FIZ') {
  const [state, setState] = useState({
    FIZ: { tickets: [], loading: true, error: null, lastFetch: null },
    GCLZ: { tickets: [], loading: true, error: null, lastFetch: null },
  })
  const pollRef = useRef(null)

  const load = useCallback(async () => {
    if (!dashboardGroup) return
    
    // Set loading to true for the current group
    setState(prev => ({
      ...prev,
      [dashboardGroup]: { ...prev[dashboardGroup], loading: true, error: null }
    }))

    try {
      const fetchFn = dashboardGroup === 'GCLZ' ? fetchGclzTickets : fetchFizTickets
      const data = await fetchFn()
      const safe = Array.isArray(data) ? data : []
      
      setState(prev => ({
        ...prev,
        [dashboardGroup]: {
          tickets: safe,
          loading: false,
          error: null,
          lastFetch: new Date()
        }
      }))
    } catch (e) {
      const msg = e?.response?.data?.error ?? e.message ?? 'Unknown error'
      const is503 = e?.response?.status === 503
      const errText = is503
        ? '⚠ Cannot reach backend — check if the Flask API is running.'
        : `API error: ${msg}`
      
      setState(prev => ({
        ...prev,
        [dashboardGroup]: {
          ...prev[dashboardGroup],
          loading: false,
          error: errText
        }
      }))
    }
  }, [dashboardGroup])

  // initial load + on dashboard group change
  useEffect(() => {
    load()
    if (!dashboardGroup) return
    pollRef.current = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [load, dashboardGroup])

  const current = state[dashboardGroup] ?? { tickets: [], loading: false, error: null, lastFetch: null }

  return {
    tickets: current.tickets,
    loading: current.loading,
    error: current.error,
    lastFetch: current.lastFetch,
    refresh: load
  }
}
