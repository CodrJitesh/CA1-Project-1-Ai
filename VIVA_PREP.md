# Viva Prep — Personal Budget Assistant (CSE476 CA1, Topic T1)

Everything here maps to real code in this repo. Line numbers are from the files
as committed.

---

## 1. 30-second pitch

> "It's an agent that helps a student track a monthly budget. It has **two
> tools** — `add_expense` and `get_summary` — and a **plan-act loop** that calls
> a tool, reads the result, and decides the next step. It keeps **memory** for
> the whole conversation: the running list of expenses and the monthly budget.
> So when you ask 'can I afford a 2000 trip?' three turns later, it looks up the
> balance with `get_summary`, subtracts 2000, and decides yes or no. There are
> two lanes behind the same loop — a deterministic planner (no API key, used in
> the notebook) and an LLM lane that uses Groq function-calling."

---

## 2. Full feature list

**Core (required by the rubric)**
- One agent with a **plan-act loop** that takes several steps (`agent.py:207`
  `while step < self.max_steps`).
- **Two tools** the agent calls: `add_expense(item, amount)`, `get_summary(category)`
  (`tools.py:19`, `tools.py:40`).
- **Conversation memory**: turn history + structured store of expenses and budget
  (`memory.py`), read back in a later turn.
- **Multi-step trace**: every step (THINK / ACT / OBS / MEMORY / ANSWER) is
  recorded and printable (`Result.show_trace`, `agent.py:35`).

**Agent behaviours**
- **Auto-categorisation** of each expense (food / transport / entertainment /
  shopping / bills / other) by keyword (`memory.py:_CATEGORY_KEYWORDS`,
  `categorise()`).
- **Affordability decision** — reads `balance` from the `get_summary` result,
  computes `balance - amount`, answers yes/no with the numbers (`agent.py:248`).
- **Decides from a tool result**: if `get_summary` comes back with `balance =
  None` (no budget known), the agent asks for the budget instead of guessing
  (`agent.py:249`).
- **Budget ingestion into memory** before planning; a budget-only turn confirms
  it (`agent.py:177`, `agent.py:286`).
- **Multi-expense in one message**: "900 on groceries, 600 on petrol and 250 on
  coffee" → three separate `add_expense` calls, three steps.
- **Category breakdown / summary** on request ("where did my money go?").
- `max_steps` guard (default 6) so the loop always terminates.

**Two lanes, one loop**
- `mode="rule"` — deterministic planner, standard library only.
- `mode="llm"` — an LLM does the deciding via OpenAI-style **function-calling**.
- `mode="auto"` — LLM if a provider is configured in `.env`, else rule
  (`agent.py:158`).
- Provider resolved by `lanes.py` (same design as the `cse476-agentic-ai` course
  repo): `PROVIDER` in `.env`, default **Groq**, model `openai/gpt-oss-20b`.
  Lanes also defined: `local` (Ollama), `foundry` (Azure); `github` marked
  retired.

**Presentation / demo**
- `demo.ipynb` — runs 3 example conversations end-to-end with full traces,
  executed and committed with outputs. Also runs the live Groq lane.
- `frontend/` — a standard-library web app (`server.py` + `index.html`): chat on
  the left with an expandable trace under each answer, a live memory panel on the
  right, and one-click **seed conversations**.
- `budget_agent/seeds.py` — four canned scenarios (`student_month`,
  `tight_budget`, `asks_for_missing_info`, `category_leak`).
- `smoke_test.py` — quick 4-turn check from the terminal.

---

## 3. File map

| File | What it holds |
|---|---|
| `budget_agent/memory.py` | `Memory` dataclass; `Expense`; keyword categoriser; totals, breakdown, balance |
| `budget_agent/tools.py` | the two tool functions + their JSON schemas (`TOOL_SCHEMAS`) + the `TOOLS` registry |
| `budget_agent/agent.py` | `Agent` class, the plan-act loop, both lanes, the NL parsing helpers, `Result`/`show_trace` |
| `budget_agent/lanes.py` | `get_client()` / `get_model()` — resolves base URL + key + model from `.env` |
| `budget_agent/seeds.py` | `SCENARIOS` — canned demo conversations |
| `demo.ipynb` | the graded demo notebook |
| `frontend/server.py`, `frontend/index.html` | the web UI |
| `.env` (gitignored) | `PROVIDER=groq`, `GROQ_API_KEY=...` |
| `.env.example` | template for the above |

