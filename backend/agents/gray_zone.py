"""
agents/gray_zone.py
────────────────────
Agent 3 — Gray Zone Investigator

Only called when the router marks a ticket as uncertain
(gray_zone=True OR confidence="low").

Searches past classifications in the SQLite cache for similar tickets
and uses that evidence to make a final, more informed decision.

Cost: +1 LLM call per uncertain ticket (~$0.0002).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.base import (
    get_system_prompt,
    call_llm,
    extract_json,
)
from sanitizer import sanitize_text

logger = logging.getLogger(__name__)

# How many past similar tickets to surface as evidence
_MAX_SIMILAR = 5

# Keywords to ignore when scoring similarity
_STOPWORDS = {
    "with", "that", "this", "from", "have", "when", "they", "will",
    "been", "were", "their", "there", "error", "issue", "ticket",
    "please", "using", "cannot", "after",
}


def _find_similar_tickets(ticket: dict, exclude_id: str) -> list[dict]:
    """
    Search the SQLite cache for past tickets with overlapping keywords.
    Pure DB lookup — no LLM call.
    """
    from cache import get_all_classifications

    summary  = (ticket.get("summary",     "") or "").lower()
    desc     = (ticket.get("description", "") or "").lower()
    combined = f"{summary} {desc}"

    keywords = {
        w for w in combined.split()
        if len(w) > 3 and w.isalpha() and w not in _STOPWORDS
    }

    if not keywords:
        return []

    scored: list[tuple[int, dict]] = []
    for past in get_all_classifications():
        if past.get("ticket_id") == exclude_id:
            continue
        text    = f"{past.get('reason','')} {' '.join(past.get('signals',[]))}".lower()
        overlap = sum(1 for kw in keywords if kw in text)
        if overlap > 0:
            scored.append((overlap, past))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:_MAX_SIMILAR]]


def investigate_gray_zone(
    ticket: dict,
    initial_result: dict,
) -> dict[str, Any]:
    """
    Re-classify an uncertain ticket using evidence from past similar tickets.

    Args:
        ticket:         Full ticket dict from jira_fetcher
        initial_result: Uncertain result from the router's first pass

    Returns:
        Refined classification dict with added 'evidence' and 'similar_count' keys
    """
    ticket_id = ticket.get("ticket_id", "UNKNOWN")
    logger.info("GrayZone: investigating %s", ticket_id)

    # ── 1. Find similar past tickets (free — DB only) ──────────────────────────
    similar = _find_similar_tickets(ticket, exclude_id=ticket_id)
    logger.info("GrayZone: %d similar past tickets found for %s", len(similar), ticket_id)

    # ── 2. Build evidence block ────────────────────────────────────────────────
    if similar:
        evidence_lines = [
            f"  • {s['ticket_id']}: → {s['board']} "
            f"(confidence={s['confidence']}) — {s.get('reason','')[:120]}"
            for s in similar
        ]
        board_counts: dict[str, int] = {}
        for s in similar:
            board_counts[s["board"]] = board_counts.get(s["board"], 0) + 1
        pattern = ", ".join(f"{b}: {c}" for b, c in board_counts.items())
        evidence_text = (
            f"SIMILAR PAST TICKETS (pattern: {pattern}):\n"
            + "\n".join(evidence_lines)
        )
    else:
        evidence_text = "SIMILAR PAST TICKETS: none found in history"

    # ── 3. Build investigation prompt ──────────────────────────────────────────
    # Send only a compact ticket reference — NOT the full description again.
    # The initial_result already contains everything the first call extracted.
    # Sending full ticket data a second time wastes ~400 tokens for nothing.
    summary  = sanitize_text((ticket.get("summary") or "")[:200])
    sep = "─" * 47
    investigation_prompt = (
        f"TICKET: {ticket_id} — {summary}\n\n"
        f"{sep}\n"
        "This ticket was initially classified but flagged as uncertain.\n"
        f"Initial board:      {initial_result.get('board')}\n"
        f"Initial confidence: {initial_result.get('confidence')}\n"
        f"Initial reason:     {initial_result.get('reason', '')}\n"
        f"Initial signals:    {', '.join(initial_result.get('signals', []))}\n\n"
        f"{evidence_text}\n\n"
        "Make your FINAL classification using this evidence."
    )

    # ── 4. Call LLM once with enriched context ─────────────────────────────────
    messages = [
        SystemMessage(content=get_system_prompt()),
        HumanMessage(content=investigation_prompt),
    ]

    raw    = call_llm(messages, ticket_id)
    result = extract_json(raw, ticket_id)

    result["evidence"]      = evidence_text
    result["similar_count"] = len(similar)

    logger.info(
        "GrayZone: %s → %s (%s)  similar_tickets_used=%d",
        ticket_id, result["board"], result["confidence"], len(similar),
    )
    return result
