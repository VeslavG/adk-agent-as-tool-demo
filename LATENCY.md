# Latency Analysis: Multi-Agent ADK on Vertex AI

## Observed: ~14s per tool-call turn

4 sequential LLM calls × ~3.5s each. SQL execution: 0.0ms.

## Where ~3.5s per LLM call goes

| Phase | Time | Notes |
|-------|------|-------|
| **Queueing** | **0.5–2s** | **PayGo shared queue — the main bottleneck** |
| Batching | 100–500ms | TPU waits for batch to fill |
| Inference | 300–600ms | Pre-fill + decode |
| Network | 200–400ms | TLS handshake, Europe → global endpoint |

## How to reduce

| Lever | Impact |
|-------|--------|
| **Provisioned Throughput** | ~2x lower TTFT — bypasses public queue |
| Streaming | -150–200ms perceived latency |
| Context Caching | Shared system prompt cached, skip pre-fill |
| Regional colocation | Cloud Run + Vertex AI in same region |

## Benchmark: ADK vs Direct SDK (April 2025, same Vertex AI project)

### Honest comparison — same tool calls, same LLM round-trips

| Approach | Model | LLM calls | Wall clock (3 concurrent) |
|----------|-------|----------:|--------------------------:|
| ADK + FunctionTools | gemini-3-flash-preview | 2 per agent | **~10s** |
| **Direct genai SDK** | **gemini-3-flash-preview** | **2 per agent** | **~4s** |

Same skills, same tools, same tool-call flow. The 2.5x difference
is pure framework overhead (sessions, event processing, tool wrapping).

### Further optimization — pre-loaded data, no tool calls

| Approach | Model | Region | LLM calls | Latency (1 agent) |
|----------|-------|--------|----------:|------------------:|
| Direct SDK + pre-load | gemini-3-flash-preview | global | 1 | ~2.2s |
| Direct SDK + pre-load | gemini-2.5-flash-lite | europe-west1 | 1 | ~2.2s |

With 3 concurrent agents + pre-load: **~2.5s wall clock**.

## Region latency (gemini-2.5-flash-lite, single call, April 2025)

| Region | Avg latency |
|--------|------------:|
| europe-west1 (Belgium) | 247ms |
| global | 274ms |
| europe-west4 (Netherlands) | 310ms |
| europe-central2 (Warsaw) | 352ms |

Preview models (gemini-3-flash-preview) are only available on `global`.

## Architectural constraint

Delegation costs round-trips. Multi-agent orchestration is inherently
sequential: each agent waits for the next. Fewer agents = lower latency,
but defeats modularity. This is a fundamental trade-off in agentic systems.

The escape hatch: move data retrieval out of the LLM loop. If data needs
are deterministic (customer authenticated via IVR, STT extracts name),
pre-load and inject into the prompt. One LLM call, not two.
