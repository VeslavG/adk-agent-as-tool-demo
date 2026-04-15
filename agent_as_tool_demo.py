"""
Google ADK Demo: Agent as Tool (AgentTool pattern)

Shows how to wrap a specialized agent and expose it as a callable tool
to a parent (orchestrator) agent. The parent LLM decides when to invoke
the sub-agent based on the user's request — just like calling a function.

Architecture:
    User  <-->  Manager Agent  --AgentTool-->  Calculator Agent
                (orchestrator)                 (specialist)
"""

import asyncio
import os
import time

# ── Vertex AI configuration ─────────────────────────────────────────
# ADK uses the google-genai SDK under the hood. These env vars tell it
# to route requests through Vertex AI (not the Gemini Developer API).
# Must be set BEFORE importing any ADK modules.
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "sandbox-2025-09"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import logging
import warnings

# Suppress noisy warnings from the genai SDK and ADK internals
warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-3-flash-preview"

# ── Step 1: Define a specialized sub-agent ───────────────────────────
# This agent knows nothing about the parent. It's a standalone agent
# with its own instruction and (optionally) its own set of tools.
# The `description` field is critical — the parent LLM reads it to
# decide WHEN to call this tool vs. handling the request itself.
calculator_agent = Agent(
    name="calculator",
    model=MODEL,
    description=(
        "A calculator agent. Use it to evaluate math expressions "
        "and return numeric results."
    ),
    instruction=(
        "You are a calculator. Given a math expression, compute the "
        "exact result. Reply ONLY with the numeric answer, nothing else."
    ),
)

# ── Step 2: Wrap the agent as a tool ─────────────────────────────────
# AgentTool takes the sub-agent and exposes it to the parent as a
# callable function. Under the hood it:
#   1. Generates a JSON schema from the agent's name + description
#   2. When invoked, runs the sub-agent's full execution loop
#   3. Returns the sub-agent's final text response to the parent
calculator_tool = AgentTool(agent=calculator_agent)

# ── Step 3: Create the parent (orchestrator) agent ───────────────────
# The parent agent receives the AgentTool in its `tools` list — same
# place where you'd put regular function tools. The LLM sees it as
# just another callable tool and decides when to use it.
manager_agent = Agent(
    name="manager",
    model=MODEL,
    instruction=(
        "You are a helpful assistant. "
        "When the user asks a math question, use the calculator tool "
        "to compute the answer, then report the result. "
        "For non-math questions, answer directly."
    ),
    tools=[calculator_tool],
)


async def main():
    # ── Session setup ────────────────────────────────────────────────
    # ADK requires a session service to track conversation state.
    # InMemorySessionService is fine for demos; for production you'd
    # use a persistent backend (Firestore, Spanner, etc.).
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="agent_tool_demo",
        user_id="user",
    )

    runner = Runner(
        agent=manager_agent,
        app_name="agent_tool_demo",
        session_service=session_service,
    )

    print("=" * 60)
    print("  ADK Demo: Agent as Tool (AgentTool)")
    print(f"  Model: {MODEL}")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 60)
    print()

    # ── Interactive chat loop ────────────────────────────────────────
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        user_message = types.Content(
            role="user",
            parts=[types.Part(text=user_input)],
        )

        t0 = time.perf_counter()
        total_prompt = 0
        total_output = 0
        total_thinking = 0

        # Run the agent and stream events.
        # ADK emits separate events for each step:
        #   1. function_call  — manager decided to invoke a sub-agent tool
        #   2. function_response — sub-agent returned its result
        #   3. text — manager's final answer to the user
        async for event in runner.run_async(
            user_id="user",
            session_id=session.id,
            new_message=user_message,
        ):
            if not event.content or not event.content.parts:
                continue

            if event.usage_metadata:
                u = event.usage_metadata
                total_prompt += u.prompt_token_count or 0
                total_output += u.candidates_token_count or 0
                total_thinking += getattr(u, "thoughts_token_count", 0) or 0

            author = event.author or "?"
            for part in event.content.parts:
                if part.function_call:
                    fc = part.function_call
                    print(f"  >> [{author}] calls tool '{fc.name}' "
                          f"with: {fc.args}")
                elif part.function_response:
                    fr = part.function_response
                    print(f"  << tool '{fr.name}' returned: "
                          f"{fr.response}")
                elif part.text and part.text.strip():
                    print(f"[{author}]: {part.text}")

        elapsed = (time.perf_counter() - t0) * 1000
        stats = f"{elapsed:.0f}ms | prompt={total_prompt} | output={total_output}"
        if total_thinking:
            stats += f" | thinking={total_thinking}"
        print(f"  [{stats}]")
        print()


if __name__ == "__main__":
    asyncio.run(main())
