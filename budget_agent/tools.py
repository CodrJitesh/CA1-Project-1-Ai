"""The two tools the agent can call.

Both are plain Python functions that read/write the shared Memory object. The
agent never touches Memory directly during a task - it only gets there through
these tools, which is what "it calls tools, not just generates text" means.

    add_expense(item, amount)   -> records one expense, returns the new totals
    get_summary(category)       -> reports spending (optionally for one category)

Each tool also has an OpenAI-style JSON schema (TOOL_SCHEMAS) so the LLM lane
can do real function-calling. The offline lane calls the same functions.
"""

from __future__ import annotations

from .memory import Memory, categorise


def add_expense(memory: Memory, item: str, amount: float) -> dict:
    """Record a single expense and return the updated totals."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"amount {amount!r} is not a number"}
    if amount <= 0:
        return {"ok": False, "error": "amount must be positive"}

    category = categorise(item)
    memory.record_expense(item, amount, category)
    return {
        "ok": True,
        "recorded": {"item": item, "amount": amount, "category": category},
        "category_total": memory.total_spent(category),
        "total_spent": memory.total_spent("all"),
        "balance": memory.balance(),  # None if no budget set yet
    }


def get_summary(memory: Memory, category: str = "all") -> dict:
    """Return spending totals, optionally narrowed to one category."""
    category = (category or "all").lower()
    if not memory.expenses:
        return {"ok": True, "empty": True, "message": "no expenses logged yet",
                "budget": memory.monthly_budget}

    result = {
        "ok": True,
        "scope": category,
        "total_spent": memory.total_spent("all"),
        "budget": memory.monthly_budget,
        "balance": memory.balance(),
        "by_category": memory.category_breakdown(),
    }
    if category != "all":
        result["category_total"] = memory.total_spent(category)
        result["count_in_category"] = sum(
            1 for e in memory.expenses if e.category == category
        )
    return result


# ---------------------------------------------------------------------------
# Registry + schemas
# ---------------------------------------------------------------------------

TOOLS = {
    "add_expense": add_expense,
    "get_summary": get_summary,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Record one expense the user made. Use this whenever "
                           "the user mentions spending/paying money on something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string",
                             "description": "what the money was spent on"},
                    "amount": {"type": "number",
                               "description": "amount spent, a positive number"},
                },
                "required": ["item", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": "Get spending totals for the session. Pass a category "
                           "(food, transport, entertainment, shopping, bills, "
                           "other) or 'all'. Use before answering questions "
                           "about balance, totals, or affordability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "description": "category name or 'all'"},
                },
                "required": ["category"],
            },
        },
    },
]
