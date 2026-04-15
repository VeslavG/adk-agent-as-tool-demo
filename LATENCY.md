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

## Architectural constraint

Delegation costs round-trips. Multi-agent orchestration is inherently sequential: each agent waits for the next. Fewer agents = lower latency, but defeats modularity. This is a fundamental trade-off in agentic systems.
