"""Quick smoke test of the plan-act loop + memory (offline / rule lane)."""
from budget_agent import Agent

agent = Agent(mode="rule")

goals = [
    "My monthly budget is 15000. I spent 250 on lunch and 400 on an uber ride.",
    "Also paid 1200 for groceries and a movie cost 300.",
    "Can I afford a 2000 trip this weekend?",
    "Give me a summary of where my money went.",
]

for g in goals:
    print("USER:", g)
    r = agent.run(g)
    r.show_trace()
    print("AGENT:", r.answer, "\n")

print("=== final memory ===")
print("turns:", len(agent.memory.turns))
print(agent.memory.snapshot())
