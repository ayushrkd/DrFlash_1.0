# ADR-0001: Initial Architecture — Modular Monolith with Trusted Execution Boundary

**Status:** Accepted  
**Date:** 2026-11-06  
**Deciders:** Owner + JARVIS AI Architect

## Context

JARVIS is a personal AI operating system that needs to:
1. Execute real actions on the local machine safely
2. Plan tasks using LLMs without trusting their outputs for authorization
3. Be modular enough to swap models, tools, and providers
4. Be simple enough for a single developer to maintain
5. Start locally without any cloud dependencies

## Decision

### Architecture: Modular Monolith
- All services (orchestrator, policy, broker, store, router, verifier) run in one Python process
- They communicate through typed interfaces, not HTTP/gRPC
- A separate process is warranted only for the Windows UIA worker (.NET, different runtime)
- Split into microservices only when concurrency, scaling, or language boundaries demand it

### Execution Model: Trusted Boundary via Execution Broker
- The LLM/orchestrator can **propose** actions, never **execute** them directly
- The Execution Broker is the single choke point where policy is enforced
- Every action goes through: Policy Check → Token Issue → Dispatch → Verify → Audit
- The policy engine is deterministic code, not LLM instructions

### Storage: SQLite with WAL Mode
- Single-user system; no need for Postgres yet
- WAL mode gives concurrent read performance
- All data persists across restarts
- Migrate to Postgres when memory/vector search or multi-worker access requires it

### Model Routing: Provider Abstraction
- ModelRouter dispatches to providers by role (FAST_INTENT, LOCAL_DIALOG, etc.)
- MockProvider enables zero-dependency development and testing
- OllamaProvider connects to local models already installed
- BedrockProvider to be added behind feature flag

### Frontend: Vite + React (no Electron yet)
- Start as a web app at localhost:3000
- Add Electron shell later when system tray, hotkeys, and native integrations needed
- Vite proxies API calls to FastAPI at localhost:8000

## Consequences

### Positive
- Zero cloud dependency to boot
- 54 tests pass from fresh clone
- Any component can be replaced without touching others
- Security model is enforced in code, not in prompts
- Full audit trail for every action

### Negative
- Single Python process means no crash isolation between services
- SQLite won't handle concurrent writes from multiple workers
- No real-time streaming yet (polling-based)

### Risks
- Python 3.14 is very new; may need compatibility patches
- Mock provider doesn't test real LLM behavior

## Alternatives Considered

1. **Microservices from day 1** — Rejected: adds deployment complexity without justification for a single-user system
2. **LangGraph for orchestration** — Deferred: evaluate when persistence/human-in-loop patterns are needed; current state machine is simpler
3. **PostgreSQL from day 1** — Deferred: SQLite is sufficient and simpler for Phase 0/1
4. **Tauri instead of Electron** — Deferred: evaluate if Electron memory footprint is a problem
