"""
The lane resolver — same setup as the cse476-agentic-ai course repo.

One socket, several plugs. The agent imports get_client() / get_model() from
here and never cares which provider is behind it.

    from budget_agent.lanes import get_client, get_model
    client = get_client()
    reply = client.chat.completions.create(model=get_model(), messages=[...])

Change PROVIDER in .env. Change nothing else. The OpenAI Python SDK talks to any
service that speaks the OpenAI chat-completions protocol — Groq, Ollama and
Microsoft Foundry all do — so the only things that vary per lane are the base
URL, the credential env var, and the default model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env() -> None:
    """Load .env. Uses python-dotenv if installed; otherwise a tiny built-in
    parser so the LLM lane still works without the extra package."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return
    except ModuleNotFoundError:
        pass
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        env = base / ".env"
        if not env.is_file():
            continue
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(),
                                  val.strip().strip('"').strip("'"))
        return


_load_env()


class LaneError(RuntimeError):
    """Raised when a lane is selected but not configured. Message tells you the fix."""


@dataclass(frozen=True)
class Lane:
    key: str
    name: str
    base_url: str | None
    key_env: str
    default_model: str
    free: bool
    note: str
    retired: bool = False


LANES: dict[str, Lane] = {
    "groq": Lane(
        key="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-20b",
        free=True,
        note="Free default for this course. Fast. Get a key at console.groq.com/keys.",
    ),
    "local": Lane(
        key="local",
        name="Ollama, on your own machine",
        base_url="http://localhost:11434/v1",
        key_env="",  # Ollama needs no key
        default_model="llama3.2",
        free=True,
        note="Free, no key, no rate limit, never down, and slower than everything else.",
    ),
    "foundry": Lane(
        key="foundry",
        name="Microsoft Foundry",
        base_url=None,  # resolved from AZURE_OPENAI_ENDPOINT
        key_env="AZURE_OPENAI_API_KEY",
        default_model="chat-demo",  # your DEPLOYMENT name, not the model name
        free=False,
        note="Formerly Azure AI Foundry. The v1 surface is OpenAI-compatible.",
    ),
    "github": Lane(
        key="github",
        name="GitHub Models (retired)",
        base_url="https://models.github.ai/inference",
        key_env="GITHUB_TOKEN",
        default_model="openai/gpt-4.1-mini",
        free=True,
        note="RETIRED by GitHub on 30 July 2026. Use groq or local instead.",
        retired=True,
    ),
}

PROVIDER: str = os.getenv("PROVIDER", "groq").strip().lower()


def _lane(provider: str | None = None) -> Lane:
    key = (provider or PROVIDER).strip().lower()
    if key not in LANES:
        raise LaneError(
            f"PROVIDER is set to '{key}', which is not a lane.\n"
            f"Valid values: {', '.join(k for k in LANES if not LANES[k].retired)}\n"
            f"Fix: edit PROVIDER in your .env file."
        )
    lane = LANES[key]
    if lane.retired:
        raise LaneError(
            f"The '{key}' lane ({lane.name}) is no longer available.\n"
            f"Switch to a free lane: set PROVIDER=groq (get a key at "
            f"console.groq.com/keys) or PROVIDER=local (run Ollama locally)."
        )
    return lane


def get_model(provider: str | None = None) -> str:
    """Model name for the active lane. MODEL in .env is a hard override."""
    override = os.getenv("MODEL", "").strip()
    if not override:
        return _lane(provider).default_model
    lane = _lane(provider)
    if lane.key in ("github", "groq") and "/" not in override and override.count("-") <= 1:
        raise LaneError(
            f"MODEL={override!r} is set in .env but you are on the '{lane.key}' "
            f"lane, which has no model by that name. Delete the MODEL line so "
            f"the lane uses its default ({lane.default_model})."
        )
    return override


def get_client(provider: str | None = None):
    """Return a configured OpenAI-compatible client for the active lane."""
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise LaneError(
            "The 'openai' package is required for the LLM lane but is not "
            "installed.\nFix: pip install -r requirements.txt  (or run the "
            "server with the project venv:  .venv/bin/python frontend/server.py)"
        ) from exc

    lane = _lane(provider)

    if lane.key == "foundry":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        api_key = os.getenv(lane.key_env, "").strip()
        if not endpoint or not api_key:
            raise LaneError(
                "The 'foundry' lane is selected but not configured.\n"
                "Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in .env, or "
                "set PROVIDER=groq instead (free key at console.groq.com/keys)."
            )
        base = endpoint
        for suffix in ("/responses", "/chat/completions", "/completions"):
            if base.rstrip("/").endswith(suffix):
                base = base.rstrip("/")[: -len(suffix)]
        if not base.rstrip("/").endswith("/openai/v1"):
            base = base.rstrip("/") + "/openai/v1"
        base = base.rstrip("/") + "/"
        return OpenAI(base_url=base, api_key=api_key, timeout=60.0, max_retries=3)

    if lane.key == "local":
        return OpenAI(base_url=lane.base_url, api_key="ollama",
                      timeout=180.0, max_retries=1)

    api_key = os.getenv(lane.key_env, "").strip()
    if not api_key:
        raise LaneError(
            f"Lane '{lane.key}' ({lane.name}) is selected but {lane.key_env} is "
            f"not set.\nFix: add {lane.key_env}=... to your .env file "
            f"(copy .env.example to .env)."
        )
    return OpenAI(base_url=lane.base_url, api_key=api_key,
                  timeout=60.0, max_retries=3)


def describe() -> str:
    """One line describing the active lane. Print at the top of a notebook."""
    lane = _lane()
    tag = "free" if lane.free else "billed"
    return f"Lane: {lane.name} ({lane.key}, {tag})  |  Model: {get_model()}"
