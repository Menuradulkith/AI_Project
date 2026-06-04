"""
agents/chat.py
──────────────
Chat Agent — answers natural language questions about FIZ tickets.

Uses a simple tool-calling loop (no deprecated AgentExecutor):
  1. Send user message + history to LLM with tools bound
  2. If LLM returns tool_calls → execute them, send results back
  3. Repeat until LLM returns a plain text response (max 5 iterations)

Cost per message:
  Stats / counts query  : ~$0.0002  (1 LLM call)
  Tool-based query      : ~$0.0004  (2 LLM calls — decide + answer)
  Specific ticket lookup: ~$0.0005  (2 LLM calls + 1 Jira call)
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agents.base import get_llm
from agents.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 5      # 5 user + 5 assistant = 10 messages max
_MAX_TOOL_ROUNDS   = 5      # max tool call iterations per user message

_CHAT_SYSTEM = """You are a helpful assistant for the IFS Bumblebee team.
You help users query and understand Jira ticket classifications for the FIZ project.

System workflow (read + classify + store only):
    - Tickets are fetched from Jira and stored in SQLite (single source of truth)
    - The classifier assigns ONLY Localisation vs Not Localisation with a confidence level
    - Some tickets are flagged for manual review (needs_review)
    - Jira tickets are not modified by chat

Available tools and when to use them:
    get_stats                  → overall counts, Localisation/Not Localisation split, needs_review
    get_tickets_by_board       → list tickets for Localisation or Not Localisation
    get_gray_zone_tickets      → tickets flagged for manual review
    get_low_confidence_tickets → tickets the AI was least sure about
    get_recent_classifications → what was classified recently
    search_by_keyword          → find tickets by keyword in reason or signals
    get_confidence_breakdown   → high/medium/low confidence percentages
    get_ticket_detail          → ONLY for a specific ticket ID (e.g. FIZ-43429)
    classify_ticket            → classify a single ticket by ID (e.g. 'classify FIZ-43429')
    classify_batch_by_status   → classify multiple tickets from a status column (e.g. 'classify all To Do tickets')

Rules:
    - Always use a tool to get data — never invent ticket IDs or counts
    - Use get_ticket_detail only when the user gives a specific ticket ID
    - Keep answers short and clear — this is a dashboard sidebar chat
    - Show max 10 tickets in any list
    - Format ticket lists as a clean numbered list
    - If no data found, say so honestly
"""

# Build a name→function lookup for tool execution
_TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# LLM with tools bound — singleton
_llm_with_tools = None


def _get_llm_with_tools():
    """Return the LLM singleton with tools bound."""
    global _llm_with_tools
    if _llm_with_tools is None:
        llm = get_llm()
        _llm_with_tools = llm.bind_tools(ALL_TOOLS)
        logger.info("Chat LLM bound with %d tools", len(ALL_TOOLS))
    return _llm_with_tools


def chat(message: str, history: list[dict]) -> str:
    """
    Send a message to the chat agent and return the reply.

    Args:
        message: The user's current message
        history: List of { role: "user"|"assistant", content: "..." }

    Returns:
        Assistant reply as plain string
    """
    llm = _get_llm_with_tools()

    # Build message list: system + trimmed history + current message
    trimmed = history[-(_MAX_HISTORY_TURNS * 2):]
    messages: list = [SystemMessage(content=_CHAT_SYSTEM)]

    for msg in trimmed:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))

    logger.info("Chat: %.100s (history=%d)", message, len(trimmed))

    # Tool-calling loop
    for iteration in range(_MAX_TOOL_ROUNDS):
        response = llm.invoke(messages)
        messages.append(response)

        # If no tool calls → we have the final answer
        if not response.tool_calls:
            return response.content or "I couldn't generate a response."

        # Execute each tool call and feed results back
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_fn   = _TOOL_MAP.get(tool_name)

            if tool_fn is None:
                result = json.dumps({"error": f"Unknown tool: {tool_name}"})
                logger.warning("Chat: unknown tool %s", tool_name)
            else:
                try:
                    result = tool_fn.invoke(tool_args)
                    logger.info("Chat: tool %s → %d chars", tool_name, len(result))
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                    logger.error("Chat: tool %s error: %s", tool_name, e)

            messages.append(
                ToolMessage(content=result, tool_call_id=tc["id"])
            )

    # If we exhausted iterations, return whatever we have
    return response.content or "I ran out of steps trying to answer. Please try a simpler question."
