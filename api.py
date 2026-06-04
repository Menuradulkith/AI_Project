"""
api.py  –  Flask REST API for the Jira FIZ/GCLZ Ticket Dashboard
────────────────────────────────────────────────────────────────
Endpoints
  GET  /api/fiz                            list FIZ tickets (from SQLite)
  GET  /api/gclz                           list GCLZ tickets (from SQLite)
  GET  /api/dashboard/stats                dashboard statistics
  GET  /api/ticket/<ticket_id>             single ticket full detail
  GET  /api/health                         liveness check
  POST /api/sync/trigger                   trigger manual sync (background)
  POST /api/sync/trigger-blocking          trigger manual sync (wait for result)
  GET  /api/sync/status                    sync state and recent runs
  GET  /api/sync/manual-review             tickets flagged for manual review

Run:
    .venv/Scripts/python.exe api.py
    → http://localhost:5001
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading

from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from jira_fetcher import (
    get_ticket_details,
    PROJECT_KEY,
)
from categorizer import classify_ticket
from cache import (
    init_db,
    get_manual_review_tickets, clear_manual_review,
    get_sync_state, get_sync_log,
    get_fiz_tickets, get_gclz_tickets, get_dashboard_stats,
    upsert_tickets_bulk, get_ticket_classification,
)
from agents.chat import chat as agent_chat
from scheduler import run_sync, start_scheduler, stop_scheduler, get_scheduler_status

WEBHOOK_SECRET = os.getenv("JIRA_WEBHOOK_SECRET", "")

# 4. Validate required env vars at startup — fail fast with a clear message
_REQUIRED_ENV = {
    "JIRA_BASE_URL":   os.getenv("JIRA_BASE_URL", ""),
    "JIRA_EMAIL":      os.getenv("JIRA_EMAIL", ""),
    "JIRA_API_TOKEN":  os.getenv("JIRA_API_TOKEN", ""),
    "OPENAI_API_KEY":  os.getenv("OPENAI_API_KEY", ""),
}
_missing_env = [k for k, v in _REQUIRED_ENV.items() if not v.strip()]
if _missing_env:
    raise EnvironmentError(
        f"\n\n❌ Missing required environment variables: {', '.join(_missing_env)}\n"
        "   Copy .env.example → .env and fill in all values before starting.\n"
    )

app = Flask(__name__)
_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
CORS(app, origins=[o.strip() for o in _ALLOWED_ORIGINS])

# initialise SQLite cache on startup
init_db()

# Auto-start scheduler when running under gunicorn (not via __main__)
# Gunicorn workers each import the module, so guard with a flag file / env var
if os.getenv("WERKZEUG_RUN_MAIN") != "true" and os.getenv("SCHEDULER_STARTED") != "1":
    try:
        start_scheduler()
        os.environ["SCHEDULER_STARTED"] = "1"
        logger.info("Scheduler auto-started (gunicorn worker)")
    except Exception as e:
        logger.warning("Could not auto-start scheduler: %s", e)


# ── helpers ───────────────────────────────────────────────────

def _ok(data):
    return jsonify({"ok": True,  "data": data})

def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


# ── routes ────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return _ok({"project": PROJECT_KEY, "status": "running"})


# ══════════════════════════════════════════════════════════════
# Dashboard endpoints (FIZ / GCLZ tabs)
# ══════════════════════════════════════════════════════════════

@app.get("/api/fiz")
def fiz_tickets():
    """
    Get all FIZ tickets from SQLite (not yet moved to GCLZ).
    Frontend reads from here — no live Jira call.
    """
    try:
        data = get_fiz_tickets()
        return _ok(data)
    except Exception as e:
        logger.error("Error fetching FIZ tickets: %s", e)
        return _err(f"Server error: {e}", 500)


@app.get("/api/gclz")
def gclz_tickets():
    """
    Get all GCLZ tickets from SQLite (tickets moved to GCLZ).
    Read-only — no automation on these tickets.
    """
    try:
        data = get_gclz_tickets()
        return _ok(data)
    except Exception as e:
        logger.error("Error fetching GCLZ tickets: %s", e)
        return _err(f"Server error: {e}", 500)


@app.get("/api/dashboard/stats")
def dashboard_stats():
    """Return dashboard statistics."""
    try:
        stats = get_dashboard_stats()
        return _ok(stats)
    except Exception as e:
        logger.error("Error fetching dashboard stats: %s", e)
        return _err(f"Server error: {e}", 500)


@app.get("/api/ticket/<ticket_id>")
def single_ticket(ticket_id: str):
    """Get single ticket details (from Jira for full info)."""
    import re as _re
    if not _re.fullmatch(r"[A-Z]{2,10}-\d{1,10}", ticket_id):
        return _err("Invalid ticket ID format", 400)
    try:
        t = get_ticket_details(ticket_id)
    except ConnectionError as e:
        return _err(str(e), 503)
    if t is None:
        return _err(f"Ticket '{ticket_id}' not found or API error", 404)
    t["_classification"] = get_ticket_classification(ticket_id)
    return _ok(t)


# ── Chat ──────────────────────────────────────────────────────

@app.post("/api/chat")
def chat_endpoint():
    """Chat with the AI assistant about FIZ tickets.
    Body: { "message": "...", "history": [...] }
    Returns: { "ok": true, "reply": "..." }
    """
    try:
        body    = request.get_json(force=True) or {}
        message = (body.get("message") or "").strip()
        history = body.get("history") or []

        if not message:
            return _err("message is required", 400)

        reply = agent_chat(message, history)
        return jsonify({"ok": True, "reply": reply})

    except Exception as e:
        logger.exception("Chat error")
        return _err(f"Chat error: {e}", 500)


# ── Jira Webhook ─────────────────────────────────────────────

def _verify_webhook_signature(payload: bytes, signature_header: str) -> bool:
    """Verify the HMAC-SHA256 signature Jira sends with each webhook."""
    if not WEBHOOK_SECRET:
        return True   # secret not configured → skip verification (dev mode)
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def _classify_and_write_back(ticket_id: str) -> None:
    """Background task: classify ticket and post result back to Jira."""
    try:
        ticket = get_ticket_details(ticket_id)
        if ticket is None:
            logger.warning("Webhook: ticket %s not found", ticket_id)
            return

        # Only process customer-raised defects
        if ticket.get("issue_type") not in ("Support Issue", "Defect"):
            logger.info("Webhook: skipping %s (type=%s)", ticket_id, ticket.get("issue_type"))
            return

        result = classify_ticket(ticket)
        logger.info("Webhook: classified %s → %s (%s)", ticket_id, result["board"], result["confidence"])
        # Persist classification to SQLite — no Jira write
        upsert_tickets_bulk([ticket])
        from cache import get_ticket_classification as _get_cls
        # save_classification used by scheduler; here we use upsert_ticket directly
        from cache import upsert_ticket as _upsert
        _upsert(ticket, classification=result)
    except Exception as e:
        logger.error("Webhook: error processing %s — %s", ticket_id, e)


@app.post("/api/webhook/jira")
def jira_webhook():
    """
    Receives Jira webhook events (issue_created / issue_updated).

    Set up in Jira:
      Project Settings → Automation → Webhooks
      OR
      Jira Settings → System → WebHooks
      URL: https://<your-server>/api/webhook/jira
      Events: Issue Created, Issue Updated
    """
    raw = request.get_data()

    # Signature verification
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_webhook_signature(raw, sig):
        logger.warning("Webhook: invalid signature — rejected")
        return _err("Invalid signature", 401)

    event = request.get_json(force=True) or {}
    webhook_event = event.get("webhookEvent", "")

    # Only handle issue created or updated events
    if webhook_event not in ("jira:issue_created", "jira:issue_updated"):
        return _ok({"skipped": webhook_event})

    issue      = event.get("issue", {})
    ticket_id  = issue.get("key", "")
    project    = issue.get("fields", {}).get("project", {}).get("key", "")

    if not ticket_id:
        return _err("No issue key in payload", 400)

    # Only process our project
    if project and project != PROJECT_KEY:
        return _ok({"skipped": f"project {project} not monitored"})

    # Run classification in background so webhook returns immediately (< 3s)
    thread = threading.Thread(target=_classify_and_write_back, args=(ticket_id,), daemon=True)
    thread.start()

    logger.info("Webhook: queued classification for %s (event=%s)", ticket_id, webhook_event)
    return _ok({"queued": ticket_id})


# ── Sync / Scheduler endpoints ────────────────────────────────

@app.post("/api/sync/trigger")
def trigger_sync():
    """Manually trigger a sync cycle. Runs in background, returns immediately."""
    def _bg_sync():
        try:
            run_sync(trigger="manual")
        except Exception as e:
            logger.error("Manual sync failed: %s", e)

    thread = threading.Thread(target=_bg_sync, daemon=True)
    thread.start()
    return _ok({"message": "Sync triggered", "status": "running"})


@app.post("/api/sync/trigger-blocking")
def trigger_sync_blocking():
    """Manually trigger a sync cycle. Blocks until complete, returns results."""
    try:
        result = run_sync(trigger="manual")
        return _ok(result)
    except Exception as e:
        return _err(f"Sync failed: {e}", 500)


@app.get("/api/sync/status")
def sync_status():
    """Return current sync state, scheduler info, and recent run log."""
    return _ok({
        "sync_state": get_sync_state(),
        "scheduler":  get_scheduler_status(),
        "recent_runs": get_sync_log(limit=10),
    })


@app.get("/api/sync/manual-review")
def manual_review_list():
    """Return tickets flagged for manual review (medium/low confidence Localisation)."""
    return _ok(get_manual_review_tickets())


@app.post("/api/sync/manual-review/<ticket_id>/clear")
def manual_review_clear(ticket_id: str):
    """Mark a ticket as manually reviewed (remove from review queue)."""
    clear_manual_review(ticket_id)
    return _ok({"cleared": ticket_id})


@app.post("/api/scheduler/start")
def scheduler_start():
    """Start the background scheduler (8am & 1pm daily)."""
    start_scheduler()
    return _ok(get_scheduler_status())


@app.post("/api/scheduler/stop")
def scheduler_stop():
    """Stop the background scheduler."""
    stop_scheduler()
    return _ok({"stopped": True})


@app.get("/api/scheduler/status")
def scheduler_status_ep():
    return _ok(get_scheduler_status())


# ── entry-point ───────────────────────────────────────────────

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "0").strip() in ("1", "true", "yes")

    # In debug mode Werkzeug spawns a reloader child process.
    # We must only start APScheduler in the MAIN process (not the reloader),
    # otherwise the scheduler runs twice and every sync fires duplicate LLM calls.
    # WERKZEUG_RUN_MAIN is set to "true" only in the child (main) process.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if not debug_mode or is_reloader_child:
        try:
            start_scheduler()
            logger.info("Scheduler auto-started with API")
        except Exception as e:
            logger.warning("Could not start scheduler: %s", e)

    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
