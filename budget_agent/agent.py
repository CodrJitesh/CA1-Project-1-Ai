"""Personal Budget Assistant - a small agent with a plan-act loop.

The agent takes a goal in natural language and then loops:

    decide next action  ->  call a tool  ->  read the result  ->  decide again

It stops when it has enough to answer. Every step is written to a `trace` so a
notebook can show that real tool calls happened (proof it is an agent, not a
chatbot).

Two lanes, same loop:
  * "llm"  - an LLM does the deciding via function-calling. The provider is
             resolved by budget_agent.lanes (same setup as the cse476-agentic-ai
             course repo): PROVIDER in .env, default Groq.
  * "rule" - a deterministic planner does the deciding. No API key needed, so
             the demo notebook always runs.
`mode="auto"` uses the LLM when a lane is configured (e.g. GROQ_API_KEY set),
otherwise it falls back to the rule planner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .memory import Memory
from .tools import TOOLS, TOOL_SCHEMAS


@dataclass
class Result:
    answer: str
    trace: list[dict] = field(default_factory=list)

    def show_trace(self) -> None:
        """Pretty-print the multi-step trace for the notebook demo."""
        for entry in self.trace:
            step = entry["step"]
            if entry["action"] == "memory":
                print(f"[step {step}] MEMORY  {entry['observation']}")
            elif entry["action"] == "final":
                print(f"[step {step}] ANSWER  {entry['thought']}")
            else:
                print(f"[step {step}] THINK   {entry['thought']}")
                print(f"          ACT     {entry['action']}({entry['action_input']})")
                print(f"          OBS     {entry['observation']}")
        print("-" * 70)


# ---------------------------------------------------------------------------
# Text parsing helpers (shared by the rule planner and budget ingestion)
# ---------------------------------------------------------------------------

_NUM = r"(\d[\d,]*(?:\.\d+)?)"


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _find_budget(text: str) -> float | None:
    m = re.search(rf"budget\s*(?:is|of|=|:)?\s*(?:rs\.?|inr|\$)?\s*{_NUM}",
                  text, re.I)
    if not m:
        m = re.search(rf"(?:i (?:have|get|earn|make))\s*(?:rs\.?|inr|\$)?\s*"
                      rf"{_NUM}\s*(?:per month|a month|monthly|/month)", text, re.I)
    return _to_float(m.group(1)) if m else None


_ARTICLES = ("a ", "an ", "the ", "some ", "my ")


def _clean_item(item: str) -> str:
    item = item.strip(" .,;").lower()
    for art in _ARTICLES:
        if item.startswith(art):
            item = item[len(art):]
    return item.strip()


def _find_expenses(text: str) -> list[tuple[str, float]]:
    """Pull (item, amount) pairs out of free text. Handles 'spent 200 on cab',
    'paid 90 for coffee', 'coffee cost 90', and 'and'/'then' lists."""
    found: list[tuple[str, float]] = []

    def add(item: str, amount: float) -> None:
        item = _clean_item(item)
        if not item:
            return
        for i, (fi, fa) in enumerate(found):
            if fa == amount and (fi in item or item in fi):  # same expense, better text
                if len(item) < len(fi):
                    found[i] = (item, amount)
                return
        found.append((item, amount))

    # "<amount> on/for <item>"  (item stops at a connective or punctuation)
    for m in re.finditer(rf"{_NUM}\s*(?:rs\.?|inr|\$|rupees)?\s*(?:on|for)\s+"
                         rf"([a-z][a-z \-]*?)(?=,|\.|;| and | then | also |$)",
                         text, re.I):
        add(m.group(2), _to_float(m.group(1)))

    # "<item> cost/costs/was <amount>"  (item = up to 3 words, no connectives)
    for m in re.finditer(rf"(?:^|\b(?:a|an|the|and|also)\s+)"
                         rf"([a-z][a-z\-]+(?:\s[a-z\-]+){{0,2}}?)\s*"
                         rf"(?:cost|costs|was)\s*(?:rs\.?|inr|\$)?\s*{_NUM}",
                         text, re.I):
        add(m.group(1), _to_float(m.group(2)))

    return found


def _find_afford_amount(text: str) -> float | None:
    m = re.search(rf"afford\s*(?:a|an|the)?\s*(?:rs\.?|inr|\$)?\s*{_NUM}",
                  text, re.I)
    return _to_float(m.group(1)) if m else None


def _wants_summary(text: str) -> bool:
    return bool(re.search(r"summary|how much|total|breakdown|where did|"
                          r"left|balance|remaining|spent so far", text, re.I))


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a personal budget assistant. You help a student track a monthly "
    "budget. Record every expense the user mentions with add_expense. Before "
    "answering ANY question about totals, balance, or whether they can afford "
    "something, you MUST call get_summary first and base your answer on its "
    "numbers - do not answer from the memory line alone, even if you think you "
    "know the figure. Think step by step: call a tool, read its result, then "
    "decide the next step. Keep answers short and concrete."
)


class Agent:
    def __init__(self, mode: str = "auto", max_steps: int = 6,
                 memory: Memory | None = None):
        self.memory = memory or Memory()
        self.max_steps = max_steps
        self.mode = self._resolve_mode(mode)

    @staticmethod
    def _resolve_mode(mode: str) -> str:
        if mode != "auto":
            return mode
        try:
            from .lanes import get_client
            get_client()  # raises LaneError if no lane is configured
            return "llm"
        except Exception:
            return "rule"

    # -- public ---------------------------------------------------------
    def run(self, goal: str) -> Result:
        self.memory.add_turn("user", goal)
        trace: list[dict] = []
        step = 0

        # Memory write: pick up a stated budget before planning. This is memory,
        # not a tool - it is what a later turn will read back.
        budget = _find_budget(goal)
        if budget is not None and self.memory.monthly_budget != budget:
            self.memory.monthly_budget = budget
            step += 1
            trace.append({"step": step, "action": "memory",
                          "observation": f"stored monthly_budget = {budget:.0f}"})

        if self.mode == "llm":
            answer = self._run_llm(goal, trace, step)
        else:
            answer = self._run_rule(goal, trace, step)

        self.memory.add_turn("agent", answer)
        return Result(answer=answer, trace=trace)

    # -- rule lane ----------------------------------------------------
    def _run_rule(self, goal: str, trace: list[dict], step: int) -> str:
        # Build the plan from the goal, then execute it one step per loop,
        # deciding the next step from what the tools returned.
        todo_expenses = _find_expenses(goal)
        afford_amt = _find_afford_amount(goal)
        need_summary = afford_amt is not None or _wants_summary(goal)

        issued_expenses = 0
        summary_obs: dict | None = None

        while step < self.max_steps:
            # 1) log any expenses that are still pending
            if issued_expenses < len(todo_expenses):
                item, amount = todo_expenses[issued_expenses]
                issued_expenses += 1
                step += 1
                thought = f"user mentioned spending {amount:.0f} on {item}; log it"
                obs = TOOLS["add_expense"](self.memory, item=item, amount=amount)
                trace.append({"step": step, "action": "add_expense",
                              "thought": thought,
                              "action_input": {"item": item, "amount": amount},
                              "observation": obs})
                continue

            # 2) if the question needs totals, look them up once
            if need_summary and summary_obs is None:
                step += 1
                thought = ("need current totals to answer; call get_summary"
                           if afford_amt is None else
                           f"to judge a {afford_amt:.0f} spend I need the balance")
                summary_obs = TOOLS["get_summary"](self.memory, category="all")
                trace.append({"step": step, "action": "get_summary",
                              "thought": thought,
                              "action_input": {"category": "all"},
                              "observation": summary_obs})
                continue

            # 3) nothing left to gather -> decide the final answer
            break

        answer = self._compose_rule_answer(goal, todo_expenses, afford_amt,
                                           need_summary, summary_obs)
        step += 1
        trace.append({"step": step, "action": "final", "thought": answer})
        return answer

    def _compose_rule_answer(self, goal, todo_expenses, afford_amt,
                             need_summary, summary_obs) -> str:
        mem = self.memory

        # Affordability: decide from the balance the tool just gave back.
        if afford_amt is not None:
            if summary_obs and summary_obs.get("balance") is None:
                return ("You've spent {:.0f} so far, but I don't know your "
                        "monthly budget yet - tell me that and I'll say whether "
                        "{:.0f} fits.".format(mem.total_spent('all'), afford_amt))
            balance = summary_obs["balance"]
            after = balance - afford_amt
            if after >= 0:
                return ("Yes. Budget {:.0f}, spent {:.0f}, so {:.0f} is left. "
                        "A {:.0f} spend leaves {:.0f}."
                        .format(mem.monthly_budget, mem.total_spent('all'),
                                balance, afford_amt, after))
            return ("No. Only {:.0f} is left ({:.0f} budget - {:.0f} spent), "
                    "so a {:.0f} spend would put you {:.0f} over."
                    .format(balance, mem.monthly_budget, mem.total_spent('all'),
                            afford_amt, -after))

        # Summary question.
        if need_summary:
            if not mem.expenses:
                return "No expenses logged yet this session."
            bd = ", ".join(f"{k} {v:.0f}" for k, v in
                           mem.category_breakdown().items())
            line = f"Spent {mem.total_spent('all'):.0f} so far ({bd})."
            if mem.balance() is not None:
                line += f" Balance: {mem.balance():.0f} of {mem.monthly_budget:.0f}."
            return line

        # Pure logging turn.
        if todo_expenses:
            n = len(todo_expenses)
            return ("Logged {} expense{} ({:.0f} total this session)."
                    .format(n, "" if n == 1 else "s", mem.total_spent('all')))

        return ("I can log expenses and summarise your spending. Try: "
                "'spent 250 on lunch' or 'can I afford a 2000 trip?'.")

    # -- llm lane ---------------------------------------------------
    def _run_llm(self, goal: str, trace: list[dict], step: int) -> str:
        import json

        from .lanes import get_client, get_model

        client = get_client()
        model = get_model()

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for t in self.memory.recent_turns(8)[:-1]:  # prior context, not this goal
            messages.append({"role": "user" if t["role"] == "user"
                             else "assistant", "content": t["content"]})
        messages.append({"role": "user",
                         "content": f"{goal}\n\n(memory: {self.memory.snapshot()})"})

        while step < self.max_steps:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=TOOL_SCHEMAS,
                tool_choice="auto", temperature=0)
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                answer = msg.content or ""
                step += 1
                trace.append({"step": step, "action": "final",
                              "thought": answer})
                return answer

            for call in msg.tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments or "{}")
                step += 1
                obs = TOOLS[name](self.memory, **args)
                trace.append({"step": step, "action": name,
                              "thought": msg.content or "(tool call)",
                              "action_input": args, "observation": obs})
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(obs, default=str)})

        # Ran out of steps - ask the model for a final answer with no tools.
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0)
        answer = resp.choices[0].message.content or ""
        step += 1
        trace.append({"step": step, "action": "final", "thought": answer})
        return answer
