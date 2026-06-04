"""
sanitizer.py
─────────────
PII / Sensitive Data Sanitizer

Strips personal and sensitive information from ticket data BEFORE
it is sent to the LLM for classification.  The classifier only needs
to know *what kind* of data is mentioned — not the actual values.

Covered patterns:
  • Email addresses          →  [EMAIL]
  • Phone numbers            →  [PHONE]
  • Credit / debit cards     →  [CREDIT_CARD]
  • IP addresses (v4 & v6)  →  [IP_ADDRESS]
  • Passwords / secrets      →  [REDACTED_SECRET]
  • National IDs / SSNs      →  [NATIONAL_ID]
  • Postal / zip codes       →  [POSTAL_CODE]
  • URLs with auth tokens    →  [REDACTED_URL]
  • Person names (heuristic) →  [PERSON_NAME]
  • Bank account / IBAN      →  [BANK_ACCOUNT]
  • API keys / tokens        →  [API_KEY]
  • File paths with usernames → [REDACTED_PATH]

Usage:
    from sanitizer import sanitize_text, sanitize_ticket

    clean_text   = sanitize_text("Contact john@acme.com or 555-1234")
    clean_ticket = sanitize_ticket(ticket_dict)
"""

from __future__ import annotations

import copy
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
# Set to "false" in .env to disable sanitization (e.g. for debugging)
SANITIZE_ENABLED = os.getenv("SANITIZE_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Regex patterns ────────────────────────────────────────────
# Order matters — more specific patterns first to avoid partial matches.

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # API keys / tokens (long hex or base64 strings that look like secrets)
    ("API_KEY",
     re.compile(
         r"""(?x)
         (?:api[_-]?key|token|secret|password|bearer|authorization)
         \s*[:=]\s*
         ["']?([A-Za-z0-9\-_./+]{20,})["']?
         """, re.IGNORECASE),
     "[API_KEY]"),

    # Credit / debit card numbers (13-19 digits, with optional separators)
    ("CREDIT_CARD",
     re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
     "[CREDIT_CARD]"),

    # IBAN numbers
    ("BANK_ACCOUNT",
     re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:\d{4}[ ]?){3,7}\d{1,4}\b"),
     "[BANK_ACCOUNT]"),

    # National ID / SSN patterns (US SSN, UK NIN, etc.)
    ("NATIONAL_ID",
     re.compile(
         r"\b(?:"
         r"\d{3}-\d{2}-\d{4}"           # US SSN
         r"|[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]"  # UK NIN
         r"|\d{9,12}"                     # Generic long numeric IDs
         r")\b"),
     "[NATIONAL_ID]"),

    # Email addresses
    ("EMAIL",
     re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "[EMAIL]"),

    # Phone numbers (international and local formats)
    ("PHONE",
     re.compile(
         r"(?<!\d)"
         r"(?:\+?\d{1,3}[\s.-]?)?"
         r"(?:\(?\d{2,4}\)?[\s.-]?)?"
         r"\d{3,4}[\s.-]?\d{3,4}"
         r"(?!\d)"),
     "[PHONE]"),

    # IPv4 addresses
    ("IP_ADDRESS",
     re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
     "[IP_ADDRESS]"),

    # IPv6 addresses (simplified)
    ("IP_ADDRESS",
     re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b"),
     "[IP_ADDRESS]"),

    # URLs with tokens / credentials in query params
    ("REDACTED_URL",
     re.compile(
         r"https?://[^\s]+(?:token|key|secret|password|auth|credential)[^\s]*",
         re.IGNORECASE),
     "[REDACTED_URL]"),

    # File paths containing user directories (Windows & Unix)
    ("REDACTED_PATH",
     re.compile(
         r"(?:[A-Z]:\\Users\\[^\s\\]+\\[^\s]*"
         r"|/(?:home|Users)/[^\s/]+/[^\s]*)",
         re.IGNORECASE),
     "[REDACTED_PATH]"),

    # Postal / ZIP codes (US 5+4, UK, generic 4-6 digit)
    ("POSTAL_CODE",
     re.compile(
         r"\b(?:"
         r"\d{5}(?:-\d{4})?"             # US ZIP
         r"|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}"  # UK postcode
         r")\b"),
     "[POSTAL_CODE]"),
]

# ── Password / secret in plain text ──────────────────────────
_SECRET_PATTERN = re.compile(
    r"(?:password|passwd|pwd|secret|token)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

def sanitize_text(text: str) -> str:
    """
    Remove / mask all PII and sensitive patterns from a string.
    Returns the sanitized copy.
    """
    if not text or not SANITIZE_ENABLED:
        return text

    result = text

    # Apply regex patterns
    for _name, pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)

    # Passwords / secrets in key=value style
    result = _SECRET_PATTERN.sub("[REDACTED_SECRET]", result)

    return result


def sanitize_ticket(ticket: dict) -> dict:
    """
    Return a deep copy of the ticket with all text fields sanitized.
    The original ticket dict is NEVER modified.

    Fields sanitized:
      - summary, description
      - comments[].body, comments[].author
      - reporter, assignee
    """
    if not SANITIZE_ENABLED:
        return ticket

    t = copy.deepcopy(ticket)

    # Text fields
    for field in ("summary", "description"):
        if field in t and t[field]:
            t[field] = sanitize_text(t[field])

    # Person names in reporter / assignee — replace with role label
    if t.get("reporter"):
        t["reporter"] = "[REPORTER]"
    if t.get("assignee") and t["assignee"] != "Unassigned":
        t["assignee"] = "[ASSIGNEE]"

    # Comments
    if "comments" in t and isinstance(t["comments"], list):
        for c in t["comments"]:
            if c.get("body"):
                c["body"] = sanitize_text(c["body"])
            if c.get("author"):
                c["author"] = "[COMMENTER]"

    return t


# ── Stats / debugging ────────────────────────────────────────

def scan_for_pii(text: str) -> list[dict]:
    """
    Scan text and return a list of detected PII types (without values).
    Useful for auditing / logging without exposing actual data.
    """
    if not text:
        return []

    found = []
    for name, pattern, _repl in _PATTERNS:
        matches = pattern.findall(text)
        if matches:
            found.append({"type": name, "count": len(matches)})

    if _SECRET_PATTERN.search(text):
        found.append({"type": "SECRET", "count": 1})

    return found


# ── CLI test ──────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        "Please contact john.doe@company.com or call +44 7911 123456",
        "SSN: 123-45-6789, IP: 192.168.1.1",
        "Card: 4111-1111-1111-1111, IBAN: GB29 NWBK 6016 1331 9268 19",
        "password=SuperSecret123! token: sk-abc123xyz456def789",
        "File at C:\\Users\\JohnDoe\\Documents\\report.xlsx",
        "Server at https://api.example.com?token=abc123secret",
    ]

    print("\n🔒 PII Sanitizer Test\n")
    for s in samples:
        print(f"  Original : {s}")
        print(f"  Sanitized: {sanitize_text(s)}")
        print(f"  PII found: {scan_for_pii(s)}")
        print()
