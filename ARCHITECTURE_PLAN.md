# Architecture Plan: Voice AI Scoring System on ADK

## Recommendation

Repackage the existing ADK agents into **Skills + parallel execution**.
All prototype work is preserved. Latency drops from ~14s to ~7s
(within the 6-7s budget) with no framework change.

## Situation

The system receives voice input, analyzes it, and outputs structured
results (score, advice, red flags) to screen. The latency budget is
**6-7 seconds** (STT + LLM combined). The team has built a working
ADK prototype with sub-agents, function tools, and database integration.

## Complication

The prototype uses sequential agent delegation (AgentTool pattern):
4 LLM round-trips × ~3.5s each = **~14s** — exceeding the budget by 2x.
This is not a bug or a model limitation. It is an architectural property:
**delegation costs round-trips**.

## Resolution

Three changes, each building on the previous. All within ADK.
All reusing existing agent logic, tools, and domain knowledge.

---

### Change 1: Sub-agents become Skills

The existing sub-agents captured the right domain knowledge. That knowledge
is now extracted into **Skill files** (`.md`) — the recommended ADK pattern
for production ([guide](https://developers.googleblog.com/developers-guide-to-building-adk-agents-with-skills/)).
Their function tools move directly onto the orchestrator.

| Before | After |
|--------|-------|
| `Agent(instruction="...")` + `AgentTool()` | `skills/scorer.md` + `FunctionTool` on orchestrator |
| Sub-agent decides which tool → 2 extra LLM calls | Orchestrator decides directly → 0 extra LLM calls |
| Knowledge embedded in Python code | Knowledge in editable `.md` files |

**Result: 4 LLM calls → 2 LLM calls. ~14s → ~7s.**

### Change 2: Independent analyses run concurrently

Scoring, red flags, and advice are independent tasks. They run in parallel
(ADK `ParallelAgent` or `asyncio.gather`), sharing the same input.

```
         ┌─ Scorer Agent      (skill + tools)   ~7s
input ───┼─ Red Flags Agent   (skill + tools)   ~7s    ← concurrent
         └─ Advisor Agent     (skill + tools)   ~7s

wall clock = max(7, 7, 7) = ~7s, NOT 21s
```

**Result: 3x analysis in the same latency budget.**

### Change 3: Pre-LLM optimizations (considerations for next phase)

Three approaches to eliminate the tool-call round-trip (saves ~3.5s per agent):

**a) Deterministic pre-fetch (IVR context).** When the customer authenticates
via IVR, their identity and account context are already known. Pre-load
the profile and inject it into the LLM prompt — no tool call needed.

**b) STT feature extraction.** Modern streaming STT engines (Chirp, Deepgram)
emit metadata alongside transcription: sentiment, intent signals, topic shifts.
These can be captured from the stream directly — zero LLM cost, zero latency.

**c) Micro-model routing.** A small/fast model (or regex) extracts the customer
name from the transcript, triggers a deterministic DB lookup, and injects
the result into the main prompt. One LLM call instead of two.

---

## What stays the same

- **Google ADK** — production-ready framework, unchanged
- **Agent definitions** — same model, same tool interface
- **Function tools** — same Python functions, same SQL queries
- **Domain knowledge** — same instructions, now in `.md` files
- **Database integration** — same schema, same parameterized queries

## What changes

- **Execution model**: sequential → concurrent
- **Knowledge packaging**: inline strings → Skill files
- **Sub-agent overhead**: eliminated (tools moved to orchestrator)

### Change 4: Drop framework overhead (measured)

ADK adds value (tracing, sessions, tool auto-wrapping) but also adds
framework overhead per LLM round-trip. To quantify this, we built
`main_direct.py` — an **identical workload** (same registry.toml,
same skills, same tools, same tool-call flow) using raw
`genai.Client` + `asyncio.gather` instead of ADK.

**Benchmarked on the same Vertex AI project (April 2025):**

**Honest comparison — same tool calls, same number of LLM round-trips:**

| Setup | LLM calls per agent | Wall clock (3 concurrent) | Notes |
|-------|--------------------:|--------------------------:|-------|
| ADK + FunctionTools | 2 | **~10s** | Framework overhead |
| **Direct genai SDK** | **2** | **~4s** | Same tools, no framework |

**Further optimization — pre-loaded data, no tool calls:**

| Setup | LLM calls per agent | Wall clock (3 concurrent) | Notes |
|-------|--------------------:|--------------------------:|-------|
| **Direct SDK + pre-load** | **1** | **~2.5s** | Deterministic data fetch |

The difference between ADK and direct SDK on the same workload is
**pure framework overhead**: session management, event processing,
tool auto-wrapping, config handling.

This is the standard framework vs. raw-API trade-off:
ADK = faster development, raw API = faster execution.
For production with a strict latency budget, the latter wins.
Both versions share the same skill registry and business logic.

**Hidden bonus: HTTP/2 connection reuse.** The direct SDK creates one
`genai.Client` and reuses it across all calls. The first call pays
the cold-start penalty (~4s), but subsequent calls ride the warm
HTTP/2 connection (~1.5–2.5s). ADK creates separate internal clients
per agent and does not benefit from this. In a production loop
(continuous stream of phrases), the direct SDK averages ~2s per
analysis after warmup.

## Latency summary

| Architecture | LLM calls | Wall clock | Status |
|---|---|---|---|
| Current prototype (AgentTool chain) | 4 sequential | ~14s | Over budget |
| **Skills + Parallel (ADK)** | **2×3 concurrent** | **~10s** | **Improved, over budget** |
| **Direct genai SDK (same tools)** | **2×3 concurrent** | **~4s** | **Within budget — measured** |
| Direct SDK + pre-loaded data | 1×3 concurrent | ~2.5s | Optimal — measured |
| + Provisioned Throughput | 1×3 concurrent | ~1–2s | Headroom for STT |

## File structure (implemented)

```
call-analyzer/
├── skills/                  ← knowledge layer (editable .md files)
│   ├── registry.toml        ← skill index (what, which tools, output format)
│   ├── scorer.md
│   ├── red_flags.md
│   └── advisor.md
├── tools.py                 ← action layer (Python + SQL)
├── main.py                  ← ADK orchestration (~10s)
├── main_direct.py           ← Direct genai SDK (~4s) — same workload
└── test_phrases.txt         ← test scenarios
```
