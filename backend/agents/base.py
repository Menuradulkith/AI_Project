"""
agents/base.py
──────────────
Shared foundation for all agents.

- LLM singleton   — created once on startup, reused for every call
- Retry logic     — exponential backoff, up to 3 attempts
- Hard timeout    — 30 s per LLM call so Flask workers never hang
- Prompt building — truncated to control token cost
- JSON extraction — validated with safe fallback

No circular imports:
  categorizer.py does NOT import from here.
  agents/* import from here only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sanitizer import sanitize_ticket, sanitize_text

load_dotenv()
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
_PROMPT_PATH           = Path(__file__).parent.parent / "prompts" / "system_prompt.md"
_MODEL                 = "gpt-4o-mini"
_LLM_TIMEOUT           = 30      # seconds — hard timeout per call
_MAX_RETRIES           = 3
_RETRY_BASE_BACKOFF    = 2       # seconds, doubles each retry: 2 → 4 → 8

_MAX_SUMMARY_CHARS     = 200
_MAX_DESCRIPTION_CHARS = 1500
_MAX_COMMENT_CHARS     = 300
_MAX_COMMENTS          = 3       # only send the 3 most recent comments

# Approximate cost logging (gpt-4o-mini as of 2025)
_COST_PER_1K_IN  = 0.000150
_COST_PER_1K_OUT = 0.000600


# ── LLM Singleton ──────────────────────────────────────────────────────────────
# Created ONCE when the module first loads — never recreated per ticket.
_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    """Return the shared LLM singleton. Initialised on first call."""
    global _llm
    if _llm is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file: OPENAI_API_KEY=sk-..."
            )
        _llm = ChatOpenAI(
            model=_MODEL,
            temperature=0,
            api_key=api_key,
            timeout=_LLM_TIMEOUT,
            max_retries=0,       # we handle retries ourselves with backoff below
        )
        logger.info("LLM singleton created  model=%s  timeout=%ds", _MODEL, _LLM_TIMEOUT)
    return _llm


# ── System Prompt Cache ────────────────────────────────────────────────────────
# Read from disk once, kept in memory for the lifetime of the process.
_system_prompt_cache: str | None = None


def get_system_prompt() -> str:
    """Load the system prompt once and keep it in memory."""
    global _system_prompt_cache
    if _system_prompt_cache is None:
        if not _PROMPT_PATH.exists():
            raise FileNotFoundError(
                f"System prompt not found: {_PROMPT_PATH}\n"
                "Make sure prompts/system_prompt.md exists."
            )
        _system_prompt_cache = _PROMPT_PATH.read_text(encoding="utf-8").strip()
        logger.info("System prompt loaded  %d chars", len(_system_prompt_cache))
    return _system_prompt_cache


# ── Prompt Builder ─────────────────────────────────────────────────────────────
def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= max_chars else text[:max_chars] + "… [truncated]"


def build_classify_prompt(ticket: dict) -> str:
    """
    Build the human prompt for a ticket.
    Truncated so every ticket costs roughly the same number of tokens.
    PII / sensitive data is stripped before the prompt is sent to the LLM.
    """
    # ── Sanitize PII before building prompt ───────────────────
    safe = sanitize_ticket(ticket)

    summary  = _truncate(safe.get("summary",     ""), _MAX_SUMMARY_CHARS)
    desc     = _truncate(safe.get("description", ""), _MAX_DESCRIPTION_CHARS)
    cs_ref   = safe.get("cs_ref") or "N/A"
    tid      = safe.get("ticket_id", "UNKNOWN")

    recent_comments = (safe.get("comments") or [])[-_MAX_COMMENTS:]
    comment_lines = [
        f"  • [{c.get('author','?')}]: {_truncate(c.get('body',''), _MAX_COMMENT_CHARS)}"
        for c in recent_comments
        if c.get("body", "").strip()
    ]
    comments_block = "\n".join(comment_lines) if comment_lines else "  (none)"

    return (
        f"TICKET ID  : {tid}\n"
        f"CS REF     : {cs_ref}\n"
        f"SUMMARY    : {summary}\n"
        f"DESCRIPTION:\n{desc}\n\n"
        f"RECENT COMMENTS:\n{comments_block}"
    )


# ── LLM Call with Retry + Backoff ──────────────────────────────────────────────
def call_llm(messages: list, ticket_id: str = "?") -> str:
    """
    Invoke the LLM with automatic retry and exponential backoff.

    Args:
        messages:  List of SystemMessage / HumanMessage
        ticket_id: Used only for log messages

    Returns:
        Raw string content from the model

    Raises:
        RuntimeError: if all retries are exhausted
    """
    llm     = get_llm()
    backoff = _RETRY_BASE_BACKOFF

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = llm.invoke(messages)
            content  = response.content if hasattr(response, "content") else str(response)

            # Log token usage + estimated cost if the SDK provides it
            usage = getattr(response, "usage_metadata", None)
            if usage:
                in_tok  = usage.get("input_tokens",  0)
                out_tok = usage.get("output_tokens", 0)
                cost    = (in_tok / 1000 * _COST_PER_1K_IN) + (out_tok / 1000 * _COST_PER_1K_OUT)
                logger.info(
                    "LLM call  ticket=%s  in=%d  out=%d  cost=$%.6f",
                    ticket_id, in_tok, out_tok, cost,
                )

            return content

        except Exception as exc:
            if attempt == _MAX_RETRIES:
                logger.error(
                    "LLM call failed for %s after %d attempts: %s",
                    ticket_id, _MAX_RETRIES, exc,
                )
                raise RuntimeError(
                    f"LLM unavailable after {_MAX_RETRIES} retries: {exc}"
                ) from exc

            logger.warning(
                "LLM attempt %d/%d failed for %s (%s) — retrying in %ds",
                attempt, _MAX_RETRIES, ticket_id, exc, backoff,
            )
            time.sleep(backoff)
            backoff *= 2  # 2s → 4s → 8s


# ── JSON Extraction + Validation ───────────────────────────────────────────────
def extract_json(raw: str, ticket_id: str = "?") -> dict[str, Any]:
    """
    Extract and validate the JSON classification object from LLM output.
    Returns a safe fallback (gray_zone=True, confidence=low) if parsing fails
    so the pipeline never crashes on a bad LLM response.
    """
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned)

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in response")

        data  = json.loads(match.group())
        board = data.get("board", "")

        if board.lower() in ("localisation", "localization"):
            board = "Localisation"
        elif board.lower() in ("not localisation", "not localization", "finance", "other"):
            board = "Not Localisation"
        else:
            raise ValueError(f"Unexpected board value: {board!r}")

        return {
            "board":      board,
            "confidence": data.get("confidence", "low"),
            "reason":     data.get("reason",     ""),
            "signals":    data.get("signals",    []),
            "gray_zone":  bool(data.get("gray_zone", False)),
        }

    except Exception as exc:
        logger.error(
            "JSON parse failed for %s: %s | raw=%.300s",
            ticket_id, exc, raw,
        )
        # Safe fallback — flag for human review rather than silently misclassify
        return {
            "board":      "Not Localisation",
            "confidence": "low",
            "reason":     f"Parse error — needs manual review ({exc})",
            "signals":    [],
            "gray_zone":  True,
        }
