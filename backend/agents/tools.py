"""
agents/tools.py
───────────────
All LangChain tools for the FIZ chat agent.

Design rules:
  - One tool = one clear purpose (LLM never guesses filter syntax)
  - SQLite only unless the user asks for a specific ticket by ID
  - Each tool returns compact JSON to save response tokens
  - Max 20 results per list tool
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_RESULTS = 20


def _compact(ticket: dict) -> dict:
    """Strip a classified ticket down to the fields the LLM needs."""
    return {
        "ticket_id":    ticket.get("ticket_id"),
        "summary":      (ticket.get("summary") or "")[:140],
        "board":        ticket.get("board"),
        "confidence":   ticket.get("confidence"),
        "needs_review": bool(ticket.get("needs_review", False)),
        "reason":       (ticket.get("reason") or "")[:100],
        "signals":      ticket.get("signals", [])[:5],
    }


# ── Tool 1 ────────────────────────────────────────────────────────────────────
@tool
def get_stats(dummy: str = "") -> str:
    """Get overall classification statistics for the FIZ project.
    Use this for questions like:
      - 'how many tickets are classified?'
      - 'what is the Localisation vs Not Localisation split?'
      - 'give me a summary'
    """
    from cache import get_all_classified_tickets

    all_t = get_all_classified_tickets()
    if not all_t:
        return json.dumps({"message": "No tickets classified yet."})

    localisation    = sum(1 for t in all_t if t.get("board") == "Localisation")
    not_localisation = sum(1 for t in all_t if t.get("board") == "Not Localisation")
    needs_review    = sum(1 for t in all_t if t.get("needs_review"))
    high            = sum(1 for t in all_t if t.get("confidence") == "high")
    medium          = sum(1 for t in all_t if t.get("confidence") == "medium")
    low             = sum(1 for t in all_t if t.get("confidence") == "low")

    return json.dumps({
        "total_classified":  len(all_t),
        "localisation":      localisation,
        "not_localisation":  not_localisation,
        "needs_review":      needs_review,
        "confidence":        {"high": high, "medium": medium, "low": low},
    })


# ── Tool 2 ────────────────────────────────────────────────────────────────────
@tool
def get_tickets_by_board(board: str) -> str:
    """Get all classified tickets for a specific board.
    Use this for questions like:
      - 'show Localisation tickets'
      - 'list Not Localisation tickets'

    Args:
        board: Must be exactly 'Localisation' or 'Not Localisation'
    """
    from cache import get_all_classified_tickets

    board_lower = board.strip().lower()
    if board_lower in ("localisation", "localization"):
        board_clean = "Localisation"
    elif board_lower in ("not localisation", "not localization", "finance", "other"):
        board_clean = "Not Localisation"
    else:
        return json.dumps({"error": f"Invalid board '{board}'. Use 'Localisation' or 'Not Localisation'."})

    tickets = [_compact(t) for t in get_all_classified_tickets() if t.get("board") == board_clean]
    return json.dumps({
        "board":   board_clean,
        "count":   len(tickets),
        "showing": min(len(tickets), _MAX_RESULTS),
        "tickets": tickets[:_MAX_RESULTS],
    })


# ── Tool 3 ────────────────────────────────────────────────────────────────────
@tool
def get_gray_zone_tickets(dummy: str = "") -> str:
    """Get all tickets flagged for manual review.
    Use this for questions like:
      - 'show tickets needing manual review'
      - 'which tickets need review?'
    """
    from cache import get_all_classified_tickets

    tickets = [_compact(t) for t in get_all_classified_tickets() if t.get("needs_review")]
    return json.dumps({
        "count":   len(tickets),
        "showing": min(len(tickets), _MAX_RESULTS),
        "tickets": tickets[:_MAX_RESULTS],
        "message": "These tickets were flagged for manual review." if tickets else "No tickets need manual review.",
    })


# ── Tool 4 ────────────────────────────────────────────────────────────────────
@tool
def get_low_confidence_tickets(board: str = "") -> str:
    """Get all tickets with low confidence.
    Use this for questions like:
      - 'show low confidence tickets'
      - 'which Localisation tickets have low confidence?'

    Args:
        board: Optional — 'Localisation' or 'Not Localisation'. Leave empty for all boards.
    """
    from cache import get_all_classified_tickets

    tickets = [t for t in get_all_classified_tickets() if t.get("confidence") == "low"]
    if board.strip():
        b = board.strip().title()
        tickets = [t for t in tickets if t.get("board") == b]

    compact = [_compact(t) for t in tickets]
    return json.dumps({
        "count":   len(compact),
        "showing": min(len(compact), _MAX_RESULTS),
        "tickets": compact[:_MAX_RESULTS],
    })


# ── Tool 5 ────────────────────────────────────────────────────────────────────
@tool
def get_recent_classifications(limit: int = 10) -> str:
    """Get the most recently classified tickets.
    Use this for questions like:
      - 'what was classified recently?'
      - 'show the last 5 classifications'

    Args:
        limit: Number of tickets to return (max 20)
    """
    from cache import get_all_classified_tickets

    limit   = max(1, min(limit, _MAX_RESULTS))
    tickets = get_all_classified_tickets(limit=limit)
    compact = [_compact(t) for t in tickets]
    return json.dumps({"count": len(compact), "tickets": compact})


# ── Tool 6 ────────────────────────────────────────────────────────────────────
@tool
def search_by_keyword(keyword: str) -> str:
    """Search classified tickets by keyword in their reason or signals.
    Use this for questions like:
      - 'find tickets about payment'
      - 'search for currency related tickets'
      - 'tickets mentioning voucher'

    Args:
        keyword: Single keyword to search for (e.g. 'payment', 'currency', 'voucher')
    """
    from cache import get_all_classified_tickets

    kw = keyword.strip().lower()
    if not kw:
        return json.dumps({"error": "keyword cannot be empty"})

    results = []
    for t in get_all_classified_tickets():
        haystack = f"{t.get('reason', '')} {' '.join(t.get('signals', []))}".lower()
        if kw in haystack:
            results.append(_compact(t))

    return json.dumps({
        "keyword": keyword,
        "count":   len(results),
        "showing": min(len(results), _MAX_RESULTS),
        "tickets": results[:_MAX_RESULTS],
    })


# ── Tool 7 ────────────────────────────────────────────────────────────────────
@tool
def get_confidence_breakdown(board: str = "") -> str:
    """Get confidence level breakdown (high / medium / low counts and percentages).
    Use this for questions like:
      - 'what is the confidence breakdown?'
      - 'how confident are the Localisation classifications?'

    Args:
        board: Optional — 'Localisation' or 'Not Localisation'. Leave empty for all.
    """
    from cache import get_all_classified_tickets

    tickets = get_all_classified_tickets()
    if board.strip():
        b = board.strip().title()
        tickets = [t for t in tickets if t.get("board") == b]

    total  = len(tickets)
    high   = sum(1 for t in tickets if t.get("confidence") == "high")
    medium = sum(1 for t in tickets if t.get("confidence") == "medium")
    low    = sum(1 for t in tickets if t.get("confidence") == "low")

    return json.dumps({
        "board":      board.strip() or "all",
        "total":      total,
        "high":       high,
        "medium":     medium,
        "low":        low,
        "high_pct":   round(high / total * 100) if total else 0,
        "medium_pct": round(medium / total * 100) if total else 0,
        "low_pct":    round(low / total * 100) if total else 0,
    })


# ── Tool 8 ────────────────────────────────────────────────────────────────────
@tool
def get_ticket_detail(ticket_id: str) -> str:
    """Fetch full details of ONE specific Jira ticket by its ID.
    Use this ONLY when the user mentions a specific ticket ID like FIZ-43429.
    Do NOT use this for general listing — use other tools instead.
    This makes a live Jira API call.

    Args:
        ticket_id: Jira ticket ID e.g. FIZ-43429
    """
    from cache import get_ticket_classification

    tid = ticket_id.upper().strip()

    # Check if we already have a classification for it
    cached_class = get_ticket_classification(tid)

    try:
        from jira_fetcher import get_ticket_details as _fetch
        ticket = _fetch(tid)
        if not ticket:
            return json.dumps({"error": f"Ticket {tid} not found in Jira."})

        result = {
            "ticket_id":     ticket.get("ticket_id"),
            "summary":       (ticket.get("summary") or "")[:300],
            "status":        ticket.get("status"),
            "priority":      ticket.get("priority"),
            "assignee":      ticket.get("assignee"),
            "reporter":      ticket.get("reporter"),
            "issue_type":    ticket.get("issue_type"),
            "description":   (ticket.get("description") or "")[:400],
            "comment_count": len(ticket.get("comments", [])),
            "updated":       ticket.get("updated"),
        }

        if cached_class:
            result["classification"] = {
                "board":        cached_class.get("board"),
                "confidence":   cached_class.get("confidence"),
                "needs_review": cached_class.get("needs_review"),
                "reason":       cached_class.get("reason"),
            }
        else:
            result["classification"] = "Not classified yet"

        return json.dumps(result)

    except ConnectionError as e:
        return json.dumps({"error": f"Cannot reach Jira: {e}"})


# ── Tool 9 ────────────────────────────────────────────────────────────────────
@tool
def classify_ticket(ticket_id: str) -> str:
    """Classify a single Jira ticket by its ID using the AI classifier.
    Use this when the user says things like:
      - 'classify FIZ-43429'
      - 'run classification on FIZ-43500'
      - 'what board should FIZ-43429 go to?'
    This fetches the ticket from Jira and runs the full classification pipeline.

    Args:
        ticket_id: Jira ticket ID e.g. FIZ-43429
    """
    tid = ticket_id.upper().strip()

    try:
        from jira_fetcher import get_ticket_details as _fetch
        ticket = _fetch(tid)
        if not ticket:
            return json.dumps({"error": f"Ticket {tid} not found in Jira."})

        from agents.router import smart_classify
        from cache import upsert_ticket
        result = smart_classify(ticket, force=False)
        upsert_ticket(ticket, classification=result)

        return json.dumps({
            "ticket_id":    tid,
            "board":        result.get("board"),
            "confidence":   result.get("confidence"),
            "reason":       result.get("reason"),
            "signals":      result.get("signals", []),
            "gray_zone":    result.get("gray_zone", False),
            "investigated": result.get("investigated", False),
            "from_cache":   result.get("from_cache", False),
        })

    except ConnectionError as e:
        return json.dumps({"error": f"Cannot reach Jira: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Classification failed: {e}"})


# ── Tool 10 ───────────────────────────────────────────────────────────────────
@tool
def classify_batch_by_status(status: str = "To Do", max_tickets: int = 10) -> str:
    """Classify multiple tickets from a Jira status column.
    Use this when the user says things like:
      - 'classify all To Do tickets'
      - 'run classification on In Progress tickets'
      - 'classify the first 5 To Do tickets'
    This fetches tickets from Jira and classifies each one.

    Args:
        status: Jira status column — 'To Do', 'In Progress', or 'Done'
        max_tickets: How many tickets to classify (default 10, max 20)
    """
    max_tickets = max(1, min(max_tickets, _MAX_RESULTS))

    try:
        from jira_fetcher import get_tickets_by_status
        tickets = get_tickets_by_status(status=status, max_results=max_tickets)
        if not tickets:
            return json.dumps({"error": f"No tickets found in '{status}' column."})

        from agents.router import smart_classify
        from cache import upsert_ticket
        results = []
        cached  = 0
        for t in tickets:
            r = smart_classify(t, force=False)
            if r.get("from_cache"):
                cached += 1
            upsert_ticket(t, classification=r)
            results.append({
                "ticket_id":  t.get("ticket_id"),
                "board":      r.get("board"),
                "confidence": r.get("confidence"),
                "from_cache": r.get("from_cache", False),
            })

        return json.dumps({
            "status":     status,
            "classified": len(results),
            "from_cache": cached,
            "new_calls":  len(results) - cached,
            "results":    results,
        })

    except ConnectionError as e:
        return json.dumps({"error": f"Cannot reach Jira: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Batch classification failed: {e}"})


# ── Export ────────────────────────────────────────────────────────────────────
ALL_TOOLS = [
    get_stats,
    get_tickets_by_board,
    get_gray_zone_tickets,
    get_low_confidence_tickets,
    get_recent_classifications,
    search_by_keyword,
    get_confidence_breakdown,
    get_ticket_detail,
    classify_ticket,
    classify_batch_by_status,
]
