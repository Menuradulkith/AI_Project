// src/api.js  –  thin wrapper around the Flask REST API
import axios from 'axios'

// In production (Vercel), VITE_API_URL is set to the Railway backend URL.
// In development, requests go to /api which is proxied by Vite to localhost:5001.
const BASE_URL = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

const client = axios.create({ baseURL: BASE_URL, timeout: 15000 })

// Dashboard data (from SQLite only — no live Jira calls)
export const fetchFizTickets  = () =>
  client.get('/fiz').then(r => r.data.data)

export const fetchGclzTickets = () =>
  client.get('/gclz').then(r => r.data.data)

export const fetchDashboardStats = () =>
  client.get('/dashboard/stats').then(r => r.data.data)

// Single ticket detail (from Jira)
export const fetchTicket = (id) =>
  client.get(`/ticket/${id}`).then(r => r.data.data)

// Sync (triggers scheduler to fetch from Jira + classify)
// Uses a longer timeout — classifying many tickets can take 60s+
export const triggerManualSync = () =>
  client.post('/sync/trigger-blocking', null, { timeout: 120000 }).then(r => r.data.data)

export const getSyncStatus = () =>
  client.get('/sync/status').then(r => r.data.data)

export const getManualReviewTickets = () =>
  client.get('/sync/manual-review').then(r => r.data.data)

export const clearManualReview = (ticketId) =>
  client.post(`/sync/manual-review/${ticketId}/clear`).then(r => r.data.data)

// Scheduler control
export const startScheduler  = () =>
  client.post('/scheduler/start').then(r => r.data.data)
export const stopScheduler   = () =>
  client.post('/scheduler/stop').then(r => r.data.data)

