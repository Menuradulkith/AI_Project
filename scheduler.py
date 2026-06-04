"""
scheduler.py
─────────────
Automated Jira FIZ ticket classification scheduler.

Flow:
  1. Load last_sync_time from SQLite
  2. Incremental fetch: only FIZ tickets created/updated since last sync
  3. For each FIZ ticket:
     a. Skip if automation_locked (already moved to GCLZ)
     b. Generate content hash — skip if unchanged
     c. AI classify (localization or not)
     d. HIGH confidence Localisation → add Jira comment + move to GCLZ + lock
     e. MEDIUM/LOW confidence → save + highlight for manual review (no Jira actions)
  4. Update last_sync_time
  5. Log the run

Schedule: 8:00 AM and 1:00 PM daily (configurable via .env)
Manual trigger: via API endpoint or CLI

NOTE: Only processes FIZ tickets. In Progress / Done are completely ignored.
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────

# Confidence threshold — only act (comment + move) when confidence ≥ this %
HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "90"))

# Schedule times (24h format)
SCHEDULE_TIMES = os.getenv("SCHEDULE_TIMES", "08:00,10:45,13:00").split(",")

# Only fetch active untriaged tickets (To Do status category)
SCHEDULED_STATUSES = ["To Do", "New", "Open"]


# ── Helpers ───────────────────────────────────────────────────

def _confidence_to_pct(confidence: str) -> float:
    """Map confidence labels to numeric percentages."""
    mapping = {"high": 90.0, "medium": 60.0, "low": 30.0}
    return mapping.get(confidence.lower(), 0.0)


def _is_localization(result: dict) -> bool:
    """Check if the classification result indicates Localisation."""
    return result.get("board", "").lower() in ("localisation", "localization")


# ══════════════════════════════════════════════════════════════
# Core sync logic
# ══════════════════════════════════════════════════════════════

def run_sync(trigger: str = "scheduled") -> dict:
    """
    Execute one full sync cycle.

    Args:
        trigger: "scheduled" | "manual" — logged for audit

    Returns:
        Summary dict with counts of fetched, classified, moved, flagged tickets.
    """
    from jira_fetcher import (
        fetch_tickets_since,
        # write_classification_to_jira,
        # move_issue_to_project,
    )                                                                                                                                                                                                                                       
    from categorizer import classify_ticket
    from cache import (
        get_last_sync_time,
        update_last_sync_time,
        log_sync_run,
        init_db,
        upsert_tickets_bulk,
        is_ticket_locked,
        get_ticket_content_hash,
        save_classification,
        mark_ticket_moved,
        _content_hash,
        get_all_fiz_ticket_ids,
        get_unclassified_fiz_ticket_ids,
        mark_tickets_inactive,
    )

    init_db()
    start = time.time()

    stats = {
        "trigger":     trigger,
        "fetched":     0,
        "classified":  0,
        "moved":       0,
        "flagged":     0,
        "errors":      [],
        "started_at":  datetime.now(timezone.utc).isoformat(),
    }

    last_sync = get_last_sync_time()
    sync_start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    logger.info("═" * 60)
    logger.info("SYNC START  trigger=%s  since=%s", trigger, last_sync)
    logger.info("═" * 60)

    # ──────────────────────────────────────────────────────────
    # Incremental fetch of FIZ tickets only (To Do status)
    # ──────────────────────────────────────────────────────────
    is_full_fetch = False
    try:
        fiz_tickets = fetch_tickets_since(last_sync, status=SCHEDULED_STATUSES)

        # ── Bootstrap guard ───────────────────────────────────
        # Trigger a full re-fetch in two cases:
        #   1. DB is completely empty (fresh install / first wipe)
        #   2. Tickets exist in DB but none are classified yet (DB wiped mid-run)
        unclassified = get_unclassified_fiz_ticket_ids()
        needs_full_fetch = not fiz_tickets and (
            not get_all_fiz_ticket_ids() or unclassified
        )
        if needs_full_fetch:
            reason = "DB is empty" if not get_all_fiz_ticket_ids() else f"{len(unclassified)} ticket(s) unclassified"
            logger.info(
                "Incremental fetch returned 0 and %s — "
                "falling back to full lookback fetch", reason
            )
            fiz_tickets = fetch_tickets_since(
                "2025-01-01T00:00:00+00:00",
                status=SCHEDULED_STATUSES,
            )
            is_full_fetch = True

        stats["fetched"] += len(fiz_tickets)
        logger.info("Fetched %d FIZ tickets since %s", len(fiz_tickets), last_sync)

        # Save all fetched tickets to SQLite (upsert, respects automation_locked)
        if fiz_tickets:
            upsert_tickets_bulk(fiz_tickets)

    except Exception as e:
        logger.error("Failed to fetch FIZ tickets: %s", e)
        stats["errors"].append(f"FIZ fetch: {e}")
        fiz_tickets = []

        # ── Reconcile: deactivate tickets no longer in Jira active set ────────
        # ONLY runs on full fetches (bootstrap/lookback) — NOT on incremental
        # fetches, because incremental only returns recently-changed tickets,
        # not the full set. Comparing a partial set would incorrectly mark
        # unchanged tickets as inactive.
    try:
        if is_full_fetch and fiz_tickets:
            active_in_db = get_all_fiz_ticket_ids()
            returned_ids = {t["ticket_id"] for t in fiz_tickets}
            stale_ids    = list(active_in_db - returned_ids)
            if stale_ids:
                n = mark_tickets_inactive(stale_ids)
                logger.info("Reconciled: marked %d stale ticket(s) inactive: %s", n, stale_ids)
                stats["deactivated"] = n
    except Exception as e:
        logger.warning("Reconcile step failed (non-fatal): %s", e)

    # ──────────────────────────────────────────────────────────
    # Process each ticket
    # ──────────────────────────────────────────────────────────
    for ticket in fiz_tickets:
        tid = ticket.get("ticket_id", "?")
        try:
            _process_fiz_ticket(
                ticket, stats, classify_ticket,
                None, None,
                is_ticket_locked, get_ticket_content_hash,
                save_classification, mark_ticket_moved, _content_hash,
            )
        except Exception as e:
            logger.error("Error processing FIZ %s: %s", tid, e)
            stats["errors"].append(f"{tid}: {e}")

    # ──────────────────────────────────────────────────────────
    # Update sync state + log the run
    # ──────────────────────────────────────────────────────────
    duration = time.time() - start
    stats["duration_sec"] = round(duration, 2)

    error_text = "; ".join(stats["errors"]) if stats["errors"] else None
    update_last_sync_time(sync_start_time, "success" if not stats["errors"] else "partial")

    log_sync_run(
        trigger_type=trigger,
        fetched=stats["fetched"],
        classified=stats["classified"],
        moved=stats["moved"],
        flagged=stats["flagged"],
        errors=error_text,
        duration=duration,
    )

    logger.info("═" * 60)
    logger.info(
        "SYNC DONE  fetched=%d classified=%d moved=%d flagged=%d  (%.1fs)",
        stats["fetched"], stats["classified"], stats["moved"], stats["flagged"], duration,
    )
    logger.info("═" * 60)

    return stats


# ──────────────────────────────────────────────────────────────
# Per-ticket processing
# ──────────────────────────────────────────────────────────────

def _process_fiz_ticket(
    ticket: dict, stats: dict,
    classify_fn, write_comment_fn, move_fn,
    is_locked_fn, get_hash_fn, save_class_fn, mark_moved_fn, hash_fn,
) -> None:
    """
    Process a single FIZ ticket:
      1. Skip if automation_locked (already moved)
      2. Content hash check → skip if unchanged
      3. Classify (localization or not)
      4. HIGH confidence Localisation → Jira comment + move to GCLZ + lock
      5. MEDIUM/LOW → save + highlight for manual review (no Jira actions)
    """
    tid = ticket["ticket_id"]
    
    # ── Skip if already moved/locked ──────────────────────────
    if is_locked_fn(tid):
        logger.debug("Skipping %s — automation_locked", tid)
        return

    # ── Content hash check ────────────────────────────────────
    current_hash = hash_fn(ticket)
    stored_hash = get_hash_fn(tid)
    # Only skip if content is unchanged AND ticket was already classified
    from cache import get_ticket_classification as _get_cls
    if stored_hash == current_hash and _get_cls(tid) is not None:
        logger.debug("Skipping %s — content unchanged + already classified (hash=%s)", tid, current_hash)
        return

    # ── Classify ──────────────────────────────────────────────
    logger.info("Classifying FIZ %s …", tid)
    # force=True only when content actually changed (hash mismatch) — not just because
    # the ticket was seen before. This prevents redundant LLM calls on unchanged tickets
    # that slipped past the hash check (e.g. first-time tickets with no stored hash).
    content_changed = stored_hash is not None and stored_hash != current_hash
    result = classify_fn(ticket, force=content_changed)
    stats["classified"] += 1

    board      = result.get("board", "")
    confidence = result.get("confidence", "low")
    reason     = result.get("reason", "")
    conf_pct   = _confidence_to_pct(confidence)
    is_loc     = _is_localization(result)

    # ── HIGH confidence Localisation → Comment + Move + Lock ──
    if is_loc and conf_pct >= HIGH_CONFIDENCE_THRESHOLD:
        logger.info("✅ %s → Localisation (HIGH %.0f%%) — write operations disabled", tid, conf_pct)

        # 1. Save classification
        save_class_fn(tid, result, needs_review=False)

        # 2. Add Jira comment
        # comment_ok = write_comment_fn(tid, board, confidence, reason)
        # if not comment_ok:
        #     logger.warning("Failed to add comment to %s, but continuing with move", tid)

        # 3. Move ticket from FIZ to GCLZ
        # move_result = move_fn(tid)
        # if move_result.get("success"):
        #     new_key = move_result.get("new_ticket_id")
        #     mark_moved_fn(tid, new_key)
        #     stats["moved"] += 1
        #     logger.info("🎉 Moved %s → GCLZ (new key: %s)", tid, new_key or "same")
        # else:
        #     logger.error("❌ Failed to move %s: %s", tid, move_result.get("error"))
        #     stats["errors"].append(f"Move failed for {tid}: {move_result.get('error')}")
        return

    # ── MEDIUM / LOW confidence → Save + Flag for review ─────
    if is_loc and conf_pct < HIGH_CONFIDENCE_THRESHOLD:
        review_reason = (
            f"Classified as Localisation but confidence is only {confidence} "
            f"({conf_pct:.0f}%). Reason: {reason}"
        )
        logger.warning("⚠️  %s → Localisation (%s) — flagged for manual review", tid, confidence)
        save_class_fn(tid, result, needs_review=True, review_reason=review_reason)
        stats["flagged"] += 1
        return

    # ── Not Localisation low/medium → flag for manual review ──
    # The AI is uncertain — could be a missed localisation ticket
    if not is_loc and conf_pct < HIGH_CONFIDENCE_THRESHOLD:
        review_reason = (
            f"Classified as Not Localisation but confidence is only {confidence} "
            f"({conf_pct:.0f}%). Manual check recommended. Reason: {reason}"
        )
        logger.warning("⚠️  %s → Not Localisation (%s) — flagged for manual review", tid, confidence)
        save_class_fn(tid, result, needs_review=True, review_reason=review_reason)
        stats["flagged"] += 1
        return

    # ── Not Localisation high confidence → just save ──────────
    logger.info("📋 %s → %s (%s)", tid, board, confidence)
    save_class_fn(tid, result, needs_review=False)


# ══════════════════════════════════════════════════════════════
# APScheduler integration
# ══════════════════════════════════════════════════════════════

_scheduler = None
_scheduler_lock = threading.Lock()


def _run_full_reconcile():
    """
    Fetch ALL active FIZ tickets from Jira and mark any DB tickets
    not returned as inactive. This catches tickets that were moved,
    closed, or deleted in Jira between syncs.
    """
    from jira_fetcher import fetch_tickets_since
    from cache import (
        init_db, get_all_fiz_ticket_ids, mark_tickets_inactive,
    )

    init_db()
    logger.info("═" * 60)
    logger.info("RECONCILE START — full ticket check")
    logger.info("═" * 60)

    try:
        all_jira = fetch_tickets_since(
            "2025-01-01T00:00:00+00:00",
            status=SCHEDULED_STATUSES,
        )
        returned_ids = {t["ticket_id"] for t in all_jira}
        active_in_db = get_all_fiz_ticket_ids()
        stale_ids = list(active_in_db - returned_ids)

        if stale_ids:
            n = mark_tickets_inactive(stale_ids)
            logger.info("Reconciled: marked %d stale ticket(s) inactive: %s", n, stale_ids)
        else:
            logger.info("Reconcile: all %d DB tickets are still active in Jira", len(active_in_db))
    except Exception as e:
        logger.error("Reconcile failed: %s", e)

    logger.info("═" * 60)
    logger.info("RECONCILE DONE")
    logger.info("═" * 60)


def start_scheduler():
    """
    Start the APScheduler background scheduler with cron jobs
    at 8:00 AM and 1:00 PM daily.
    """
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            logger.info("Scheduler already running")
            return

        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from zoneinfo import ZoneInfo

        TZ = ZoneInfo("Asia/Colombo")
        _scheduler = BackgroundScheduler(daemon=True, timezone=TZ)

        for time_str in SCHEDULE_TIMES:
            time_str = time_str.strip()
            hour, minute = time_str.split(":")
            trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=TZ)
            _scheduler.add_job(
                run_sync,
                trigger=trigger,
                args=["scheduled"],
                id=f"sync_{time_str}",
                name=f"Sync at {time_str} (Asia/Colombo)",
                replace_existing=True,
                misfire_grace_time=60,
            )
            logger.info("Scheduled sync job at %s Asia/Colombo daily", time_str)

        # Full reconcile once daily at 00:30 Asia/Colombo
        _scheduler.add_job(
            _run_full_reconcile,
            trigger=CronTrigger(hour=0, minute=30, timezone=TZ),
            id="reconcile_daily",
            name="Daily reconcile (Asia/Colombo)",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Scheduled daily reconcile at 00:30 Asia/Colombo")

        _scheduler.start()
        logger.info("APScheduler started with %d jobs", len(_scheduler.get_jobs()))


def stop_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return scheduler state + next run times."""
    if _scheduler is None:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })
    return {"running": True, "jobs": jobs}


# ══════════════════════════════════════════════════════════════
# CLI entry-point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Jira FIZ ticket sync scheduler")
    parser.add_argument("--run-now", action="store_true",
                        help="Run one sync cycle immediately (manual trigger)")
    parser.add_argument("--daemon", action="store_true",
                        help="Start the scheduler daemon (runs at 8am & 1pm)")
    args = parser.parse_args()

    if args.run_now:
        print("\n🔄 Running manual sync…\n")
        result = run_sync(trigger="manual")
        print(f"\n✅ Sync complete: {json.dumps(result, indent=2, default=str)}\n")

    elif args.daemon:
        print("\n🕐 Starting scheduler daemon (8:00 AM & 1:00 PM daily)…")
        print("   Press Ctrl+C to stop.\n")
        start_scheduler()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop_scheduler()
            print("\n👋 Scheduler stopped.")
    else:
        parser.print_help()
