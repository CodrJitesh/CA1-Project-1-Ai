"""Conversation memory for the Personal Budget Assistant agent.

Two kinds of memory live here:

1. Turn history  - every user/agent message in the session, so the agent can
   look back at what was said earlier ("earlier you told me your budget is X").
2. Structured store - the running list of expenses and the monthly budget.
   This is what makes category totals stay correct across many turns and what
   lets a *later* answer ("can I afford a 2000 trip?") use facts from an
   *earlier* turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Keyword -> category. Deliberately tiny and readable; good enough for a demo.
_CATEGORY_KEYWORDS = {
    "food": ["food", "lunch", "dinner", "breakfast", "grocery", "groceries",
             "snack", "coffee", "restaurant", "pizza", "meal", "canteen"],
    "transport": ["uber", "ola", "cab", "taxi", "bus", "train", "metro", "fuel",
                  "petrol", "diesel", "auto", "flight", "ticket"],
    "entertainment": ["movie", "netflix", "spotify", "game", "concert", "party",
                      "subscription"],
    "shopping": ["shirt", "shoes", "clothes", "amazon", "flipkart", "book",
                 "headphones", "gadget", "phone"],
    "bills": ["rent", "electricity", "water", "wifi", "internet", "phone bill",
              "recharge", "gas"],
}


def categorise(item: str) -> str:
    """Best-effort category from the item text. Falls back to 'other'."""
    text = item.lower()
    for category, words in _CATEGORY_KEYWORDS.items():
        if any(word in text for word in words):
            return category
    return "other"


@dataclass
class Expense:
    item: str
    amount: float
    category: str


@dataclass
class Memory:
    turns: list[dict] = field(default_factory=list)
    expenses: list[Expense] = field(default_factory=list)
    monthly_budget: float | None = None

    # ---- turn history -----------------------------------------------------
    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})

    def recent_turns(self, n: int = 6) -> list[dict]:
        return self.turns[-n:]

    # ---- structured store ----------------------------------------------
    def record_expense(self, item: str, amount: float, category: str) -> None:
        self.expenses.append(Expense(item=item, amount=float(amount),
                                     category=category))

    def total_spent(self, category: str = "all") -> float:
        if category in ("all", "", None):
            return sum(e.amount for e in self.expenses)
        return sum(e.amount for e in self.expenses
                   if e.category == category.lower())

    def category_breakdown(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.expenses:
            out[e.category] = out.get(e.category, 0.0) + e.amount
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def balance(self) -> float | None:
        if self.monthly_budget is None:
            return None
        return self.monthly_budget - self.total_spent("all")

    def snapshot(self) -> str:
        """Short human-readable state, handy for prompts and debugging."""
        parts = [f"budget={self.monthly_budget}",
                 f"spent={self.total_spent('all'):.0f}",
                 f"n_expenses={len(self.expenses)}"]
        bd = self.category_breakdown()
        if bd:
            parts.append("by_category=" +
                         ", ".join(f"{k}:{v:.0f}" for k, v in bd.items()))
        return " | ".join(parts)
