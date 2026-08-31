"""Canned demo conversations. Each scenario is an ordered list of user
messages; replaying them through one Agent shows the plan-act loop, the tool
calls, and memory being used in a later turn.

    from budget_agent import Agent
    from budget_agent.seeds import SCENARIOS

    agent = Agent(mode="rule")
    for msg in SCENARIOS["student_month"]["messages"]:
        print(agent.run(msg).answer)
"""

SCENARIOS: dict[str, dict] = {
    "student_month": {
        "title": "Student monthly budget (the flagship demo)",
        "blurb": "Sets a budget, logs four expenses across two turns, then asks "
                 "an affordability question that uses all of it from memory.",
        "messages": [
            "My monthly budget is 15000.",
            "I spent 250 on lunch and 400 on an uber ride.",
            "Also paid 1200 for groceries and a movie cost 300.",
            "Can I afford a 2000 trip this weekend?",
            "Give me a summary of where my money went.",
        ],
    },
    "tight_budget": {
        "title": "Tight budget — the answer is no",
        "blurb": "Small budget, rent eats most of it, so the agent works out "
                 "the shortfall and says no.",
        "messages": [
            "Budget is 4000 for the month.",
            "Spent 900 on groceries, 600 on petrol, 250 on coffee and 1500 on rent.",
            "Can I afford a 1500 phone?",
        ],
    },
    "asks_for_missing_info": {
        "title": "Agent decides from a tool result",
        "blurb": "No budget in memory yet, so after get_summary the agent asks "
                 "for it instead of guessing. Give the budget, ask again, "
                 "different plan.",
        "messages": [
            "I spent 500 on shoes and 300 on headphones.",
            "Can I afford a 3000 phone?",
            "My budget is 4000. Now can I afford a 3000 phone?",
        ],
    },
    "category_leak": {
        "title": "Where is the money going?",
        "blurb": "Logs a mixed week and asks for the category breakdown.",
        "messages": [
            "My budget this month is 20000.",
            "Spent 3000 on rent, 1800 on groceries, 900 on petrol, 1200 on "
            "netflix and spotify, 600 on coffee, 2500 on a new phone.",
            "Where did my money go?",
            "Can I afford a 5000 weekend trip?",
        ],
    },
}
