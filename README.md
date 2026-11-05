# JARVIS — Personal AI Operating System

> Local-first, cloud-augmented, secure by construction, verifiable action, measurable improvement.

JARVIS is a long-lived, permission-aware personal software agent that can accept multimodal intent, understand personal context, plan bounded tasks, execute actions through appropriate system interfaces, verify observable outcomes, and learn repeatable procedures under supervision.

## Quick Start

### Prerequisites
- Python 3.12+ (tested with 3.14)
- Node.js 22+ with pnpm
- Git

### 1. Clone and Setup Python Backend

```bash
git clone <repo-url> jarvis
cd jarvis

# Create virtual environment and install dependencies
python -m uv venv .venv
python -m uv pip install -e ".[dev]" --python .venv/Scripts/python.exe

# Copy environment config
cp .env.example .env
```

### 2. Run Tests

```bash
.venv/Scripts/python -m pytest tests/ -v
```

Expected: **54 tests passed** (unit, integration, security).

### 3. Start the API Server

```bash
.venv/Scripts/python run_server.py
```

The API is available at `http://127.0.0.1:8000` (localhost only).
- API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

### 4. Start the Desktop UI

```bash
cd apps/desktop
pnpm install
pnpm dev
```

Open http://localhost:3000 — the UI proxies API calls to the backend.

## Architecture

```
User → Desktop UI (React) → Core API (FastAPI) → Orchestrator
         → Policy Engine → Execution Broker → Tool Adapters → Verifier
```

### Core Principles
- **Deny by default**: Every action must pass a deterministic policy check
- **Independent verification**: "Tool returned success" is not enough — verify the actual outcome
- **Scoped capability tokens**: Single-use, time-limited, bound to specific actions
- **Full audit trail**: Every action, decision, and verification is logged
- **LLMs propose, code decides**: Models suggest plans; trusted code authorizes execution

### What Works Today (Phase 0)
- ✅ Task creation, state machine, persistence, restart recovery
- ✅ Deny-by-default policy engine with risk tiers
- ✅ Sandbox file operations (list, read, write — scoped)
- ✅ Full execution pipeline: intent → plan → execute → verify
- ✅ Mock + Ollama model providers
- ✅ Desktop UI with command input, task list, execution trace
- ✅ 54 passing tests including security/adversarial cases

### What's Mocked
- LLM planning uses MockProvider (deterministic responses)
- Approvals are in-memory only
- Memory service is a stub
- No voice, browser automation, or Windows GUI control yet

## Project Structure

```
jarvis/
├── services/              # Python backend
│   ├── contracts/         # Shared Pydantic models and enums
│   ├── core_api/          # FastAPI application and routes
│   ├── orchestrator/      # Task planning and execution loop
│   ├── execution_broker/  # Trusted dispatch boundary
│   ├── policy/            # Deny-by-default authorization
│   ├── task_store/        # SQLite persistence + state machine
│   ├── model_router/      # Mock, Ollama, (Bedrock) providers
│   ├── verifier/          # Independent outcome verification
│   ├── memory/            # Stub for Phase 2
│   └── telemetry/         # Structured logging + metrics
├── apps/desktop/          # React + Vite frontend
├── tests/                 # Unit, integration, security tests
├── sandbox/               # Restricted workspace for tool execution
├── docs/                  # Architecture, plans, threat model
└── data/                  # SQLite database (gitignored)
```

## Security Model

- No network listener outside localhost
- Path traversal detection blocks `..`, UNC paths, absolute paths outside sandbox
- Unregistered tools/actions denied by default
- Capability tokens are single-use and expire in 5 minutes
- R2+ (external write) actions require explicit approval
- Full audit log of every policy decision

## Next Steps

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the detailed roadmap.

## License

Personal project — license TBD.
