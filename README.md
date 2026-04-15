# Google ADK: Agent-as-Tool Demos

Two working demos of the [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) `AgentTool` pattern — wrapping one agent as a callable tool for another agent.

Both demos are interactive (terminal chat), show per-turn latency and token usage, and run on **Vertex AI**.

## Demo 1: Calculator (`agent_as_tool_demo.py`)

Minimal example. Manager agent delegates math questions to a Calculator sub-agent.

```
User  <-->  Manager Agent  --AgentTool-->  Calculator Agent
            (orchestrator)                 (LLM does math)
```

```
You: 2+2?
  >> [manager] calls tool 'calculator' with: {'request': '2+2'}
  << tool 'calculator' returned: {'result': '4'}
[manager]: 2+2 = 4.
  [12475ms | prompt=254 | output=11 | thinking=30]
```

The calculator "thinks" about math (no real computation) — this is intentionally naive to contrast with Demo 2.

## Demo 2: Database Agent (`db_agent_demo.py`)

Realistic example. Manager agent delegates data questions to a DB Agent, which calls **real Python functions** that execute **real SQL** against a SQLite database.

```
User  <-->  Manager Agent  --AgentTool-->  DB Agent
            (conversational)               (data specialist)
                                              |
                                       FunctionTools (Python)
                                              |
                                         SQLite database
```

The DB Agent has 4 tools (plain Python functions, auto-wrapped by ADK):

| Tool | SQL |
|------|-----|
| `get_user_by_name(name)` | `SELECT ... WHERE name = ?` |
| `get_user_by_id(user_id)` | `SELECT ... WHERE id = ?` |
| `count_users()` | `SELECT COUNT(*)` |
| `get_top_balances(limit)` | `SELECT ... ORDER BY balance DESC LIMIT ?` |

```
You: what is Eve's ID?
  >> [manager] calls 'db_agent' with {'request': "What is Eve's ID?"}
  << 'db_agent' returned: {'result': '{"id": 5, "name": "Eve", "balance": 7391.07}'}
[manager]: Eve's ID is 5.
  [15678ms | prompt=414 | output=23 | thinking=45]
```

### Tracing

Demo 2 exports OpenTelemetry spans to `trace.jsonl` (one JSON per line). Each span includes trace/span IDs, parent-child relationships, duration, token counts, and tool call arguments.

Span tree for a single query:

```
invocation                                    15678ms
  invoke_agent manager                        15678ms
    call_llm (manager -> gemini-3-flash)      12075ms  in=155 out=15 think=45
      execute_tool db_agent (AgentTool)         7682ms
        invoke_agent db_agent                   7682ms
          call_llm (db_agent -> gemini)          3917ms  in=259 out=13 think=57
            execute_tool get_user_by_name         0.0ms  <-- actual SQL
          call_llm (db_agent -> gemini)          3764ms  in=395 out=24
    call_llm (manager -> gemini)                3600ms  in=259 out=8
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Cloud project with Vertex AI API enabled
- `gcloud auth application-default login` (authenticated)

## Setup

```bash
cd adk
uv sync
```

Edit the `GOOGLE_CLOUD_PROJECT` in either demo file to match your GCP project, or set the env var:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GOOGLE_GENAI_USE_VERTEXAI=true
```

## Run

```bash
# Demo 1: Calculator (minimal AgentTool example)
uv run python agent_as_tool_demo.py

# Demo 2: Database Agent (realistic, with tracing)
uv run python db_agent_demo.py
```

## Test cases

### Demo 1 (Calculator)

| Input | Expected behavior |
|-------|-------------------|
| `hello` | Manager answers directly, no tool call |
| `2+2` | Manager calls calculator tool, returns 4 |
| `what is 123 * 456 + 789?` | Calculator tool called, returns 56877 |
| `roses are red?` | Manager answers directly (not math) |

### Demo 2 (Database)

| Input | Expected behavior |
|-------|-------------------|
| `hello` | Manager answers directly, no tool call |
| `What is Eve's ID?` | manager -> db_agent -> `get_user_by_name("Eve")` -> ID 5 |
| `Tell me about user 3` | manager -> db_agent -> `get_user_by_id(3)` -> Charlie |
| `How many users?` | manager -> db_agent -> `count_users()` -> 6 |
| `Who are the top 3 richest?` | manager -> db_agent -> `get_top_balances(3)` -> Eve, Frank, Alice |
| `What is the weather?` | Manager answers directly (not a data question) |

## Key ADK concepts used

- **`Agent`** — LLM agent with instruction, model, and tools
- **`AgentTool`** — wraps an Agent so it can be called as a tool by another Agent
- **`FunctionTool`** (implicit) — plain Python functions auto-wrapped by ADK via type hints and docstrings
- **`Runner`** — executes the agent loop (LLM call -> tool call -> LLM call -> ...)
- **`InMemorySessionService`** — tracks conversation state between turns
- **OpenTelemetry tracing** — built into ADK, exportable to file/Jaeger/Cloud Trace

## Latency notes

Each tool call = multiple LLM round-trips:

1. Manager LLM call (~3.5s) — decides to call tool
2. Sub-agent LLM call (~3.5s) — decides which function to use
3. Function execution (~0ms for SQLite)
4. Sub-agent LLM call (~3.5s) — formulates response
5. Manager LLM call (~3.5s) — presents result to user

Total: **~14s per tool call** (4 LLM round-trips). This is an architectural reality of multi-agent systems, not a bug.

## Files

```
adk/
  agent_as_tool_demo.py   # Demo 1: Calculator (minimal)
  db_agent_demo.py        # Demo 2: Database (realistic + tracing)
  trace.jsonl             # OpenTelemetry spans (generated by Demo 2)
  pyproject.toml          # uv project config
```

## Links

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK GitHub (Python)](https://github.com/google/adk-python)
- [ADK Samples](https://github.com/google/adk-samples)
- [Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-builder/adk-overview)
