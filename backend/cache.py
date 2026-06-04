"""
cache.py
────────
SQLite-backed classification cache.

Logic:
  - Cache key  = ticket_id
  - Cache valid when ticket's `updated` timestamp matches stored value
  - If ticket was updated in Jira → cache is STALE → re-classify
  - Force flag bypasses cache entirely
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger  = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent / "classifications.db"


# ── connection ────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    # WAL mode: allows concurrent reads while a write is in progress
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")   # safe + faster than FULL
    c.execute("PRAGMA foreign_keys=ON")
    return c


# ── init ──────────────────────────────────────────────────────

def init_db() -> None:
    """Create all cache / sync tables if they don't exist."""
    with _conn() as c:
        # ── Main tickets table (single source of truth for dashboard) ──
        c.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id         TEXT PRIMARY KEY,
                summary           TEXT NOT NULL,
                description       TEXT,
                ticket_json       TEXT NOT NULL,
                classification    TEXT,
                confidence        TEXT,
                reason            TEXT,
                signals           TEXT,
                dashboard_group   TEXT DEFAULT 'FIZ',
                moved_to_gclz     INTEGER DEFAULT 0,
                automation_locked INTEGER DEFAULT 0,
                content_hash      TEXT,
                needs_review      INTEGER DEFAULT 0,
                review_reason     TEXT,
                gclz_ticket_id    TEXT,
                classified_at     TEXT,
                moved_at          TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                is_active         INTEGER DEFAULT 1
            )
        """)

        # ── sync state (single-row table) ─────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                last_sync_time  TEXT NOT NULL,
                last_run_status TEXT DEFAULT 'never',
                last_run_at     TEXT
            )
        """)
        # Seed the row if missing — default to 30 days ago
        c.execute("""
            INSERT OR IGNORE INTO sync_state (id, last_sync_time)
            VALUES (1, datetime('now', '-30 days'))
        """)

        # ── sync run log ──────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at          TEXT NOT NULL,
                trigger_type    TEXT NOT NULL,
                tickets_fetched INTEGER DEFAULT 0,
                tickets_classified INTEGER DEFAULT 0,
                tickets_moved   INTEGER DEFAULT 0,
                tickets_flagged INTEGER DEFAULT 0,
                errors          TEXT,
                duration_sec    REAL
            )
        """)

        c.commit()
    logger.info("Cache DB ready → %s", DB_PATH)

    # ── Migrate: add is_active column if it doesn't exist yet ────────────────
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(tickets)").fetchall()]
        if "is_active" not in cols:
            c.execute("ALTER TABLE tickets ADD COLUMN is_active INTEGER DEFAULT 1")
            c.execute("UPDATE tickets SET is_active = 1")  # mark all existing as active
            c.commit()
            logger.info("Migration: added is_active column to tickets table")


# ── read ──────────────────────────────────────────────────────

def get_all_fiz_ticket_ids() -> set[str]:
    """Return all ticket_ids currently in the FIZ active dashboard group."""
    with _conn() as c:
        rows = c.execute(
            "SELECT ticket_id FROM tickets WHERE dashboard_group = 'FIZ' AND is_active = 1"
        ).fetchall()
    return {r["ticket_id"] for r in rows}


def get_unclassified_fiz_ticket_ids() -> set[str]:
    """Return ticket_ids that are active in FIZ but have no classification yet."""
    with _conn() as c:
        rows = c.execute(
            "SELECT ticket_id FROM tickets "
            "WHERE dashboard_group = 'FIZ' AND is_active = 1 AND classification IS NULL"
        ).fetchall()
    return {r["ticket_id"] for r in rows}


def mark_tickets_inactive(ticket_ids: list[str]) -> int:
    """
    Mark the given ticket IDs as inactive (is_active=0).
    They will be hidden from the FIZ dashboard but kept for audit history.
    Returns the number of rows updated.
    """
    if not ticket_ids:
        return 0
    with _conn() as c:
        placeholders = ",".join("?" * len(ticket_ids))
        c.execute(
            f"UPDATE tickets SET is_active = 0 WHERE ticket_id IN ({placeholders})",
            ticket_ids,
        )
        updated = c.execute("SELECT changes()").fetchone()[0]
        c.commit()
    if updated:
        logger.info("Marked %d ticket(s) as inactive: %s", updated, ticket_ids)
    return updated


# ── all classifications (for similarity search) ──────────────

def get_all_classifications() -> list[dict]:
    """
    Return all classified tickets.
    Used by GrayZoneInvestigator to find similar past tickets.
    No LLM call — pure DB read.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT ticket_id, classification, confidence, reason, signals "
            "FROM tickets WHERE classification IS NOT NULL "
            "ORDER BY classified_at DESC"
        ).fetchall()
    return [
        {
            "ticket_id":  r["ticket_id"],
            "board":      r["classification"],
            "confidence": r["confidence"],
            "reason":     r["reason"],
            "signals":    json.loads(r["signals"]) if r["signals"] else [],
        }
        for r in rows
    ]


