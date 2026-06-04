"""
jira_fetcher.py
───────────────
Fetch ticket details from the Jira project defined in .env.

Supported operations
  • get_tickets_by_status(status)   – list of tickets in one column
  • get_ticket_details(ticket_id)   – full detail of a single ticket
  • print_ticket(ticket)            – pretty-print one ticket dict

Run directly:
    python jira_fetcher.py
  → prints all TO DO tickets.

Requires a .env file (copy .env.example and fill in real values).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

import requests
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# 1.  Load configuration
# ──────────────────────────────────────────────────────────────
load_dotenv()

JIRA_BASE_URL: str          = os.getenv("JIRA_BASE_URL", "").rstrip("/")
EMAIL: str                  = os.getenv("JIRA_EMAIL", "")
API_TOKEN: str              = os.getenv("JIRA_API_TOKEN", "")
PROJECT_KEY: str            = os.getenv("JIRA_PROJECT_KEY", "FIZ")
LOCALIZATION_PROJECT_KEY: str = os.getenv("LOCALIZATION_PROJECT_KEY", "GCLZ")
JIRA_WRITE_ENABLED: bool    = os.getenv("JIRA_WRITE_ENABLED", "0").strip() in ("1", "true", "yes")

# Validate that the three required settings are present
_missing = [k for k, v in {
    "JIRA_BASE_URL": JIRA_BASE_URL,
    "JIRA_EMAIL":    EMAIL,
    "JIRA_API_TOKEN": API_TOKEN,
}.items() if not v]

if _missing:
    raise EnvironmentError(
        f"Missing required .env values: {', '.join(_missing)}\n"
        "Copy .env.example → .env and fill in the real credentials."
    )

AUTH    = HTTPBasicAuth(EMAIL, API_TOKEN)
HEADERS = {"Accept": "application/json"}

# ── Comment account (optional separate credentials) ───────────
# If JIRA_COMMENT_EMAIL + JIRA_COMMENT_TOKEN are set in .env, comments
# will be posted under that account (e.g. a shared service account).
# Falls back to the main read account if not configured.
_COMMENT_EMAIL = os.getenv("JIRA_COMMENT_EMAIL", "").strip() or EMAIL
_COMMENT_TOKEN = os.getenv("JIRA_COMMENT_TOKEN", "").strip() or API_TOKEN

# ── Retry-enabled session ─────────────────────────────────────
# Retries up to 3 times on network errors and 429/500/502/503/504.
# Uses exponential back-off: 0s, 2s, 4s between attempts.
_retry_strategy = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT"],
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)
_session = requests.Session()
_session.mount("https://", _adapter)
_session.mount("http://",  _adapter)
_session.auth    = AUTH
_session.headers.update(HEADERS)

# ── Comment session (may use a different account) ─────────────
_comment_session = requests.Session()
_comment_session.mount("https://", _adapter)
_comment_session.mount("http://",  _adapter)
_comment_session.auth = HTTPBasicAuth(_COMMENT_EMAIL, _COMMENT_TOKEN)
_comment_session.headers.update(HEADERS)

# Fields to request from Jira (keeps payload small)
ISSUE_FIELDS = [
    "summary",
    "description",
    "status",
    "priority",
    "assignee",
    "reporter",
    "created",
    "updated",
    "comment",
    "labels",
    "issuetype",
    "customfield_10020",   # Sprint – present on most cloud boards
]


# ──────────────────────────────────────────────────────────────
# 2.  Helpers
# ──────────────────────────────────────────────────────────────

def _extract_text(node) -> str:
    """
    Recursively walk an Atlassian Document Format (ADF) node
    and return all text content as a plain string.
    Falls back gracefully if the field is already a plain string
    or is None / empty.
    """
    if not node:
        return ""
    if isinstance(node, str):
        return node.strip()

    parts: list[str] = []

    def _walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content", []):
                _walk(child)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return " ".join(p for p in parts if p).strip()


def _extract_cs_ref(summary: str) -> Optional[str]:
    """Pull the CS reference (e.g. CS0512074) out of the summary line."""
    m = re.search(r"CS\d{6,}", summary)
    return m.group(0) if m else None


def _fmt_ts(iso: Optional[str]) -> str:
    """Return a readable timestamp; keeps raw string if parsing fails."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    except ValueError:
        return iso


