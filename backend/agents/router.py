"""
agents/router.py
─────────────────
Agent 1 — Smart Ticket Router

Flow:
  1. Cache check  → return instantly (free)
  2. Quick classify via LLM (1 call)
  3. Clear result → save & return
  4. Uncertain    → escalate to GrayZoneInvestigator (+1 call)
  5. Save & return

Cost:
  Cached:    0 calls  (free)
  Clear:     1 call   (~$0.0002)
  Uncertain: 2 calls  (~$0.0004)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from cache import get_ticket_classification, upsert_ticket
from agents.base import (
    get_system_prompt,
    build_classify_prompt,
    call_llm,
    extract_json,
)

logger = logging.getLogger(__name__)


def smart_classify(ticket: dict, force: bool = False) -> dict[str, Any]:
    """
    Classify a ticket — uses cache, LLM, and gray zone investigator as needed.

    Args:
        ticket: Ticket dict from jira_fetcher
        force:  Skip cache, always call LLM

    Returns:
        dict with keys: board, confidence, reason, signals,
                        gray_zone, from_cache, investigated, evidence
    """
    # local import to avoid circular ref at module load time
    from agents.gray_zone import investigate_gray_zone

    ticket_id  = ticket.get("ticket_id", "UNKNOWN")
    updated_at = ticket.get("updated",   "")

    # ── 1. Cache check (unified tickets table) ────────────────────────────────
    if not force:
        stored = get_ticket_classification(ticket_id)
        if stored and stored.get("classified_at"):
            # Only use cache if ticket hasn't been updated since last classification
            # (updated_at from Jira vs classified_at in DB)
            # Simple guard: if we have a classification AND the ticket hash hasn't changed
            # this is handled upstream in scheduler; here we trust the stored result
            cached_result = {
                "board":        stored["board"],
                "confidence":   stored["confidence"],
                "reason":       stored["reason"],
                "signals":      stored.get("signals", []),
                "gray_zone":    False,
                "from_cache":   True,
                "investigated": False,
                "evidence":     "",
                "ticket_id":    ticket_id,
            }
            logger.info("Router: cache HIT  %s", ticket_id)
            return cached_result

    # ── 2. Quick classify ──────────────────────────────────────────────────────
    logger.info("Router: classifying %s (force=%s)", ticket_id, force)

    messages = [
        SystemMessage(content=get_system_prompt()),
        HumanMessage(content=build_classify_prompt(ticket)),
    ]

    raw    = call_llm(messages, ticket_id)
    result = extract_json(raw, ticket_id)

    result.update({
        "ticket_id":    ticket_id,
        "from_cache":   False,
        "investigated": False,
        "evidence":     "",
    })

    # ── 3. Escalate if uncertain ───────────────────────────────────────────────
    is_uncertain = (
        result.get("gray_zone") is True or
        result.get("confidence") == "low"
    )

    if is_uncertain:
        logger.info(
            "Router: %s uncertain (gray_zone=%s confidence=%s) → escalating",
            ticket_id, result.get("gray_zone"), result.get("confidence"),
        )
        investigated = investigate_gray_zone(ticket, result)
        result.update({
            "board":         investigated.get("board",         result["board"]),
            "confidence":    investigated.get("confidence",    result["confidence"]),
            "reason":        investigated.get("reason",        result["reason"]),
            "signals":       investigated.get("signals",       result["signals"]),
            "gray_zone":     investigated.get("gray_zone",     True),
            "investigated":  True,
            "evidence":      investigated.get("evidence",      ""),
            "similar_count": investigated.get("similar_count", 0),
        })
    else:
        logger.info(
            "Router: %s → %s (%s)  clear",
            ticket_id, result["board"], result["confidence"],
        )

    # ── 4. Save to unified tickets table ────────────────────────────────────
    upsert_ticket(ticket, classification=result)

    return result
