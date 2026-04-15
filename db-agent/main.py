"""
Google ADK Demo: Agent-as-Tool with real database (SQLite)

A realistic multi-agent demo where the Manager agent delegates database
queries to a specialized DB Agent. The DB Agent doesn't "think" about
the data — it calls real Python functions that execute actual SQL.

Architecture:
    User  <-->  Manager Agent  --AgentTool-->  DB Agent
                (conversational)               (data specialist)
                                                  |
                                          FunctionTools (Python)
                                                  |
                                             SQLite database

Users in the database:
    Alice (1), Bob (2), Charlie (3), Dave (4), Eve (5), Frank (6)
    Each has a random account balance.
"""

import asyncio
import os
import random
import sqlite3
import time

# ── Vertex AI config (must be set before ADK imports) ────────────────
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "sandbox-2025-09"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import json
import logging
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

# ── OpenTelemetry: export ADK spans to a JSON file ──────────────────
# ADK already creates spans internally via its `tracer`. We just need
# to wire up an SDK TracerProvider so those spans go somewhere.
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

TRACE_FILE = "trace.jsonl"  # one JSON object per span, easy to parse


class JsonFileExporter(SpanExporter):
    """Writes each finished span as a single JSON line to a file."""

    def __init__(self, path: str):
        self._f = open(path, "w", encoding="utf-8")

    def export(self, spans):
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent
            record = {
                "trace_id": f"{ctx.trace_id:032x}",
                "span_id": f"{ctx.span_id:016x}",
                "parent_span_id": (
                    f"{parent.span_id:016x}" if parent else None
                ),
                "name": span.name,
                "start": datetime.fromtimestamp(
                    span.start_time / 1e9, tz=timezone.utc
                ).isoformat(),
                "end": datetime.fromtimestamp(
                    span.end_time / 1e9, tz=timezone.utc
                ).isoformat(),
                "duration_ms": round(
                    (span.end_time - span.start_time) / 1e6, 1
                ),
                "attributes": {
                    k: v
                    for k, v in (span.attributes or {}).items()
                    # skip giant serialized blobs, keep the useful stuff
                    if not k.endswith(("llm_request", "llm_response",
                                      "tool_response", "data"))
                },
            }
            self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self._f.close()


provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(JsonFileExporter(TRACE_FILE)))
otel_trace.set_tracer_provider(provider)

from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-3-flash-preview"


# ═════════════════════════════════════════════════════════════════════
# DATABASE SETUP
# ═════════════════════════════════════════════════════════════════════

DB_PATH = ":memory:"  # in-memory SQLite, fresh each run

def init_db() -> sqlite3.Connection:
    """Create the users table and seed it with test data."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # dict-like access to columns
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id      INTEGER PRIMARY KEY,
            name    TEXT    NOT NULL,
            balance REAL    NOT NULL
        )
    """)
    # Seed data: 6 users with random balances ($100–$10,000)
    random.seed(42)  # reproducible balances
    users = [
        (1, "Alice"),
        (2, "Bob"),
        (3, "Charlie"),
        (4, "Dave"),
        (5, "Eve"),
        (6, "Frank"),
    ]
    for uid, name in users:
        balance = round(random.uniform(100, 10000), 2)
        conn.execute(
            "INSERT OR REPLACE INTO users (id, name, balance) VALUES (?, ?, ?)",
            (uid, name, balance),
        )
    conn.commit()
    return conn


# Global connection — shared by all tool functions
DB = init_db()


# ═════════════════════════════════════════════════════════════════════
# FUNCTION TOOLS — real Python functions that execute real SQL
# ═════════════════════════════════════════════════════════════════════
# ADK auto-wraps plain Python functions into FunctionTool objects.
# The docstring becomes the tool description for the LLM.
# Parameter names and type hints become the JSON schema.

def get_user_by_name(name: str) -> dict:
    """Look up a user by name. Returns their ID and account balance.
    Use this when the user asks about a specific person by name."""
    row = DB.execute(
        "SELECT id, name, balance FROM users WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    if row:
        return {"id": row["id"], "name": row["name"], "balance": row["balance"]}
    return {"error": f"User '{name}' not found"}


def get_user_by_id(user_id: int) -> dict:
    """Look up a user by their numeric ID. Returns their name and balance.
    Use this when the user asks about a specific user ID."""
    row = DB.execute(
        "SELECT id, name, balance FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row:
        return {"id": row["id"], "name": row["name"], "balance": row["balance"]}
    return {"error": f"User with ID {user_id} not found"}


def count_users() -> dict:
    """Count the total number of users in the database.
    Use this when the user asks how many users/people/accounts exist."""
    row = DB.execute("SELECT COUNT(*) as total FROM users").fetchone()
    return {"total_users": row["total"]}


def get_top_balances(limit: int) -> dict:
    """Get users with the highest account balances, sorted descending.
    Use this when the user asks about richest users, top balances, or rankings."""
    rows = DB.execute(
        "SELECT id, name, balance FROM users ORDER BY balance DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {
        "users": [
            {"id": r["id"], "name": r["name"], "balance": r["balance"]}
            for r in rows
        ]
    }


# ═════════════════════════════════════════════════════════════════════
# AGENT SETUP
# ═════════════════════════════════════════════════════════════════════

# DB Agent: has the SQL tools, knows how to query data
db_agent = Agent(
    name="db_agent",
    model=MODEL,
    description=(
        "A database agent with access to the users database. "
        "Use it for ANY question about users, balances, accounts, or IDs."
    ),
    instruction=(
        "You are a database assistant. You have tools to query a users "
        "database. Use the appropriate tool to answer the question. "
        "Always use a tool — never guess or make up data. "
        "Return the raw data from the tool, don't embellish."
    ),
    tools=[
        get_user_by_name,
        get_user_by_id,
        count_users,
        get_top_balances,
    ],
)

# Manager: conversational front-end, delegates data questions to db_agent
manager_agent = Agent(
    name="manager",
    model=MODEL,
    instruction=(
        "You are a friendly customer service manager at a bank. "
        "You have access to a database of customers via the db_agent tool. "
        "The database contains user names, IDs, and account balances. "
        "Whenever the user asks about a person, ID, balance, account, or "
        "anything related to customer data — ALWAYS use the db_agent tool. "
        "Never say you don't have a database. You do. Use it. "
        "For general conversation, answer directly. "
        "Present database results in a clear, human-friendly way."
    ),
    tools=[AgentTool(agent=db_agent)],
)


# ═════════════════════════════════════════════════════════════════════
# INTERACTIVE LOOP
# ═════════════════════════════════════════════════════════════════════

async def main():
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="db_demo", user_id="user",
    )
    runner = Runner(
        agent=manager_agent, app_name="db_demo",
        session_service=session_service,
    )

    # Show the seeded data so the user knows what's in the DB
    print("=" * 64)
    print("  ADK Demo: Agent → Agent → SQL Database")
    print(f"  Model: {MODEL}")
    print("=" * 64)
    print()
    print("  Database contents:")
    for row in DB.execute("SELECT * FROM users ORDER BY id"):
        print(f"    #{row['id']}  {row['name']:<10} ${row['balance']:>9,.2f}")
    print()
    print("  Try: 'What is Eve's ID?', 'How many users?',")
    print("       'Who has the most money?', 'Tell me about user 3'")
    print("  Type 'quit' to exit.")
    print("=" * 64)
    print()

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
                    print(f"  >> [{author}] calls '{fc.name}' "
                          f"with {fc.args}")
                elif part.function_response:
                    fr = part.function_response
                    print(f"  << '{fr.name}' returned: {fr.response}")
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