def _build_ticket(issue: dict) -> dict:
    """Map a raw Jira issue dict to the flat ticket dict used by this app."""
    fields  = issue.get("fields", {})
    summary = fields.get("summary", "")

    # Last 5 comments (oldest → newest)
    raw_comments = fields.get("comment", {}).get("comments", [])
    comments = [
        {
            "author":  c.get("author", {}).get("displayName", "?"),
            "body":    _extract_text(c.get("body")),
            "created": _fmt_ts(c.get("created")),
        }
        for c in raw_comments[-5:]
    ]

    assignee = fields.get("assignee")
    priority = fields.get("priority")
    sprint_field = fields.get("customfield_10020")
    sprint_name  = None
    if isinstance(sprint_field, list) and sprint_field:
        sprint_name = sprint_field[-1].get("name")

    return {
        "ticket_id":      issue.get("key", ""),                # FIZ-43429
        "cs_ref":         _extract_cs_ref(summary),           # CS0512074
        "summary":        summary,
        "description":    _extract_text(fields.get("description")),
        "status":         fields.get("status", {}).get("name", ""),
        "status_category": fields.get("status", {}).get("statusCategory", {}).get("name", ""),
        "priority":       priority.get("name") if priority else "—",
        "issue_type":  fields.get("issuetype", {}).get("name", ""),
        "reporter":    fields.get("reporter", {}).get("displayName", "?"),
        "assignee":    assignee.get("displayName") if assignee else "Unassigned",
        "created":     _fmt_ts(fields.get("created")),
        "updated":     _fmt_ts(fields.get("updated")),
        "labels":      fields.get("labels", []),
        "sprint":      sprint_name,
        "comments":    comments,
    }


# ──────────────────────────────────────────────────────────────
# 3.  Main API functions
# ──────────────────────────────────────────────────────────────

# Map friendly board-column names → JQL clause
_STATUS_JQL: dict[str, str] = {
    # ── To-Do board column ────────────────────────────────────
    "to do":       'statusCategory = "To Do"',
    # ── In-Progress board column ──────────────────────────────
    "in progress": 'statusCategory = "In Progress"',
    # ── Done / Closed board column ────────────────────────────
    "done":        'statusCategory = "Done"',
}


def get_tickets_by_status(status: str = "To Do", max_results: int = 100) -> list[dict]:
    """
    Return tickets matching a board column name or an exact Jira status.

    Board column names (case-insensitive):
        "To Do", "In Progress", "Resolved", "Done"

    You can also pass any exact Jira status name, e.g.
        "Under Investigation", "Fix In Progress", "New"
    """
    # Only fetch customer-raised defects (Support Issues & Defects)
    # Exclude cloned tickets — summaries starting with "CLONE -" are copies
    defect_filter = 'issuetype in ("Support Issue", "Defect") AND NOT summary ~ "CLONE" AND reporter = "ServiceNow Jira Integration"'

    jql_clause = _STATUS_JQL.get(status.lower())
    if jql_clause:
        jql = f'project = "{PROJECT_KEY}" AND {defect_filter} AND {jql_clause} ORDER BY updated DESC'
    else:
        # fall back to exact status name match
        jql = f'project = "{PROJECT_KEY}" AND {defect_filter} AND status = "{status}" ORDER BY updated DESC'

    url    = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql":        jql,
        "maxResults": max_results,
        "fields":     ",".join(ISSUE_FIELDS),
    }

    try:
        response = _session.get(url, params=params, timeout=20)
    except requests.exceptions.ConnectTimeout:
        raise ConnectionError("Timed out connecting to Jira. Check your VPN / network.")
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Cannot reach Jira: {e}")

    if response.status_code == 200:
        data   = response.json()
        issues = data.get("issues", [])
        total  = data.get("total", len(issues))
        logger.info("Found %d of %d '%s' tickets in project %s",
                    len(issues), total, status, PROJECT_KEY)
        return [_build_ticket(i) for i in issues]

    # ── error handling ──────────────────────────────────────
    logger.error("HTTP %d fetching status='%s' | JQL: %s", response.status_code, status, jql)
    try:
        err = response.json()
        for msg in err.get("errorMessages", []):
            logger.error("  %s", msg)
        for k, v in err.get("errors", {}).items():
            logger.error("  %s: %s", k, v)
    except Exception:
        logger.error("  Raw: %s", response.text[:400])
    return []


