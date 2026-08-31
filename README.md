# Personal Budget Assistant — CSE476 CA1 (Topic T1)

An AI **agent** that helps a student track a monthly budget and answer money
questions. It runs a plan-act loop: it decides an action, calls a tool, reads the
result, and decides the next step, until it can answer. Run `demo.ipynb`
top-to-bottom to see the multi-step traces — it needs no API key.

## The two tools

- **`add_expense(item, amount)`** — records one expense in memory, auto-tags a
  category (food / transport / entertainment / shopping / bills / other), and
  returns the updated category total, session total, and remaining balance.
- **`get_summary(category)`** — reports spending for the session: total spent, the
  per-category breakdown, the budget, and the balance. Pass `"all"` or a single
  category. The agent calls this before answering any "how much / what's left /
  can I afford X" question.

The agent only ever touches the data through these two functions — it never
writes totals itself. The loop has two lanes behind one implementation:
`mode="rule"` (deterministic planner, used by the notebook) and `mode="llm"`
(an LLM on GitHub Models does the deciding via function-calling, if `GITHUB_TOKEN`
is set). `mode="auto"` picks automatically.

## What the memory does

`Memory` holds two things for the whole conversation: the **turn history** (every
user and agent message) and a **structured store** (the list of expenses, each
with its category, plus the monthly budget). The structured store is what keeps
category totals correct as expenses pile up across many turns, and it is what a
*later* turn reads back: when the user asks "can I afford a 2000 trip?" in turn 3,
the agent uses the budget stated in turn 1 and the expenses logged in turns 1–2,
computes `balance − 2000`, and decides yes/no. If no budget is in memory yet, the
agent notices that in the `get_summary` result and asks for it instead of
guessing.

## One honest failure

The natural-language expense parser was the hard part. Given
*"Also paid 1200 for groceries and a movie cost 300"*, the first version pulled
out an expense whose item was the whole phrase *"for groceries and a movie"* —
a second regex for the *"X cost N"* pattern overlapped the first regex's match and
swallowed the connective words. The fix was three small rules: strip leading
articles (`a`, `an`, `the`, `my`), cap the *"X cost N"* item to at most three
words with no `and`/`also` inside it, and de-duplicate two matches that share the
same amount and overlap textually (keeping the shorter, cleaner item). It now
splits that sentence into `groceries → 1200` and `movie → 300` correctly. It is
still a heuristic, not a real parser — very unusual phrasings can still be
missed — but every example in the demo notebook parses correctly.

## How to run

```bash
pip install -r requirements.txt        # only needed for the optional LLM lane
jupyter nbconvert --to notebook --execute --inplace demo.ipynb   # or open in Jupyter
```

Programmatic use:

```python
from budget_agent import Agent
agent = Agent(mode="rule")                     # one instance = one conversation
agent.run("My budget is 15000. Spent 250 on lunch and 400 on a cab.")
print(agent.run("Can I afford a 2000 trip?").answer)
```
