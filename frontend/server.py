"""Tiny web frontend for the Personal Budget Assistant agent.

Standard library only - no Flask, no build step. It serves one chat page and a
few JSON endpoints that drive a single in-memory Agent session.

    python3 frontend/server.py            # rule lane (no key needed)
    AGENT_MODE=llm python3 frontend/server.py   # Groq lane (needs .env)
    AGENT_MODE=auto python3 frontend/server.py  # llm if .env configured, else rule

Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget_agent import Agent  # noqa: E402
from budget_agent.seeds import SCENARIOS  # noqa: E402

HERE = Path(__file__).resolve().parent
MODE = os.environ.get("AGENT_MODE", "rule")  # requested mode: rule | llm | auto
PORT = int(os.environ.get("PORT", "8000"))
VALID_MODES = ("rule", "llm", "auto")

_lock = threading.Lock()
_agent = Agent(mode=MODE)


def _new_agent() -> Agent:
    global _agent
    _agent = Agent(mode=MODE)
    return _agent


def _lane_check() -> str:
    """Empty string if the LLM lane is usable, else a short reason why not."""
    try:
        from budget_agent.lanes import describe, get_client
        get_client()
        return describe()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _set_mode(requested: str) -> dict:
    global MODE
    requested = (requested or "").strip().lower()
    if requested not in VALID_MODES:
        return {"error": f"unknown mode {requested!r} (use rule|llm|auto)"}
    note = _lane_check() if requested in ("llm", "auto") else ""
    MODE = requested
    _new_agent()
    return {"state": _state(), "note": note}


def _state() -> dict:
    m = _agent.memory
    return {
        "requested": MODE,        # what the user picked (rule|llm|auto)
        "mode": _agent.mode,      # what it resolved to (rule|llm)
        "budget": m.monthly_budget,
        "total_spent": m.total_spent("all"),
        "balance": m.balance(),
        "by_category": m.category_breakdown(),
        "n_expenses": len(m.expenses),
        "n_turns": len(m.turns),
        "turns": m.turns,
    }


def _chat(message: str) -> dict:
    result = _agent.run(message)
    return {"answer": result.answer, "trace": result.trace, "state": _state()}


def _seed(key: str) -> dict:
    if key not in SCENARIOS:
        return {"error": f"unknown scenario {key!r}"}
    _new_agent()
    conversation = []
    for msg in SCENARIOS[key]["messages"]:
        result = _agent.run(msg)
        conversation.append({"role": "user", "content": msg})
        conversation.append({"role": "agent", "content": result.answer,
                             "trace": result.trace})
    return {"conversation": conversation, "state": _state()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode(),
                   "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(),
                       "text/html; charset=utf-8")
        elif self.path == "/api/state":
            with _lock:
                self._json(_state())
        elif self.path == "/api/scenarios":
            self._json({"scenarios": [
                {"key": k, "title": v["title"], "blurb": v["blurb"],
                 "messages": v["messages"]}
                for k, v in SCENARIOS.items()
            ]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or "{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        with _lock:
            try:
                if self.path == "/api/chat":
                    msg = (payload.get("message") or "").strip()
                    if not msg:
                        return self._json({"error": "empty message"}, 400)
                    self._json(_chat(msg))
                elif self.path == "/api/reset":
                    _new_agent()
                    self._json({"state": _state()})
                elif self.path == "/api/seed":
                    self._json(_seed(payload.get("key", "")))
                elif self.path == "/api/mode":
                    self._json(_set_mode(payload.get("mode", "")))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:  # surface agent/LLM errors to the page
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Budget Agent frontend  ->  http://127.0.0.1:{PORT}")
    print(f"lane: {_agent.mode}   (switch it live with the rule/auto/llm "
          f"buttons in the page header)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
