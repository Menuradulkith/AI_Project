"""
agents/
───────
AI classification agents for the FIZ ticket classifier.

Public API:
  from agents import smart_classify
"""

from agents.router import smart_classify

__all__ = ["smart_classify"]
