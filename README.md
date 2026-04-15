# Google ADK: Agent Orchestration Demos

Working demos of [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/)
patterns on Vertex AI — from prototype to production architecture.

## Demos

| # | Demo | Pattern | LLM calls | Wall clock | Folder |
|---|------|---------|-----------|------------|--------|
| 1 | Calculator | `AgentTool` (agent-as-tool) | 4 sequential | ~14s | `calculator/` |
| 2 | Database Agent | `AgentTool` + FunctionTools + tracing | 4 sequential | ~14s | `db-agent/` |
| 3a | **Call Analyzer (ADK)** | **Skills + Parallel FunctionTools** | **2×3 concurrent** | **~10s** | `call-analyzer/` |
| 3b | **Call Analyzer (Direct)** | **genai SDK + asyncio.gather** | **2×3 concurrent** | **~4s** | `call-analyzer/` |

All demos use **Google ADK** (production-ready framework), **Vertex AI**,
and **Gemini** models. Interactive terminal UI with latency and token metrics.

---

## Demo 1: Calculator (`calculator/`)

Minimal `AgentTool` example. Manager agent wraps a Calculator sub-agent as a tool.

```
User  →  Manager Agent  --AgentTool-->  Calculator Agent
```

Three lines of ADK are the core idea:
```python
calculator = Agent(name="calculator", ...)
calculator_tool = AgentTool(agent=calculator)
manager = Agent(..., tools=[calculator_tool])
```

## Demo 2: Database Agent (`db-agent/`)

Realistic `AgentTool` example with real SQL (SQLite), parameterized queries,
and OpenTelemetry tracing exported to `trace.jsonl`.

```
User  →  Manager Agent  --AgentTool-->  DB Agent  → FunctionTools → SQL
```

## Demo 3: Call Center Analyzer (`call-analyzer/`)

**Production pattern.** Three agents analyze a customer's phrase concurrently.
Each agent's behavior is defined by a **Skill** (`.md` file), and its
capabilities come from shared **FunctionTools** (Python + SQL).

```
              ┌─ Scorer Agent ─────── skills/scorer.md + tools.py
User input ───┼─ Red Flags Agent ──── skills/red_flags.md + tools.py
              └─ Advisor Agent ─────── skills/advisor.md + tools.py
              (all three run concurrently)
```

```
Phrase: Customer Alice says: I want to close all my accounts

  [scorer]     Urgency: 10/10 | Sentiment: negative | Churn risk: HIGH
  [red_flags]  ⚠ Account closure request  ⚠ High-value customer churn
  [advisor]    1. Offer retention package  2. Escalate to specialist

  wall clock: 10495ms (sum of individual: 25335ms)
```

**To change agent behavior, edit the skill file. No code changes.**

---

## Evolution: prototype → production

The three demos show a deliberate architectural evolution:

1. **Prototype** (Demos 1-2): `AgentTool` pattern — sub-agents wrapped as tools.
   Correct domain knowledge and tool structure, but sequential execution
   (4 LLM calls, ~14s).

2. **Production** (Demo 3): Sub-agents are **promoted to Skills**.
   Domain knowledge moves to `.md` files. Function tools move directly
   onto agents. Independent analyses run concurrently.
   Same ADK, same tools, same knowledge — different execution model.

### Demo 3b: same workload, no framework

`call-analyzer/main_direct.py` — identical skills, tools, and tool-call
flow, but using `genai.Client` + `asyncio.gather` instead of ADK.
Same `registry.toml`, same business logic, same number of LLM calls.

| Approach | Latency (3 agents, concurrent) |
|----------|-------------------------------:|
| ADK (`main.py`) | ~10s |
| **Direct SDK (`main_direct.py`)** | **~4s** |

**2.5x faster.** The difference is pure framework overhead.

*Measured on the same Vertex AI project, April 2025.
See [LATENCY.md](LATENCY.md) for full benchmarks.*

See [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) for the full rationale
and [LATENCY.md](LATENCY.md) for latency analysis.

---

## Setup

```bash
# Prerequisites: Python 3.12+, uv, gcloud auth
uv sync

# Set your GCP project (or edit the scripts directly)
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GOOGLE_GENAI_USE_VERTEXAI=true
```

## Run

```bash
# Demo 1: Calculator (minimal AgentTool)
uv run python calculator/main.py

# Demo 2: Database Agent (AgentTool + SQL + tracing)
uv run python db-agent/main.py

# Demo 3a: Call Analyzer — ADK (Skills + Parallel)
cd call-analyzer
uv run python main.py           # interactive, type 'test' for all phrases

# Demo 3b: Call Analyzer — Direct SDK (same workload, no ADK)
uv run python main_direct.py    # same interface, ~2.5x faster
```

## File structure

```
adk/
├── calculator/              Demo 1: minimal AgentTool
│   └── main.py
├── db-agent/                Demo 2: AgentTool + SQL + tracing
│   └── main.py
├── call-analyzer/           Demo 3: Skills + parallel execution
│   ├── main.py              ADK version (~10s)
│   ├── main_direct.py       Direct genai SDK (~4s) — same workload
│   ├── tools.py             shared FunctionTools (Python + SQL)
│   ├── skills/              knowledge layer
│   │   ├── registry.toml    skill index (tools, output format)
│   │   ├── scorer.md
│   │   ├── red_flags.md
│   │   └── advisor.md
│   └── test_phrases.txt
├── ARCHITECTURE_PLAN.md     design rationale (McKinsey pyramid)
├── LATENCY.md               latency analysis + benchmarks
└── pyproject.toml
```

## Test cases

### Demo 1 (Calculator)

| Input | Expected |
|-------|----------|
| `hello` | Direct answer, no tool call |
| `2+2` | Tool call → calculator → 4 |

### Demo 2 (Database Agent)

| Input | Expected |
|-------|----------|
| `What is Eve's ID?` | Tool call → db_agent → SQL → ID 5 |
| `How many users?` | Tool call → db_agent → SQL → 6 |
| `Who are the top 3 richest?` | Tool call → db_agent → SQL → Eve, Frank, Alice |

### Demo 3 (Call Analyzer)

| Input | Scorer | Red Flags | Advisor |
|-------|--------|-----------|---------|
| Alice: close accounts | 10/10, HIGH churn | ⚠ closure, ⚠ churn | Retention package |
| Bob: stolen card | 10/10, negative | ⚠ fraud | Freeze card, dispute |
| Charlie: balance inquiry | 2/10, neutral | ✓ No flags | Provide balance |
| Dave: regulator threat | 10/10, negative | ⚠ regulatory | De-escalate, supervisor |

## Links

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK Skills Guide](https://developers.googleblog.com/developers-guide-to-building-adk-agents-with-skills/)
- [ADK GitHub](https://github.com/google/adk-python)
- [Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/agent-builder/adk-overview)
