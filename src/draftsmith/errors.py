"""Shared error types.

Kept dependency-free so the scene model, DSL and geometry modules do not
have to import the (heavy) rendering stack.
"""


class ToolError(ValueError):
    """Raised for invalid operations; the message is written as agent feedback."""
