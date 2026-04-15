"""
Shared FunctionTools for the Call Center Analyzer.

These are plain Python functions that execute real SQL against SQLite.
ADK auto-wraps them into FunctionTool objects using the function name,
type hints, and docstring.

All agents share the same tools — each gets direct database access
without going through an intermediary agent.
"""

import random
import sqlite3


# ── Database setup ──────────────────────────────────────────────────

def init_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database with sample customer data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE users (
            id              INTEGER PRIMARY KEY,
            name            TEXT NOT NULL,
            balance         REAL NOT NULL,
            tier            TEXT NOT NULL,
            months_active   INTEGER NOT NULL
        )
    """)
    random.seed(42)
    customers = [
        (1, "Alice",   6430.33, "Gold",     36),
        (2, "Bob",      347.61, "Standard",  3),
        (3, "Charlie", 2822.79, "Silver",   18),
        (4, "Dave",    2309.79, "Silver",   12),
        (5, "Eve",     7391.07, "Platinum", 60),
        (6, "Frank",   6799.32, "Gold",     48),
    ]
    for uid, name, balance, tier, months in customers:
        conn.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (uid, name, balance, tier, months),
        )
    conn.commit()
    return conn


DB = init_db()


# ── FunctionTools (exposed to agents) ───────────────────────────────

def get_customer_profile(name: str) -> dict:
    """Look up a customer by name. Returns their ID, balance, tier,
    and how long they have been a customer (months_active).
    Use this when the transcript mentions a customer by name."""
    row = DB.execute(
        "SELECT * FROM users WHERE LOWER(name) = LOWER(?)", (name,),
    ).fetchone()
    if row:
        return {
            "id": row["id"],
            "name": row["name"],
            "balance": row["balance"],
            "tier": row["tier"],
            "months_active": row["months_active"],
        }
    return {"error": f"Customer '{name}' not found"}


def get_high_value_threshold() -> dict:
    """Returns the balance threshold for high-value customers.
    Use this to determine if a customer is high-value."""
    return {"threshold": 5000.00, "currency": "USD"}