def fetch_tickets_since(since: str, status: str | list[str] | None = None,
                        max_results: int = 200) -> list[dict]:
    """
    Fetch tickets created or updated since *since* (ISO datetime string).
    Optionally filter by status category.

    Args:
        since:       ISO datetime, e.g. "2026-05-15T08:00:00+00:00"
        status:      Optional status filter. Can be a single status string,
                    a list of statuses, or a comma-separated string.
        max_results: Max tickets to return
    Returns:
        list of ticket dicts
    """
    defect_filter = 'issuetype in ("Support Issue", "Defect") AND NOT summary ~ "CLONE" AND reporter = "ServiceNow Jira Integration"'
    # Convert ISO to JQL-friendly format
    try:
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        jql_since = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        jql_since = since

    jql = (
        f'project = "{PROJECT_KEY}" AND {defect_filter} '
        f'AND updated >= "{jql_since}"'
    )

    if status:
        statuses: list[str]
        if isinstance(status, str):
            statuses = [s.strip() for s in status.split(",") if s.strip()]
        else:
            statuses = [s.strip() for s in status if s and s.strip()]

        if len(statuses) == 1:
            s = statuses[0]
            jql_clause = _STATUS_JQL.get(s.lower())
            if jql_clause:
                jql += f" AND {jql_clause}"
            else:
                jql += f' AND status = "{s}"'
        elif len(statuses) > 1:
            quoted = ", ".join(f'"{s}"' for s in statuses)
            jql += f" AND status in ({quoted})"

    jql += " ORDER BY updated DESC"

    url    = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql":        jql,
        "maxResults": max_results,
        "fields":     ",".join(ISSUE_FIELDS),
    }

    try:
        response = _session.get(url, params=params, timeout=30)
    except requests.exceptions.ConnectTimeout:
        raise ConnectionError("Timed out connecting to Jira.")
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Cannot reach Jira: {e}")

    if response.status_code == 200:
        data   = response.json()
        issues = data.get("issues", [])
        total  = data.get("total", len(issues))
        logger.info("Incremental fetch: %d of %d tickets since %s",
                     len(issues), total, jql_since)
        return [_build_ticket(i) for i in issues]

    logger.error("HTTP %d on incremental fetch | JQL: %s", response.status_code, jql)
    return []