# ── delete ────────────────────────────────────────────────────




# ══════════════════════════════════════════════════════════════
# Sync / Scheduler helpers
# ══════════════════════════════════════════════════════════════

def get_last_sync_time() -> str:
    """Return the ISO timestamp of the last successful sync."""
    with _conn() as c:
        row = c.execute("SELECT last_sync_time FROM sync_state WHERE id = 1").fetchone()
    return row["last_sync_time"] if row else "2020-01-01T00:00:00+00:00"


def update_last_sync_time(ts: str | None = None, status: str = "success") -> None:
    """Update last_sync_time to *ts* (default: now UTC)."""
    now = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with _conn() as c:
        c.execute("""
            UPDATE sync_state
            SET last_sync_time = ?, last_run_status = ?, last_run_at = ?
            WHERE id = 1
        """, (now, status, datetime.now(timezone.utc).isoformat()))
        c.commit()


def get_sync_state() -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
    if not row:
        return {}
    return dict(row)



# ── sync log ─────────────────────────────────────────────────

def log_sync_run(trigger_type: str, fetched: int, classified: int,
                 moved: int, flagged: int, errors: str | None, duration: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            INSERT INTO sync_log
                (run_at, trigger_type, tickets_fetched, tickets_classified,
                 tickets_moved, tickets_flagged, errors, duration_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (now, trigger_type, fetched, classified, moved, flagged, errors, duration))
        c.commit()


def get_sync_log(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
# Unified Tickets Table (Single Source of Truth for Dashboard)
# ══════════════════════════════════════════════════════════════

def _content_hash(ticket: dict) -> str:
    """Generate a deterministic hash of ticket content for change detection."""
    import hashlib
    content = json.dumps({
        "summary": ticket.get("summary", ""),
        "description": ticket.get("description", ""),
        "labels": sorted(ticket.get("labels", [])),
        "comments": [c.get("body", "") for c in ticket.get("comments", [])],
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def upsert_ticket(ticket: dict, classification: dict | None = None) -> None:
    """
    Insert or update a ticket in the unified tickets table.
    If classification is provided, also update classification fields.
    Skips tickets that are automation_locked.
    """
    now = datetime.now(timezone.utc).isoformat()
    content_hash = _content_hash(ticket)
    
    with _conn() as c:
        # Check if ticket exists and is automation_locked
        existing = c.execute(
            "SELECT automation_locked FROM tickets WHERE ticket_id = ?",
            (ticket.get("ticket_id"),)
        ).fetchone()
        
        if existing and existing["automation_locked"]:
            logger.debug("Ticket %s is automation_locked, skipping upsert", ticket.get("ticket_id"))
            return
        
        if classification:
            c.execute("""
                INSERT INTO tickets
                    (ticket_id, summary, description, ticket_json, classification,
                     confidence, reason, signals, content_hash, classified_at,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                    summary        = excluded.summary,
                    description    = excluded.description,
                    ticket_json    = excluded.ticket_json,
                    classification = excluded.classification,
                    confidence     = excluded.confidence,
                    reason         = excluded.reason,
                    signals        = excluded.signals,
                    content_hash   = excluded.content_hash,
                    classified_at  = excluded.classified_at,
                    updated_at     = excluded.updated_at
            """, (
                ticket.get("ticket_id"),
                ticket.get("summary", ""),
                ticket.get("description", ""),
                json.dumps(ticket),
                classification.get("board"),
                classification.get("confidence"),
                classification.get("reason"),
                json.dumps(classification.get("signals", [])),
                content_hash,
                now,
                ticket.get("created", now),
                now,
            ))
        else:
            c.execute("""
                INSERT INTO tickets
                    (ticket_id, summary, description, ticket_json, content_hash,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                    summary      = excluded.summary,
                    description  = excluded.description,
                    ticket_json  = excluded.ticket_json,
                    content_hash = excluded.content_hash,
                    updated_at   = excluded.updated_at
            """, (
                ticket.get("ticket_id"),
                ticket.get("summary", ""),
                ticket.get("description", ""),
                json.dumps(ticket),
                content_hash,
                ticket.get("created", now),
                now,
            ))
        c.commit()


def upsert_tickets_bulk(tickets: list[dict]) -> None:
    """Bulk upsert tickets without classification (used during fetch)."""
    for t in tickets:
        upsert_ticket(t)
    logger.info("Bulk upserted %d tickets", len(tickets))


def save_classification(ticket_id: str, classification: dict,
                        needs_review: bool = False, review_reason: str | None = None) -> None:
    """Update classification fields for an existing ticket."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            UPDATE tickets SET
                classification = ?,
                confidence     = ?,
                reason         = ?,
                signals        = ?,
                needs_review   = ?,
                review_reason  = ?,
                classified_at  = ?,
                updated_at     = ?
            WHERE ticket_id = ? AND automation_locked = 0
        """, (
            classification.get("board"),
            classification.get("confidence"),
            classification.get("reason"),
            json.dumps(classification.get("signals", [])),
            int(needs_review),
            review_reason,
            now,
            now,
            ticket_id,
        ))
        c.commit()
    logger.info("Saved classification for %s: %s (%s)", 
                ticket_id, classification.get("board"), classification.get("confidence"))


def mark_ticket_moved(ticket_id: str, gclz_ticket_id: str | None = None) -> None:
    """Mark a ticket as moved to GCLZ and lock it from further automation."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            UPDATE tickets SET
                dashboard_group   = 'GCLZ',
                moved_to_gclz     = 1,
                automation_locked = 1,
                gclz_ticket_id    = ?,
                moved_at          = ?,
                updated_at        = ?
            WHERE ticket_id = ?
        """, (gclz_ticket_id, now, now, ticket_id))
        c.commit()
    logger.info("Marked %s as moved to GCLZ (new key: %s)", ticket_id, gclz_ticket_id or "same")


def get_fiz_tickets() -> list[dict]:
    """Get all tickets in FIZ dashboard group (not moved to GCLZ)."""
    with _conn() as c:
        rows = c.execute("""
            SELECT ticket_json, classification, confidence, reason, signals,
                   needs_review, review_reason, classified_at
            FROM tickets
            WHERE dashboard_group = 'FIZ' AND moved_to_gclz = 0 AND is_active = 1
            ORDER BY updated_at DESC
        """).fetchall()
    
    results = []
    for r in rows:
        ticket = json.loads(r["ticket_json"])
        ticket["_classification"] = {
            "board": r["classification"],
            "confidence": r["confidence"],
            "reason": r["reason"],
            "signals": json.loads(r["signals"]) if r["signals"] else [],
            "needs_review": bool(r["needs_review"]),
            "review_reason": r["review_reason"],
            "classified_at": r["classified_at"],
        } if r["classification"] else None
        results.append(ticket)
    return results


def get_gclz_tickets() -> list[dict]:
    """Get all tickets that have been moved to GCLZ."""
    with _conn() as c:
        rows = c.execute("""
            SELECT ticket_json, classification, confidence, reason, signals,
                   gclz_ticket_id, moved_at, classified_at
            FROM tickets
            WHERE dashboard_group = 'GCLZ' AND moved_to_gclz = 1
            ORDER BY moved_at DESC
        """).fetchall()
    
    results = []
    for r in rows:
        ticket = json.loads(r["ticket_json"])
        ticket["_classification"] = {
            "board": r["classification"],
            "confidence": r["confidence"],
            "reason": r["reason"],
            "signals": json.loads(r["signals"]) if r["signals"] else [],
            "classified_at": r["classified_at"],
        } if r["classification"] else None
        ticket["_gclz_ticket_id"] = r["gclz_ticket_id"]
        ticket["_moved_at"] = r["moved_at"]
        results.append(ticket)
    return results


def get_all_classified_tickets(limit: int | None = None) -> list[dict]:
    """Return all classified tickets from the unified tickets table."""
    base_query = (
        "SELECT ticket_id, summary, classification, confidence, reason, signals, "
        "needs_review, review_reason, classified_at "
        "FROM tickets WHERE classification IS NOT NULL "
        "ORDER BY classified_at DESC"
    )
    with _conn() as c:
        if limit is not None:
            rows = c.execute(f"{base_query} LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute(base_query).fetchall()
    return [
        {
            "ticket_id": r["ticket_id"],
            "summary": r["summary"],
            "board": r["classification"],
            "confidence": r["confidence"],
            "reason": r["reason"],
            "signals": json.loads(r["signals"]) if r["signals"] else [],
            "needs_review": bool(r["needs_review"]),
            "review_reason": r["review_reason"],
            "classified_at": r["classified_at"],
        }
        for r in rows
    ]


def get_ticket_classification(ticket_id: str) -> dict | None:
    """Return classification data for a ticket if available."""
    with _conn() as c:
        row = c.execute(
            "SELECT classification, confidence, reason, signals, needs_review, review_reason, classified_at "
            "FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    if not row or not row["classification"]:
        return None
    return {
        "board": row["classification"],
        "confidence": row["confidence"],
        "reason": row["reason"],
        "signals": json.loads(row["signals"]) if row["signals"] else [],
        "needs_review": bool(row["needs_review"]),
        "review_reason": row["review_reason"],
        "classified_at": row["classified_at"],
    }


def get_ticket_content_hash(ticket_id: str) -> str | None:
    """Get the stored content hash for a ticket."""
    with _conn() as c:
        row = c.execute(
            "SELECT content_hash FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()
    return row["content_hash"] if row else None


def is_ticket_locked(ticket_id: str) -> bool:
    """Check if a ticket is locked from automation."""
    with _conn() as c:
        row = c.execute(
            "SELECT automation_locked FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()
    return bool(row and row["automation_locked"])


def get_dashboard_stats() -> dict:
    """Get ticket counts and performance metrics for dashboard."""
    # Approximate cost per classification call (gpt-4o-mini 2025 pricing)
    _COST_PER_CLASSIFY = 0.0004   # ~$0.0004 per ticket (2 LLM calls worst case)

    with _conn() as c:
        fiz_total = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE dashboard_group = 'FIZ'"
        ).fetchone()[0]
        fiz_classified = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE dashboard_group = 'FIZ' AND classification IS NOT NULL"
        ).fetchone()[0]
        fiz_needs_review = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE dashboard_group = 'FIZ' AND needs_review = 1"
        ).fetchone()[0]
        gclz_total = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE dashboard_group = 'GCLZ'"
        ).fetchone()[0]
        localisation = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE classification = 'Localisation'"
        ).fetchone()[0]
        not_localisation = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE classification = 'Not Localisation'"
        ).fetchone()[0]
        high_conf = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE confidence = 'high' AND classification IS NOT NULL"
        ).fetchone()[0]
        medium_conf = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE confidence = 'medium' AND classification IS NOT NULL"
        ).fetchone()[0]
        low_conf = c.execute(
            "SELECT COUNT(*) FROM tickets WHERE confidence = 'low' AND classification IS NOT NULL"
        ).fetchone()[0]
        total_synced = c.execute(
            "SELECT COALESCE(SUM(tickets_classified), 0) FROM sync_log"
        ).fetchone()[0]
        total_syncs = c.execute(
            "SELECT COUNT(*) FROM sync_log"
        ).fetchone()[0]
        last_classified = c.execute(
            "SELECT MAX(classified_at) FROM tickets WHERE classification IS NOT NULL"
        ).fetchone()[0]

    total_cls = fiz_classified
    return {
        "fiz_total":        fiz_total,
        "fiz_classified":   fiz_classified,
        "fiz_needs_review": fiz_needs_review,
        "gclz_total":       gclz_total,
        "board_split": {
            "localisation":     localisation,
            "not_localisation": not_localisation,
        },
        "confidence_breakdown": {
            "high":   high_conf,
            "medium": medium_conf,
            "low":    low_conf,
        },
        "automation_rate": round(high_conf / total_cls * 100) if total_cls else 0,
        "manual_review_rate": round(fiz_needs_review / total_cls * 100) if total_cls else 0,
        "estimated_llm_cost_usd": round(total_synced * _COST_PER_CLASSIFY, 4),
        "total_sync_runs":  total_syncs,
        "last_classified_at": last_classified,
    }


def clear_manual_review(ticket_id: str) -> None:
    """Mark a ticket as reviewed (no longer needs manual review)."""
    with _conn() as c:
        c.execute(
            "UPDATE tickets SET needs_review = 0, review_reason = NULL WHERE ticket_id = ?",
            (ticket_id,),
        )
        c.commit()


def get_manual_review_tickets() -> list[dict]:
    """Return all tickets flagged for manual review."""
    with _conn() as c:
        rows = c.execute("""
            SELECT ticket_id, summary, classification, confidence, 
                   needs_review, review_reason, classified_at
            FROM tickets 
            WHERE needs_review = 1 AND dashboard_group = 'FIZ'
            ORDER BY classified_at DESC
        """).fetchall()
    return [dict(r) for r in rows]
