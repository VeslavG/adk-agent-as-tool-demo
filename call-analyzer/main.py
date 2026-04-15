"""
Call Center Analyzer — Parallel Agents with Skills + FunctionTools

Three agents analyze a customer's phrase concurrently:
  - Scorer:    sentiment, urgency, churn risk
  - Red Flags: compliance and risk flags
  - Advisor:   suggested next actions for the operator

Each agent's behavior is defined by a Skill (a .md file in skills/).
Each agent's capabilities come from shared FunctionTools (tools.py).

To change an agent's behavior, edit its skill file — no code changes needed.
"""

import asyncio
import os
import time
import tomllib
from pathlib import Path

# ── Vertex AI config (must be set before ADK imports) ───────────────
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "sandbox-2025-09"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import logging
import warnings

warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from tools import DB, get_customer_profile, get_high_value_threshold

MODEL = "gemini-3-flash-preview"
SKILLS_DIR = Path(__file__).parent / "skills"
REGISTRY_FILE = SKILLS_DIR / "registry.toml"
TEST_PHRASES_FILE = Path(__file__).parent / "test_phrases.txt"

# ── Disable thinking tokens for lower latency ─────────────────────
NO_THINKING = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)


# ═════════════════════════════════════════════════════════════════════
# SKILL REGISTRY — declarative index of all skills (registry.toml)
# ═════════════════════════════════════════════════════════════════════
# In production this would be Redis, Firestore, or a DB table.
# Each entry maps a skill name to its instruction file, required tools,
# and expected output format. To add a new skill, add an entry here
# and create the corresponding .md file — no code changes needed.

# Available tools — registry references them by name
TOOL_REGISTRY = {
    "get_customer_profile": get_customer_profile,
    "get_high_value_threshold": get_high_value_threshold,
}

def load_agents_from_registry() -> list[Agent]:
    """Build Agent objects from registry.toml — zero hardcoded agents."""
    with open(REGISTRY_FILE, "rb") as f:
        registry = tomllib.load(f)

    agents = []
    for name, skill in registry.items():
        instruction = (SKILLS_DIR / skill["instruction"]).read_text(encoding="utf-8")
        tools = [TOOL_REGISTRY[t] for t in skill["tools"]]
        agents.append(Agent(
            name=name,
            model=MODEL,
            instruction=instruction,
            tools=tools,
            generate_content_config=NO_THINKING,
        ))
    return agents

agents = load_agents_from_registry()


# ═════════════════════════════════════════════════════════════════════
# PARALLEL EXECUTION
# ═════════════════════════════════════════════════════════════════════

async def run_agent(agent: Agent, session_service, text: str):
    """Run a single agent and return its output + stats."""
    app_name = f"call_{agent.name}"
    session = await session_service.create_session(
        app_name=app_name, user_id="user",
    )
    runner = Runner(
        agent=agent, app_name=app_name,
        session_service=session_service,
    )
    msg = types.Content(role="user", parts=[types.Part(text=text)])

    lines = []
    total_prompt = 0
    total_output = 0
    total_thinking = 0
    tool_calls = []

    t0 = time.perf_counter()

    async for event in runner.run_async(
        user_id="user", session_id=session.id, new_message=msg,
    ):
        if not event.content or not event.content.parts:
            continue
        if event.usage_metadata:
            u = event.usage_metadata
            total_prompt += u.prompt_token_count or 0
            total_output += u.candidates_token_count or 0
            total_thinking += getattr(u, "thoughts_token_count", 0) or 0
        for part in event.content.parts:
            if part.function_call:
                tool_calls.append(
                    f"{part.function_call.name}({part.function_call.args})"
                )
            elif part.text and part.text.strip():
                lines.append(part.text.strip())

    elapsed = (time.perf_counter() - t0) * 1000
    stats = f"{elapsed:.0f}ms | prompt={total_prompt} | output={total_output}"
    if total_thinking:
        stats += f" | thinking={total_thinking}"

    return {
        "name": agent.name,
        "output": "\n".join(lines),
        "tools_used": tool_calls,
        "stats": stats,
        "elapsed_ms": elapsed,
    }


async def analyze(phrase: str, session_service):
    """Fan-out: run all agents on the same phrase concurrently."""
    print(f"\n{'─' * 70}")
    print(f"  INPUT: {phrase}")
    print(f"{'─' * 70}")

    t0 = time.perf_counter()

    results = await asyncio.gather(
        *[run_agent(a, session_service, phrase) for a in agents]
    )

    wall_clock = (time.perf_counter() - t0) * 1000

    for r in results:
        tools_str = (
            f"  tools: {', '.join(r['tools_used'])}"
            if r["tools_used"] else ""
        )
        print(f"\n  [{r['name']}] ({r['stats']}){tools_str}")
        for line in r["output"].split("\n"):
            print(f"    {line}")

    print(f"\n  wall clock: {wall_clock:.0f}ms "
          f"(sum of individual: "
          f"{sum(r['elapsed_ms'] for r in results):.0f}ms)")


# ═════════════════════════════════════════════════════════════════════
# INTERACTIVE LOOP
# ═════════════════════════════════════════════════════════════════════

async def main():
    session_service = InMemorySessionService()

    # Load test phrases
    test_phrases = [
        line.strip()
        for line in TEST_PHRASES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print("=" * 70)
    print("  Call Center Analyzer — Skills + Parallel Agents")
    print(f"  Model: {MODEL}")
    print(f"  Skills: {', '.join(s.stem for s in SKILLS_DIR.glob('*.md'))}")
    print(f"  Agents: {', '.join(a.name for a in agents)} (concurrent)")
    print("=" * 70)
    print()
    print("  Customer database:")
    for row in DB.execute("SELECT * FROM users ORDER BY id"):
        print(f"    #{row['id']}  {row['name']:<10} ${row['balance']:>9,.2f}"
              f"  {row['tier']:<10} {row['months_active']}mo")
    print()
    print("  Commands:")
    print("    Type a phrase   — analyze it")
    print("    'test'          — run all test phrases from test_phrases.txt")
    print("    'quit'          — exit")
    print("=" * 70)

    while True:
        try:
            user_input = input("\nPhrase: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        phrases = test_phrases if user_input.lower() == "test" else [user_input]

        for phrase in phrases:
            await analyze(phrase, session_service)

        print()


if __name__ == "__main__":
    asyncio.run(main())