def get_transitions(ticket_id: str) -> list[dict]:
    """Return available workflow transitions for a ticket."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}/transitions"
    try:
        r = _session.get(url, timeout=15)
    except Exception as e:
        logger.error("Failed to get transitions for %s: %s", ticket_id, e)
        return []
    if r.status_code == 200:
        return r.json().get("transitions", [])
    logger.error("HTTP %d getting transitions for %s", r.status_code, ticket_id)
    return []


def transition_ticket(ticket_id: str, transition_name: str) -> bool:
    """
    Move a ticket to a different status by transition name.
    First fetches available transitions, then finds the matching one.
    """
    if not JIRA_WRITE_ENABLED:
        logger.warning("Jira write disabled: skipping transition for %s → '%s'", ticket_id, transition_name)
        return False
    transitions = get_transitions(ticket_id)
    target = None
    for t in transitions:
        if t["name"].lower() == transition_name.lower():
            target = t
            break

    if not target:
        available = [t["name"] for t in transitions]
        logger.warning(
            "Transition '%s' not found for %s. Available: %s",
            transition_name, ticket_id, available,
        )
        return False

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}/transitions"
    payload = {"transition": {"id": target["id"]}}
    try:
        r = _session.post(url, json=payload, timeout=15)
    except Exception as e:
        logger.error("Failed to transition %s: %s", ticket_id, e)
        return False

    if r.status_code in (200, 204):
        logger.info("Transitioned %s → '%s'", ticket_id, transition_name)
        return True

    logger.error("HTTP %d transitioning %s → '%s': %s",
                 r.status_code, ticket_id, transition_name, r.text[:200])
    return False


def move_issue_to_project(ticket_id: str, target_project_key: str | None = None) -> dict:
    """
    Move a Jira issue from the current project (FIZ) to the target project
    (default: LOCALIZATION_PROJECT_KEY from .env, i.e. GCLZ).

    Jira Cloud API:  POST /rest/api/3/issue/{key}/moves
    Requires the 'Move Issues' project permission in both projects.

    Returns:
        dict with keys:
          success (bool), new_ticket_id (str|None), error (str|None)
    """
    if not JIRA_WRITE_ENABLED:
        logger.warning("Jira write disabled: skipping move for %s", ticket_id)
        return {"success": False, "new_ticket_id": None, "error": "Jira write disabled"}
    target = target_project_key or LOCALIZATION_PROJECT_KEY

    # ── Step 1: Fetch available move targets ──────────────────
    moves_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}/moves"
    try:
        r = _session.get(moves_url, timeout=15)
    except Exception as e:
        logger.error("Failed to fetch move options for %s: %s", ticket_id, e)
        return {"success": False, "new_ticket_id": None, "error": str(e)}

    if r.status_code not in (200, 201):
        # Fallback: try direct project field update (older Jira configs)
        return _move_via_field_update(ticket_id, target)

    move_options = r.json()
    # Find matching project in the returned options
    target_option = None
    for opt in move_options.get("moveToProjects", []):
        if opt.get("key", "").upper() == target.upper():
            target_option = opt
            break

    if not target_option:
        available = [o.get("key") for o in move_options.get("moveToProjects", [])]
        logger.warning(
            "Project '%s' not available as move target for %s. Available: %s",
            target, ticket_id, available,
        )
        # Fallback to field update
        return _move_via_field_update(ticket_id, target)

    # ── Step 2: Execute the move ──────────────────────────────
    payload = {
        "moveToProject": {"key": target},
        "issueIdOrKey":  ticket_id,
    }
    try:
        r2 = _session.post(moves_url, json=payload, timeout=20)
    except Exception as e:
        logger.error("Move POST failed for %s: %s", ticket_id, e)
        return {"success": False, "new_ticket_id": None, "error": str(e)}

    if r2.status_code in (200, 201, 204):
        body = r2.json() if r2.content else {}
        new_key = body.get("key") or body.get("id") or f"{target}-?"
        logger.info("Moved %s → %s (new key: %s)", ticket_id, target, new_key)
        return {"success": True, "new_ticket_id": new_key, "error": None}

    logger.error("HTTP %d moving %s → %s: %s",
                 r2.status_code, ticket_id, target, r2.text[:300])
    return {"success": False, "new_ticket_id": None,
            "error": f"HTTP {r2.status_code}: {r2.text[:200]}"}


def _move_via_field_update(ticket_id: str, target_project_key: str) -> dict:
    """
    Fallback: update the 'project' field directly via PUT.
    Works on some Jira Cloud configurations.
    """
    if not JIRA_WRITE_ENABLED:
        logger.warning("Jira write disabled: skipping field update move for %s", ticket_id)
        return {"success": False, "new_ticket_id": None, "error": "Jira write disabled"}
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}"
    payload = {"fields": {"project": {"key": target_project_key}}}
    try:
        r = _session.put(url, json=payload, timeout=15)
    except Exception as e:
        return {"success": False, "new_ticket_id": None, "error": str(e)}

    if r.status_code in (200, 204):
        logger.info("Moved %s → %s via field update", ticket_id, target_project_key)
        return {"success": True, "new_ticket_id": None, "error": None}

    logger.error("Fallback move failed %s → %s: HTTP %d — %s",
                 ticket_id, target_project_key, r.status_code, r.text[:200])
    return {"success": False, "new_ticket_id": None,
            "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def get_ticket_details(ticket_id: str) -> Optional[dict]:
    """
    Fetch and return the full detail dict for a single ticket.
    ticket_id examples: "FIZ-43429", "FIZ-42053"
    """
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}"
    params = {"fields": ",".join(ISSUE_FIELDS)}

    try:
        response = _session.get(url, params=params, timeout=20)
    except requests.exceptions.ConnectTimeout:
        raise ConnectionError("Timed out connecting to Jira. Check your VPN / network.")
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Cannot reach Jira: {e}")

    if response.status_code == 200:
        return _build_ticket(response.json())

    logger.error("HTTP %d fetching ticket '%s'", response.status_code, ticket_id)
    return None


def get_all_statuses() -> list[dict]:
    """
    Return every status available in the project.
    Useful for confirming the exact status name strings to use.
    """
    url    = f"{JIRA_BASE_URL}/rest/api/3/project/{PROJECT_KEY}/statuses"
    response = _session.get(url, timeout=20)
    if response.status_code == 200:
        result = []
        for issue_type in response.json():
            for s in issue_type.get("statuses", []):
                entry = {"name": s["name"], "id": s["id"], "category": s.get("statusCategory", {}).get("name")}
                if entry not in result:
                    result.append(entry)
        return result
    logger.error("Could not fetch statuses: HTTP %d", response.status_code)
    return []


def write_classification_to_jira(ticket_id: str, board: str, confidence: str, reason: str) -> bool:
    """
    Write the AI classification result back to a Jira ticket as a comment
    and optionally update a custom field (JIRA_AI_BOARD_FIELD_ID in .env).

    Always posts a comment (visible to the team).
    Also updates custom field if JIRA_AI_BOARD_FIELD_ID is set in .env.
    """
    if not JIRA_WRITE_ENABLED:
        logger.warning("Jira write disabled: skipping comment/field update for %s", ticket_id)
        return False

    def _text(t, bold=False):
        node = {"type": "text", "text": t}
        if bold:
            node["marks"] = [{"type": "strong"}]
        return node

    def _para(*nodes):
        return {"type": "paragraph", "content": list(nodes)}

    def _rule():
        return {"type": "rule"}

    confidence_label = confidence.capitalize()
    comment_body = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                _para(
                    _text(
                        f"Automated comment: AI triage has routed this issue to the "
                        f"Global Compliance and Localizations Support project (confidence: {confidence_label})."
                    )
                ),
                _para(_text("Reason", bold=True)),
                _para(_text(reason)),
            ],
        }
    }

    # ── post comment (uses JIRA_COMMENT_EMAIL account if configured) ──
    comment_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}/comment"
    r = _comment_session.post(comment_url, json=comment_body, timeout=20)
    if r.status_code not in (200, 201):
        logger.error("Failed to post comment on %s: HTTP %d — %s", ticket_id, r.status_code, r.text[:200])
        return False
    logger.info("Posted classification comment on %s (%s, %s)", ticket_id, board, confidence)

    # ── update custom field (optional) ────────────────────────
    field_id = os.getenv("JIRA_AI_BOARD_FIELD_ID", "").strip()
    if field_id:
        field_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}"
        payload   = {"fields": {field_id: board}}
        rf = _session.put(field_url, json=payload, timeout=20)
        if rf.status_code not in (200, 204):
            logger.warning("Could not update custom field %s on %s: HTTP %d", field_id, ticket_id, rf.status_code)
        else:
            logger.info("Updated custom field %s = %s on %s", field_id, board, ticket_id)

    return True


# ──────────────────────────────────────────────────────────────
# 4.  Pretty-print helper
# ──────────────────────────────────────────────────────────────

_SEP  = "─" * 68
_SEP2 = "═" * 68

def print_ticket(t: dict, show_full_description: bool = False) -> None:
    """Print a readable summary of one ticket dict to stdout."""
    desc = t.get("description", "") or ""
    desc_display = desc if show_full_description else (
        desc[:400] + " …" if len(desc) > 400 else desc
    )

    print(_SEP)
    print(f"  🎫  {t['ticket_id']}  |  CS Ref: {t['cs_ref'] or '—'}  |  {t['status']}")
    print(_SEP)
    print(f"  📝  Summary   : {t['summary']}")
    print(f"  🏷   Type      : {t['issue_type']}   Priority: {t['priority']}")
    print(f"  👤  Reporter  : {t['reporter']}")
    print(f"  👷  Assignee  : {t['assignee']}")
    print(f"  📅  Created   : {t['created']}")
    print(f"  🔄  Updated   : {t['updated']}")
    if t.get("sprint"):
        print(f"  🏃  Sprint    : {t['sprint']}")
    if t.get("labels"):
        print(f"  🏷   Labels   : {', '.join(t['labels'])}")
    print(f"\n  📄  Description:\n     {desc_display or '(empty)'}\n")
    if t["comments"]:
        print(f"  💬  Comments ({len(t['comments'])} shown, latest last):")
        for c in t["comments"]:
            body = c["body"][:200] + " …" if len(c["body"]) > 200 else c["body"]
            print(f"     [{c['created']}] {c['author']}: {body}")
    print()


# ──────────────────────────────────────────────────────────────
# 5.  CLI entry-point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch IFS / Jira ticket details for the categoriser."
    )
    parser.add_argument(
        "--status", "-s",
        default="To Do",
        help='Jira status column to fetch. Default: "To Do". '
             'Use "list-statuses" to see all available.',
    )
    parser.add_argument(
        "--ticket", "-t",
        default=None,
        help="Fetch a single ticket by ID, e.g. FIZ-43429",
    )
    parser.add_argument(
        "--max", "-m",
        type=int,
        default=100,
        help="Maximum number of tickets to retrieve (default 100).",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Dump raw JSON instead of pretty-print.",
    )
    parser.add_argument(
        "--list-statuses",
        action="store_true",
        help="List all statuses available in the project and exit.",
    )
    args = parser.parse_args()

    # ── list-statuses mode ─────────────────────────────────────
    if args.list_statuses:
        print(f"\nStatuses in project {PROJECT_KEY}:\n")
        for s in get_all_statuses():
            print(f"  • {s['name']:30s}  category={s['category']}  id={s['id']}")
        raise SystemExit(0)

    # ── single-ticket mode ─────────────────────────────────────
    if args.ticket:
        print(f"\nFetching ticket: {args.ticket}\n")
        t = get_ticket_details(args.ticket)
        if t:
            if args.json:
                print(json.dumps(t, indent=2, ensure_ascii=False))
            else:
                print_ticket(t, show_full_description=True)
        raise SystemExit(0)

    # ── list mode (default) ────────────────────────────────────
    print(f"\n{'='*68}")
    print(f"  IFS Jira Ticket Fetcher")
    print(f"  Project : {PROJECT_KEY}   Status filter: \"{args.status}\"")
    print(f"{'='*68}\n")

    tickets = get_tickets_by_status(status=args.status, max_results=args.max)

    if not tickets:
        print(f"\n  ⚠  No tickets found with status='{args.status}'.")
        raise SystemExit(0)

    if args.json:
        print(json.dumps(tickets, indent=2, ensure_ascii=False))
    else:
        print(f"\n  Showing {len(tickets)} ticket(s)\n")
        for t in tickets:
            print_ticket(t)

    print(_SEP2)
    print(f"  Total fetched: {len(tickets)}")
    print(_SEP2)