---

## 4. The two tools — expect direct questions here

### `add_expense(memory, item, amount)` — `tools.py:19`
- **What it does:** validates `amount` (must be a positive number), categorises
  `item` with `categorise()`, appends an `Expense(item, amount, category)` to
  `memory.expenses`.
- **What it returns (the observation the agent reads):**
  ```python
  {"ok": True,
   "recorded": {"item": "lunch", "amount": 250.0, "category": "food"},
   "category_total": 250.0,     # total in that category so far
   "total_spent": 250.0,        # total across all categories
   "balance": 14750.0}          # budget - total_spent, or None if no budget
  ```
- **On bad input:** `{"ok": False, "error": "amount 'abc' is not a number"}` —
  the agent sees the error in the trace rather than crashing.
- **Who calls it:** the rule planner at `agent.py:214`; the LLM via a
  `tool_calls` entry, dispatched at `agent.py:327`.

### `get_summary(memory, category="all")` — `tools.py:40`
- **What it does:** reads `memory` and returns totals. No writing.
- **Returns:**
  ```python
  {"ok": True, "scope": "all",
   "total_spent": 2150.0,
   "budget": 15000.0,
   "balance": 12850.0,
   "by_category": {"food": 1450.0, "transport": 400.0, "entertainment": 300.0}}
  ```
  With a specific category it also adds `category_total` and
  `count_in_category`. If nothing is logged yet it returns `{"ok": True,
  "empty": True, ...}`.
- **Who calls it:** the rule planner before any affordability/summary answer
  (`agent.py:227`); the LLM (its system prompt *requires* a `get_summary` call
  before answering anything about balance — `agent.py:143`).

### How the LLM knows the tools exist
`TOOL_SCHEMAS` in `tools.py:66` — standard OpenAI function-calling schema
(name, description, JSON-schema parameters). Passed as `tools=` on every
`chat.completions.create` call (`agent.py:311`). The model replies with
`tool_calls`; the loop runs `TOOLS[name](self.memory, **args)` and feeds the
JSON result back as a `role: "tool"` message.

---

## 5. Memory — expect "what does the memory do / show me where it's read back"

`Memory` (`memory.py:64`) is a dataclass with three fields:

| Field | Purpose |
|---|---|
| `turns: list[dict]` | every message, `{"role": "user"/"agent", "content": ...}`. Added at `agent.py:171` (user) and `agent.py:191` (agent). The LLM lane replays the last 8 turns as context (`agent.py:303`). |
| `expenses: list[Expense]` | the running list; each `Expense` has `item, amount, category`. This is what keeps category totals correct across many turns. |
| `monthly_budget: float | None` | set from user text before planning (`agent.py:179`). |

Derived methods: `total_spent(category)`, `category_breakdown()`,
`balance()` ( = `budget - total_spent`, or `None`), `snapshot()` (one-line
state string).

**Where memory is read back in a *later* turn (the key viva point):**
Turn 1 "My budget is 15000" → stored in `monthly_budget`.
Turn 2 "spent 250 on lunch, 400 on cab" → two `Expense` objects appended.
Turn 3 "Can I afford a 2000 trip?" → the agent calls `get_summary`, which reads
**both** `monthly_budget` (from turn 1) and `expenses` (from turn 2) to compute
`balance = 15000 - 650 = 14350`, then the agent does `14350 - 2000 = 12350` and
answers "Yes". Nothing about turn 3 is in turn 3's text — it all comes from
memory.

