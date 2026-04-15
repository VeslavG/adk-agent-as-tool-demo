"""
Call Center Analyzer — Direct genai SDK (no ADK)

Same skill registry, same tools, same business logic as main.py.
The only difference: no ADK framework. The tool-call loop, session
management, and parallel execution are handled manually.

Purpose: honest comparison of ADK vs raw SDK on identical workload.
"""

import asyncio
import os
import time
import tomllib
from pathlib import Path

# ── Vertex AI config ──────────────────────────────────────────────
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "sandbox-2025-09"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from google import genai
from google.genai import types

# Reuse the same tools and database from the ADK version
from tools import DB, get_customer_profile, get_high_value_threshold

MODEL = "gemini-3-flash-preview"
SKILLS_DIR = Path(__file__).parent / "skills"
REGISTRY_FILE = SKILLS_DIR / "registry.toml"
TEST_PHRASES_FILE = Path(__file__).parent / "test_phrases.txt"

# ═════════════════════════════════════════════════════════════════════
# TOOL REGISTRY — map names from registry.toml to callable functions
# ═════════════════════════════════════════════════════════════════════

TOOL_FUNCTIONS = {
    "get_customer_profile": get_customer_profile,
    "get_high_value_threshold": get_high_value_threshold,
}

# ═════════════════════════════════════════════════════════════════════
# TOOL DECLARATIONS — genai SDK needs explicit schemas (no auto-wrap)
# ═════════════════════════════════════════════════════════════════════
# ADK auto-generates these from Python type hints + docstrings.
# Without ADK, we declare them manually.

TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_customer_profile",
        description=(
            "Look up a customer by name. Returns their ID, balance, tier, "
            "and how long they have been a customer (months_active). "
            "Use this when the transcript mentions a customer by name."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Customer name"),
            },
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_high_value_threshold",
        description=(
            "Returns the balance threshold for high-value customers. "
            "Use this to determine if a customer is high-value."
        ),
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
])


# ═════════════════════════════════════════════════════════════════════
# SKILL LOADING — same registry.toml as ADK version
# ═════════════════════════════════════════════════════════════════════

def load_registry() -> dict:
    with open(REGISTRY_FILE, "rb") as f:
        return tomllib.load(f)


# ═════════════════════════════════════════════════════════════════════
# MANUAL TOOL-CALL LOOP — what ADK does for you automatically
# ═════════════════════════════════════════════════════════════════════

async def run_skill(client: genai.Client, skill_name: str,
                    instruction: str, text: str) -> dict:
    """Run one skill: send prompt, handle tool calls, return result."""

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        tools=[TOOL_DECLARATIONS],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    messages = [
        types.Content(role="user", parts=[types.Part.from_text(text=text)]),
    ]

    total_prompt = 0
    total_output = 0
    tool_calls = []

    t0 = time.perf_counter()

    # Loop: LLM may call tools, we execute and send results back
    while True:
        response = await client.aio.models.generate_content(
            model=MODEL, contents=messages, config=config,
        )

        # Accumulate token usage
        if response.usage_metadata:
            total_prompt += response.usage_metadata.prompt_token_count or 0
            total_output += response.usage_metadata.candidates_token_count or 0

        candidate = response.candidates[0]
        parts = candidate.content.parts

        # Check if model wants to call functions
        fn_calls = [p for p in parts if p.function_call]
        if not fn_calls:
            # No tool calls — this is the final text response
            break

        # Execute each tool call and collect responses
        messages.append(candidate.content)  # add model's tool-call message

        fn_response_parts = []
        for part in fn_calls:
            fc = part.function_call
            func = TOOL_FUNCTIONS[fc.name]
            result = func(**fc.args)
            tool_calls.append(f"{fc.name}({fc.args})")
            fn_response_parts.append(
                types.Part.from_function_response(name=fc.name, response=result)
            )

        messages.append(types.Content(role="tool", parts=fn_response_parts))

    elapsed = (time.perf_counter() - t0) * 1000

    # Extract final text
    output_text = "\n".join(
        p.text.strip() for p in parts if p.text and p.text.strip()
    )

    stats = f"{elapsed:.0f}ms | prompt={total_prompt} | output={total_output}"

    return {
        "name": skill_name,
        "output": output_text,
        "tools_used": tool_calls,
        "stats": stats,
        "elapsed_ms": elapsed,
    }


# ═════════════════════════════════════════════════════════════════════
# PARALLEL EXECUTION — asyncio.gather, same as ADK version
# ═════════════════════════════════════════════════════════════════════

async def analyze(phrase: str, client: genai.Client, registry: dict):
    """Fan-out: run all skills on the same phrase concurrently."""
    print(f"\n{'─' * 70}")
    print(f"  INPUT: {phrase}")
    print(f"{'─' * 70}")

    t0 = time.perf_counter()

    tasks = []
    for name, skill in registry.items():
        instruction = (SKILLS_DIR / skill["instruction"]).read_text(encoding="utf-8")
        tasks.append(run_skill(client, name, instruction, phrase))

    results = await asyncio.gather(*tasks)

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
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ["GOOGLE_CLOUD_LOCATION"],
    )
    registry = load_registry()

    test_phrases = [
        line.strip()
        for line in TEST_PHRASES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print("=" * 70)
    print("  Call Center Analyzer — Direct genai SDK (no ADK)")
    print(f"  Model: {MODEL}")
    print(f"  Skills: {', '.join(registry.keys())} (from registry.toml)")
    print("=" * 70)
    print()
    print("  Customer database:")
    for row in DB.execute("SELECT * FROM users ORDER BY id"):
        print(f"    #{row['id']}  {row['name']:<10} ${row['balance']:>9,.2f}"
              f"  {row['tier']:<10} {row['months_active']}mo")
    print()
    print("  Commands:")
    print("    Type a phrase   — analyze it")
    print("    'test'          — run all test phrases")
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
            await analyze(phrase, client, registry)

        print()


if __name__ == "__main__":
    asyncio.run(main())
