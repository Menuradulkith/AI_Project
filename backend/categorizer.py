"""
categorizer.py
──────────────
Public API for ticket classification.
All LLM logic lives in agents/ — this module is an intentionally thin wrapper.

Usage:
    from categorizer import classify_ticket
    result = classify_ticket(ticket_dict)
    result = classify_ticket(ticket_dict, force=True)  # skip cache
"""

from __future__ import annotations

import logging
from typing import Any

from cache import init_db

logger = logging.getLogger(__name__)

# Initialise SQLite cache on first import
init_db()


def classify_ticket(ticket: dict, force: bool = False) -> dict[str, Any]:
    """
    Classify a Jira ticket as Localisation or Not Localisation.

    Args:
        ticket: Ticket dict from jira_fetcher._build_ticket()
        force:  Skip cache, always call LLM

    Returns:
        dict with keys:
          board, confidence, reason, signals, gray_zone,
          from_cache, investigated, evidence
    """
    from agents.router import smart_classify
    return smart_classify(ticket, force=force)


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import logging as _logging

    from jira_fetcher import get_ticket_details, get_tickets_by_status

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Classify Jira tickets (FIZ)")
    parser.add_argument("--ticket", "-t", help="Single ticket ID e.g. FIZ-43385")
    parser.add_argument("--status", "-s", default="To Do",
                        help="Classify all tickets in this status column")
    parser.add_argument("--max",    "-m", type=int, default=10)
    parser.add_argument("--force",        action="store_true", help="Skip cache")
    args = parser.parse_args()

    if args.ticket:
        tickets = [get_ticket_details(args.ticket)]
    else:
        tickets = get_tickets_by_status(args.status, args.max)

    print("\nModel: gpt-4o-mini   Agents: SmartRouter + GrayZoneInvestigator\n")
    for t in tickets:
        if not t:
            continue
        print(f"{'─'*60}")
        print(f"  {t['ticket_id']}  {t.get('cs_ref') or ''}")
        print(f"  {t['summary'][:80]}")
        try:
            r     = classify_ticket(t, force=args.force)
            blue  = "\033[94m"; green = "\033[92m"; reset = "\033[0m"
            color = green if r["board"] == "Localisation" else blue
            print(f"  Board      : {color}{r['board']}{reset}  ({r['confidence']} confidence)")
            print(f"  Reason     : {r['reason']}")
            print(f"  Signals    : {', '.join(r.get('signals', []))}")
            if r.get("gray_zone"):
                print("  ⚠  Gray zone")
            if r.get("investigated"):
                print(f"  🔍 Investigated  similar_tickets={r.get('similar_count', 0)}")
            if r.get("from_cache"):
                print("  ⚡ From cache")
        except Exception as e:
            print(f"  ERROR: {e}")
    print()