**Scope:** memory is per-`Agent` instance and in-process only. One `Agent()` =
one conversation. A new instance starts empty. (No database — deliberate for the
assignment's "same conversation" requirement.)

---

## 6. The plan-act loop — expect "walk me through it" / "where does it decide the next step"

### Rule lane (`_run_rule`, `agent.py:195`)
1. Parse the goal once into a **plan**: list of expenses to log
   (`_find_expenses`), an afford-amount if any (`_find_afford_amount`), whether a
   summary is needed (`_wants_summary`).
2. Loop, **one action per iteration**:
   - if expenses still pending → issue the next `add_expense`, record THINK/ACT/OBS;
   - else if a summary is needed and not fetched yet → issue `get_summary`;
   - else → break.
3. `_compose_rule_answer` turns the accumulated observations into the final
   answer. The affordability branch **reads `balance` out of the `get_summary`
   observation** (`agent.py:253`) — that is the "decide next step / answer from a
   tool result" point.
4. Append the ANSWER step to the trace.

It is deterministic: same input → same trace. Good for a demo that must run
without a key.

### LLM lane (`_run_llm`, `agent.py:294`)
1. Build `messages`: system prompt + last 8 turns from memory + the new goal
   (with a `(memory: ...)` snapshot line).
2. Loop: call `chat.completions.create(..., tools=TOOL_SCHEMAS,
   tool_choice="auto")`.
   - If the model returns `tool_calls` → run each tool, append the result as a
     `role: "tool"` message, loop again.
   - If the model returns plain content → that's the final answer, stop.
3. `max_steps` guard: if it never stops, one final call **without** tools forces
   an answer.

Same `Memory`, same `TOOLS` — only the *decider* changes.

### Why this is an agent, not a chatbot
- It **calls tools** (not just text) — `add_expense`, `get_summary`.
- It **takes more than one step** and each step's next action depends on prior
  results (log N expenses, then summarise, then decide).
- It **remembers** earlier turns and uses them later (budget + expenses in the
  affordability answer).

---

## 7. Rubric → where to point

| Rubric item | Point to |
|---|---|
| Real plan-act loop, >1 step | `agent.py:207` (rule) / `agent.py:309` (llm); any trace with steps 2–4 |
| Uses tool results to decide next step | `agent.py:253` — `balance = summary_obs["balance"]`; `agent.py:249` — no-budget branch |
| ≥2 working tools actually called | `tools.py:19` + `tools.py:40`; dispatch at `agent.py:214`, `227`, `327` |
| Memory remembers + used later | `memory.py:64`; `agent.py:179` write, `get_summary` read; turn-3 affordability example |
| Notebook runs on 2–3 goals with trace | `demo.ipynb` sections 3, 4, 5 (+ 6 for Groq) |

---

## 8. Likely viva questions and answers

**Q: What tools does your agent use and how?**
Two: `add_expense(item, amount)` writes one expense into memory and returns the
updated category total, total spent and balance; `get_summary(category)` reads
memory and returns totals + the per-category breakdown + the balance. The agent
never touches the data directly during a task — only through these functions. In
the rule lane the planner calls `TOOLS["add_expense"](memory, ...)` directly; in
the LLM lane the model emits an OpenAI `tool_calls` object (schemas in
`TOOL_SCHEMAS`) and the loop dispatches it to the same function.

**Q: Why exactly two tools?**
The topic (T1) specifies those two. "At least two" is the rule; more would be
fine but these two cover write (record spending) and read (report/decide).

**Q: Is setting the budget a tool?**
No. The budget is *memory*, not an action with side effects on the world, so the
agent extracts it from the user's text and stores it in `memory.monthly_budget`
before planning (`agent.py:177`). That's shown in the trace as a `MEMORY` step.

**Q: Where does the loop decide the next step from a tool result?**
Two places. (1) After `get_summary`, the affordability branch reads
`summary_obs["balance"]` and computes `balance - amount` to answer
(`agent.py:253`). (2) If that balance is `None` (no budget in memory), the agent
decides to *ask for the budget* instead of answering (`agent.py:249`). In the
LLM lane, the model reads the tool's JSON result and chooses whether to call
another tool or answer.

**Q: What does the memory do, and show me where it's read back later.**
It stores the turn history and the structured store (expenses + budget) for the
whole conversation. Read-back: run `student_month` — turn 1 sets the budget,
turn 2 logs expenses, turn 3 "can I afford 2000?" calls `get_summary` which
reads the budget from turn 1 and the expenses from turn 2. `agent.memory.expenses`
and `agent.memory.monthly_budget` after the run prove it.

**Q: How is an expense categorised?**
`categorise(item)` in `memory.py` — a small keyword map (e.g. "uber", "cab",
"petrol" → transport). Unknown → "other". It's a heuristic, not ML.

**Q: What's the LLM and how is it wired?**
Groq, model `openai/gpt-oss-20b`, via the OpenAI-compatible endpoint
`https://api.groq.com/openai/v1`. `lanes.py` builds an `openai.OpenAI(base_url,
api_key)` client from `.env` (`PROVIDER`, `GROQ_API_KEY`). Same lane design as
the course repo, so switching to Ollama or Foundry is a one-line `.env` change.
The agent calls `chat.completions.create` with `tools=TOOL_SCHEMAS` and loops on
`tool_calls`.

**Q: Does the notebook need an API key?**
No. Default `mode="rule"` is deterministic and standard-library only, so the
notebook always runs. If `.env` has a Groq key, section 6 also runs the live LLM
lane.

**Q: How do you stop an infinite loop?**
`max_steps` (default 6). Rule lane can't loop anyway (finite plan). LLM lane: if
it hits the cap, one final tool-less call forces an answer (`agent.py:335`).

**Q: What happens on bad input, e.g. "spent abc on lunch"?**
`add_expense` returns `{"ok": False, "error": ...}`; the agent records it in the
trace and moves on rather than crashing. The parser also just skips text it
can't turn into (item, amount).

**Q: One honest failure you hit?**
The NL expense parser. "Also paid 1200 for groceries and a movie cost 300" first
captured one expense with the item "for groceries and a movie" — a second regex
for the "X cost N" pattern overlapped the first. Fixed with three rules: strip
leading articles, cap the "X cost N" item to 3 words with no connectives, and
de-duplicate matches that share an amount and overlap textually. Later, "budget
is 4000 for the month" logged a phantom 4000 expense — fixed by stripping the
budget clause before expense parsing (`_strip_budget_clause`, `agent.py:74`).
It's still a heuristic; very unusual phrasings can be missed, but every demo
sentence parses correctly.

**Q: Rule lane vs LLM lane — which is "the agent"?**
Both. The loop, tools and memory are identical; only the component that picks the
next action differs. The rule lane proves the architecture without a network
dependency; the LLM lane shows the same architecture with a model doing the
planning.

**Q: Could you add the Group-of-3 add-on?**
Yes — `set_savings_goal` as a third tool + an overspend warning in
`get_summary`. The tool registry and schema list make adding a tool a
two-place change.

**Q: How is the trace produced?**
Every branch of the loop appends a dict `{step, action, thought, action_input,
observation}` to `trace`. `Result.show_trace()` pretty-prints it; the notebook
and the web UI both render it. It's literally the list of decisions and tool
calls the agent made.

---

## 9. Known limitations (say these before you're asked)

- NL parser is regex heuristics — no word-number ("two hundred"), no "1.2k", no
  refunds/negatives.
- Budget detection is phrase-based; unusual phrasings won't set it.
- Memory is in-process only; no persistence across runs (by design).
- Single category per expense; no editing/removing an expense.
- LLM lane depends on Groq being up; `mode="auto"` silently falls back to rule —
  check `agent.mode` to see which lane you got.
- Rule lane's summary always queries `category="all"`; it doesn't pick a single
  category even if you name one (the LLM lane can).

---

## 10. Live demo script (2 minutes)

1. `python3 frontend/server.py` → open http://127.0.0.1:8000.
2. Click **"Student monthly budget"** seed. Point at the right panel: budget
   15000, four expenses, balance updating.
3. Expand the trace on the "Can I afford a 2000 trip?" answer. Point at:
   `ACT get_summary(...)` → `OBS ...balance: 12850` → `ANSWER Yes... leaves 10850`.
   Say: "that's the loop deciding the answer from the tool result, using the
   budget and expenses from earlier turns — that's the memory."
4. Type a new message: `spent 12000 on a laptop` → then `can I afford a 2000 trip?`
   → now it says **No** and shows the shortfall (budget 15000, spent ~14150, so
   under 2000 left). Same question, different answer, because memory changed.
5. If asked for the LLM: stop the server, `AGENT_MODE=llm .venv/bin/python
   frontend/server.py`, repeat step 3 — the trace now shows the model's
   `tool_calls` instead of the rule planner, same tools.

Fallback if the web UI misbehaves: `python3 smoke_test.py` or open `demo.ipynb`.
