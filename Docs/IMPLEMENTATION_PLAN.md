# JARVIS — Implementation Plan

> Phase 0/1 Architecture, Technology Decisions, and Acceptance Criteria  
> Created: 2026-11-06

## Architecture Overview

JARVIS is built as a **modular monolith** — logically separated services sharing one Python process, with a strict internal protocol. This avoids premature microservice complexity while keeping components independently testable and replaceable.

```
┌──────────────────────────────────────────────────────────┐
│                    Desktop UI (React/Vite)               │
│  Command Input │ Task List │ Event Trace │ Approval Queue │
└─────────────────────────┬────────────────────────────────┘
                          │ HTTP (localhost:3000 → 8000)
┌─────────────────────────▼────────────────────────────────┐
│                   Core API (FastAPI)                      │
│  /tasks │ /approvals │ /tools │ /health │ /privacy       │
├──────────────────────────────────────────────────────────┤
│                     Orchestrator                          │
│  Intent → Plan → Execute → Verify → Complete/Fail        │
├──────────────────────────────────────────────────────────┤
│              Execution Broker (trusted boundary)          │
│  Policy Engine │ Tool Registry │ Scoped Dispatch │ Audit  │
├──────────┬───────────────┬───────────────────────────────┤
│ Tool     │ Sandbox Files │ (Browser Agent, future)       │
│ Adapters │ Windows UIA   │ (Code Sandbox, future)        │
├──────────┴───────────────┴───────────────────────────────┤
│  Model Router │ Task Store (SQLite) │ Verifier │ Memory  │
└──────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Deny-by-Default Policy Engine
Every tool call must pass through the policy engine before execution. Unregistered tools, unknown actions, and out-of-scope paths are denied. This runs as deterministic code, not LLM instructions.

### 2. Mock-First Model Routing
The system boots and functions fully with a `MockProvider` — zero cloud dependencies. The `OllamaProvider` is available for local models. Bedrock integration is behind a feature flag for Phase 2+.

### 3. SQLite for Phase 0/1
Good enough for single-user, with WAL mode for concurrent reads. Migration to PostgreSQL + pgvector when semantic memory or concurrency demands it.

### 4. Scoped Capability Tokens
Every authorized action gets a single-use, time-limited token bound to a specific tool + action + resource scope. Replay protection built in.

### 5. Independent Outcome Verification
The verifier is separate from the tool itself. It independently checks file existence, content hashes, state changes, and expected outcomes.

## Implementation Order (Phase 0 — complete)

| # | Component | Status |
|---|-----------|--------|
| 1 | Environment probe & ENVIRONMENT.md | ✅ Done |
| 2 | Contracts (Pydantic models, enums, state machine) | ✅ Done |
| 3 | Policy Engine (deny-by-default, scope validation, tokens) | ✅ Done |
| 4 | Task Store (SQLite, state machine, events, persistence) | ✅ Done |
| 5 | Model Router (MockProvider, OllamaProvider, routing) | ✅ Done |
| 6 | Execution Broker (registry, policy check, dispatch, audit) | ✅ Done |
| 7 | Outcome Verifier (file hash, state change, expected outcome) | ✅ Done |
| 8 | Sandbox File Tools (list, read, write_report — scoped) | ✅ Done |
| 9 | Orchestrator (intent → plan → execute → verify loop) | ✅ Done |
| 10 | Core API (FastAPI, tasks, approvals, health, tools, events) | ✅ Done |
| 11 | Desktop UI (React/Vite, command input, task list, trace viewer) | ✅ Done |
| 12 | Test Suite (54 tests: unit, integration, security/adversarial) | ✅ 54/54 |

## Phase 1 — Next Steps

| # | Deliverable | Priority |
|---|-------------|----------|
| 1 | Switch model router to Ollama for real LLM planning | High |
| 2 | Browser Playwright connector with sample test site | High |
| 3 | Approval workflow (UI cards, approval tokens, expiry) | High |
| 4 | Checkpoint/restart with failure recovery | High |
| 5 | C# Windows UIA inspector (read-only) | Medium |
| 6 | WebSocket/SSE streaming for real-time events | Medium |
| 7 | Local ASR/TTS voice spike (sherpa-onnx) | Medium |
| 8 | Bedrock provider adapter (behind feature flag) | Medium |
| 9 | Memory service with SQLite + embeddings | Later |
| 10 | Cost tracking dashboard in UI | Later |

## Risks

| Risk | Mitigation |
|------|-----------|
| Python 3.14 is very new; some libs may break | Tested: all 50 packages installed and working |
| 8GB VRAM limits concurrent models | One model at a time; swap via Ollama |
| Mock provider doesn't produce real plans | Toggle to Ollama when ready; interface unchanged |
| SQLite doesn't scale to concurrent workers | Migrate to Postgres when justified |
| No auth on localhost API | Single-user local system; add auth before any remote access |

## Test Coverage

- **Unit (14 tests):** Policy deny-by-default, scope enforcement, path traversal, risk tiers, capability tokens, task state machine, events, persistence, model routing
- **Integration (8 tests):** Full task pipeline, file operations through broker, API endpoints, audit trail
- **Security (8 tests):** Path traversal, unauthorized tools/actions, version mismatch, scope isolation, UNC paths, audit completeness
- **API (11 tests):** Health, models, tools, privacy, CRUD tasks, run, cancel, events

All 54 tests pass ✅
